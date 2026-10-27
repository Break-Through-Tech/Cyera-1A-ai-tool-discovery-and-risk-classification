"""AI Determination for one Tool Candidate (ADR 0001, ADR 0002).

By default the evidence text is the fetched homepage, and a supplied Dataset B functionality
description stands in only when no homepage was extracted. ``prefer_supplied`` reverses that
order so the two strategies can be compared. The gate settles text with no AI
signal without a model call; everything else goes to Jev, then a separate Jev request
scores each sentence as evidence.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from app.ai_determination import gate as gate_module
from app.ai_determination.gate import MIN_TEXT_CHARS, SNIPPET_CHARS, gate, sentences
from app.ai_determination.jev import (
    EVIDENCE_INSTRUCTIONS,
    MODEL,
    QUESTIONS,
    Judge,
)
from app.enrichment.fetch import Capture
from app.pipeline.identity import CandidateIdentity, ToolMetadataSnapshot, normalize_name

AI_CUTOFF = 0.4
REVIEW_EVIDENCE_CUTOFF = 0.6
TOP_EVIDENCE = 3
FULL_TEXT_CHARS = 12000
EVIDENCE_SENTENCES = 60
EVIDENCE_MIN_CHARS = 20


def configuration_version(prefer_supplied: bool = False) -> str:
    """Hash of everything that decides the outcome: gate, questions, model, cutoffs and source preference."""
    configuration = {
        "keyword": gate_module.KEYWORD.pattern,
        "capability": gate_module.CAPABILITY.pattern,
        "min_text_chars": MIN_TEXT_CHARS,
        "snippet_chars": SNIPPET_CHARS,
        "questions": QUESTIONS,
        "evidence_instructions": EVIDENCE_INSTRUCTIONS,
        "model": MODEL,
        "ai_cutoff": AI_CUTOFF,
        "review_evidence_cutoff": REVIEW_EVIDENCE_CUTOFF,
        "top_evidence": TOP_EVIDENCE,
        "full_text_chars": FULL_TEXT_CHARS,
        "evidence_sentences": EVIDENCE_SENTENCES,
        "evidence_min_chars": EVIDENCE_MIN_CHARS,
        "source_policy": "supplied_description_first" if prefer_supplied else "homepage_first",
        "supplied_text_exempt_from_min_chars": True,
    }
    canonical = json.dumps(configuration, sort_keys=True, ensure_ascii=False)
    return f"jev-cascade:sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


@dataclass(frozen=True)
class EvidenceSource:
    """Where the judged text came from: a Dataset B row or a homepage capture."""

    kind: str
    reference: str
    captured_at: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class EvidenceSentence:
    sentence: str
    probability: float


@dataclass(frozen=True)
class AiDetermination:
    determination: str
    stage: str
    source: EvidenceSource | None = None
    reason: str | None = None
    model: str | None = None
    probabilities: Mapping[str, float] | None = None
    evidence: tuple[EvidenceSentence, ...] = ()
    needs_review: bool = False


@dataclass(frozen=True)
class EvidenceText:
    title: str
    meta_description: str
    headings: str
    body: str
    gated_text: str
    supplied: bool


def determine_ai(
    candidate: CandidateIdentity,
    captures_by_domain: Mapping[str, Capture],
    metadata: ToolMetadataSnapshot,
    judge: Judge,
    prefer_supplied: bool = False,
) -> AiDetermination:
    found = evidence_text(candidate, captures_by_domain, metadata, prefer_supplied)
    if isinstance(found, str):
        return AiDetermination("unresolved", "no_evidence", reason=found)
    source, text = found

    if not gate(text.gated_text):
        # The length floor catches parked and empty pages; a short supplied description is still a description.
        if not text.supplied and len(text.gated_text.strip()) < MIN_TEXT_CHARS:
            return AiDetermination("unresolved", "insufficient_text", source)
        return AiDetermination("non_ai", "keyword_gate", source)

    state = {
        "title": text.title,
        "meta_description": text.meta_description,
        "headings": text.headings,
        "page_text": text.body[:FULL_TEXT_CHARS],
    }
    decision = judge({"model": MODEL, "state": state, "questions": QUESTIONS})
    answers = decision["answers"]
    probabilities = answers["determination"]["probabilities"]
    determination = _decide(probabilities)
    evidence = _evidence(state, text, judge)
    return AiDetermination(
        determination,
        "jev_judge",
        source,
        model=decision["model"],
        probabilities={
            "ai": probabilities["ai"],
            "non_ai": probabilities["non_ai"],
            "unresolved": probabilities["unresolved"],
            **{name: answers[name]["noul"] for name in QUESTIONS if name != "determination"},
        },
        evidence=evidence[:TOP_EVIDENCE],
        needs_review=determination == "ai"
        and (not evidence or evidence[0].probability < REVIEW_EVIDENCE_CUTOFF),
    )


def evidence_text(
    candidate: CandidateIdentity,
    captures_by_domain: Mapping[str, Capture],
    metadata: ToolMetadataSnapshot,
    prefer_supplied: bool,
) -> tuple[EvidenceSource, EvidenceText] | str:
    """The preferred of an extracted homepage and a non-empty supplied description, else why neither exists."""
    capture = captures_by_domain.get(candidate.domain)
    homepage = _homepage_text(capture)
    supplied = _supplied_text(candidate, metadata)
    found = (supplied or homepage) if prefer_supplied else (homepage or supplied)
    if found is not None:
        return found
    return capture.outcome if capture is not None else "not_fetched"


def _homepage_text(capture: Capture | None) -> tuple[EvidenceSource, EvidenceText] | None:
    if capture is None or capture.outcome != "extracted":
        return None
    title = capture.title or ""
    meta = capture.metadata.get("description") or capture.metadata.get("og:description") or ""
    headings = " | ".join(capture.headings)
    body = capture.main_text or ""
    source = EvidenceSource(
        "homepage", capture.final_url or capture.requested_url, capture.captured_at
    )
    return source, EvidenceText(
        title, meta, headings, body, " ".join((title, meta, headings, body)), supplied=False
    )


def _supplied_text(
    candidate: CandidateIdentity, metadata: ToolMetadataSnapshot
) -> tuple[EvidenceSource, EvidenceText] | None:
    row = metadata.find(candidate.domain, normalize_name(candidate.application_names[0]))
    description = (row or {}).get("functionality_text", "").strip()
    if not row or not description:
        return None
    source = EvidenceSource("supplied_description", row["metadata_id"], version=metadata.version)
    return source, EvidenceText(row["application_name"], description, "", "", description, supplied=True)


def _decide(probabilities: Mapping[str, float]) -> str:
    if probabilities["ai"] >= AI_CUTOFF:
        return "ai"
    return max(("non_ai", "unresolved"), key=lambda k: probabilities[k])


def _evidence(state: Mapping[str, str], text: EvidenceText, judge: Judge) -> tuple[EvidenceSentence, ...]:
    """Every candidate sentence scored in one request separate from the decision, strongest first."""
    candidates = _evidence_sentences(text)
    if not candidates:
        return ()
    questions = {
        f"e{i}": {"type": "noul", "instructions": EVIDENCE_INSTRUCTIONS.format(sentence)}
        for i, sentence in enumerate(candidates)
    }
    answers = judge({"model": MODEL, "state": dict(state), "questions": questions})["answers"]
    scored = [
        EvidenceSentence(sentence, answers[f"e{i}"]["noul"]) for i, sentence in enumerate(candidates)
    ]
    return tuple(sorted(scored, key=lambda e: e.probability, reverse=True))


def _evidence_sentences(text: EvidenceText) -> list[str]:
    """Title, meta description, then gate-matching sentences, then the rest, up to EVIDENCE_SENTENCES."""
    body = [
        s[:SNIPPET_CHARS]
        for source in (text.headings, text.body)
        for s in sentences(source)
        if len(s) >= EVIDENCE_MIN_CHARS
    ]
    ordered = [text.title, text.meta_description]
    ordered += [s for s in body if gate(s)] + [s for s in body if not gate(s)]
    unique: list[str] = []
    for sentence in ordered:
        if sentence and sentence not in unique:
            unique.append(sentence)
    return unique[:EVIDENCE_SENTENCES]
