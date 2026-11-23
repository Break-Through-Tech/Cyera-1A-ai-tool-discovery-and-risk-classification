"""Resolve a typed Evidence reference to the stored source behind a claim. Read-only.

Record references pin the producing Run (Batch-qualified) and one record in it; only a
succeeded Run exposes findings, though an ``analysis_run`` reference returns any Run's
status record. Each result carries an explicit role, so observed activity, analysis and
model outputs, synthetic policy, vendor claims and governance guidance stay distinct.
Aggregate references are not resolved here: they route to the scoped listing operations.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import Connection, select

from app.assistant.contracts import Contract, RecordEvidence, RunReference, Text
from app.batches import get_batch
from app.db.tables import (
    activity_events,
    ai_determinations,
    category_classifications,
    usage_context_assessments,
    website_captures,
)
from app.errors import AppError
from app.pipeline.identity import ToolMetadataSnapshot
from app.runs import Run, get_run

MAX_TEXT_CHARS = 4000
MAX_ITEMS = 50
LISTING_OPERATIONS = ("GET /overview", "GET /applications", "GET /contexts", "GET /events")

Role = Literal[
    "observed_activity",  # an uploaded Activity Event
    "analysis_result",  # a deterministic stage result, such as a Usage Context assessment
    "analysis_provenance",  # an Analysis Run's status and versions
    "model_output",  # a model-produced score or retrieval result
    "synthetic_policy",  # supplied synthetic Tool metadata and policy assumptions
    "vendor_claim",  # what a vendor's website or catalog listing says
    "governance_guidance",  # a retrieved governance passage
]
Number = Annotated[int, Field(strict=True, ge=1, le=999_999_999)]
Name = Annotated[Text, Field(max_length=512)]


class ActivityEventReference(Contract):
    kind: Literal["activity_event"] = "activity_event"
    run: RunReference
    event_id: Name


class UsageContextReference(Contract):
    """A Usage Context and its stored contextual-risk assessment."""

    kind: Literal["usage_context"] = "usage_context"
    run: RunReference
    context_number: Number


class AnalysisRunReference(Contract):
    kind: Literal["analysis_run"] = "analysis_run"
    run: RunReference


class AiEvidenceSentenceReference(Contract):
    """One scored sentence of a Tool Candidate's AI Determination, 1-based, strongest first."""

    kind: Literal["ai_evidence_sentence"] = "ai_evidence_sentence"
    run: RunReference
    candidate_number: Number
    sentence_number: Number


class WebsiteCaptureReference(Contract):
    kind: Literal["website_capture"] = "website_capture"
    run: RunReference
    domain: Name


class ToolMetadataReference(Contract):
    """A synthetic Tool metadata row in the snapshot version the Run recorded."""

    kind: Literal["tool_metadata"] = "tool_metadata"
    run: RunReference
    metadata_id: Name


class CategoryNeighborReference(Contract):
    """One Semantic Neighbor of a Tool Candidate's Category Classification, 1-based."""

    kind: Literal["category_neighbor"] = "category_neighbor"
    run: RunReference
    candidate_number: Number
    neighbor_number: Number


class PassageReference(Contract):
    """A governance or source passage, identified like ``PassageEvidence``."""

    kind: Literal["passage"] = "passage"
    corpus_version: Name
    document_id: Name
    document_version: Name
    passage_id: Name


class AggregateReference(BaseModel):
    """Accepted with any ``AggregateEvidence`` fields, only to be routed to the listings."""

    model_config = ConfigDict(extra="allow", frozen=True)
    kind: Literal["aggregate"] = "aggregate"


RecordReference = (
    ActivityEventReference
    | UsageContextReference
    | AnalysisRunReference
    | AiEvidenceSentenceReference
    | WebsiteCaptureReference
    | ToolMetadataReference
    | CategoryNeighborReference
)
EvidenceReference = Annotated[
    RecordReference | PassageReference | AggregateReference, Field(discriminator="kind")
]
_RECORD_ADAPTER = TypeAdapter(Annotated[RecordReference, Field(discriminator="kind")])


class SourceIdentity(Contract):
    type: str
    id: str
    batch_id: str | None = None
    run_id: str | None = None
    version: str | None = None
    url: str | None = None


class Applicability(Contract):
    """What the source applies to and what it does not establish."""

    subject_type: Literal[
        "activity_event", "usage_context", "analysis_run", "tool_candidate", "domain",
        "tool_metadata", "passage",
    ]
    subject_id: str
    statement: str


class Truncation(Contract):
    field: str
    unit: Literal["characters", "items"]
    returned: int
    total: int


class ResolvedEvidence(Contract):
    reference: EvidenceReference
    role: Role
    source: SourceIdentity
    # Named UTC timestamps, e.g. ``occurred_at``, ``captured_at`` and ``run_completed_at``.
    dates: dict[str, str | None]
    applicability: Applicability
    versions: dict[str, str]
    record: dict[str, JsonValue]
    truncated: bool = False
    truncations: tuple[Truncation, ...] = ()


class EvidenceError(AppError):
    """A reference that cannot be resolved; ``status_code`` follows the API error rules."""


PassageResolver = Callable[[Connection, PassageReference], ResolvedEvidence]


@dataclass(frozen=True)
class EvidenceSources:
    """Versioned sources held outside the database; a missing one is reported unavailable."""

    tool_metadata: ToolMetadataSnapshot | None = None
    passages: PassageResolver | None = None


def resolve_evidence(
    connection: Connection,
    reference: RecordReference | PassageReference | AggregateReference,
    sources: EvidenceSources = EvidenceSources(),
) -> ResolvedEvidence:
    """The record or retained excerpt behind ``reference``, or an ``EvidenceError``.

    404: unknown Run, record or source version; 409: findings of a non-succeeded Run;
    422: an aggregate reference; 501: a source this backend does not hold (passages).
    """
    if isinstance(reference, AggregateReference):
        raise EvidenceError(
            422,
            "aggregate_reference_not_resolvable",
            "Aggregate references are opened through their scoped listing operation.",
            {"listing_operations": list(LISTING_OPERATIONS)},
        )
    if isinstance(reference, PassageReference):
        if sources.passages is None:
            raise EvidenceError(
                501,
                "passage_corpus_unavailable",
                "No governance passage corpus is available to resolve this reference.",
            )
        return sources.passages(connection, reference)
    if isinstance(reference, AnalysisRunReference):
        return _analysis_run(reference, _run(connection, reference.run))
    run = _run(connection, reference.run)
    if run.status != "succeeded":
        raise EvidenceError(
            409, "run_not_succeeded", "Only a succeeded Analysis Run has results."
        )
    resolve = _RESOLVERS[type(reference)]
    return resolve(connection, reference, run, sources)


def record_reference(run: RunReference, record_type: str, record_id: str) -> RecordReference:
    """The typed reference a ``RecordEvidence`` record type and ID denote (422 if invalid).

    IDs: an event ID, a context number, the Run ID, a domain, a metadata ID, or
    ``"<candidate_number>:<n>"`` for an AI evidence sentence or Category neighbor.
    """
    fields: dict[str, Any] = {"kind": record_type, "run": run}
    match record_type:
        case "activity_event":
            fields["event_id"] = record_id
        case "usage_context":
            fields["context_number"] = _number(record_id)
        case "analysis_run":
            if record_id != run.run_id:
                raise _invalid("analysis_run record ID must be its Run ID")
        case "website_capture":
            fields["domain"] = record_id
        case "tool_metadata":
            fields["metadata_id"] = record_id
        case "ai_evidence_sentence" | "category_neighbor":
            candidate, _, item = record_id.partition(":")
            item_field = (
                "sentence_number" if record_type == "ai_evidence_sentence" else "neighbor_number"
            )
            fields |= {"candidate_number": _number(candidate), item_field: _number(item)}
        case _:
            raise _invalid("Unsupported record type")
    try:
        return _RECORD_ADAPTER.validate_python(fields)
    except ValidationError as error:
        raise _invalid("Invalid record reference") from error


def from_record_evidence(evidence: RecordEvidence) -> RecordReference:
    return record_reference(evidence.run, evidence.record_type, evidence.record_id)


def to_record_evidence(reference: RecordReference, evidence_id: str) -> RecordEvidence:
    """Raises ``ValidationError`` for a kind ``RecordEvidence.record_type`` does not yet list."""
    return RecordEvidence(
        evidence_id=evidence_id,
        run=reference.run,
        record_type=reference.kind,
        record_id=_record_id(reference),
    )


def _record_id(reference: RecordReference) -> str:
    match reference:
        case ActivityEventReference():
            return reference.event_id
        case UsageContextReference():
            return str(reference.context_number)
        case AnalysisRunReference():
            return reference.run.run_id
        case WebsiteCaptureReference():
            return reference.domain
        case ToolMetadataReference():
            return reference.metadata_id
        case AiEvidenceSentenceReference():
            return f"{reference.candidate_number}:{reference.sentence_number}"
        case CategoryNeighborReference():
            return f"{reference.candidate_number}:{reference.neighbor_number}"
    raise TypeError(reference)


@dataclass
class _Bounds:
    """Bounds long text and lists, recording each cut so it is never silent."""

    truncations: list[Truncation] = field(default_factory=list)

    def text(self, name: str, value: str | None) -> str | None:
        if value is None or len(value) <= MAX_TEXT_CHARS:
            return value
        self.truncations.append(
            Truncation(field=name, unit="characters", returned=MAX_TEXT_CHARS, total=len(value))
        )
        return value[:MAX_TEXT_CHARS]

    def items(self, name: str, values: Sequence) -> list:
        if len(values) > MAX_ITEMS:
            self.truncations.append(
                Truncation(field=name, unit="items", returned=MAX_ITEMS, total=len(values))
            )
        return list(values[:MAX_ITEMS])

    def result(self, **fields: Any) -> ResolvedEvidence:
        cuts = tuple(self.truncations)
        return ResolvedEvidence(**fields, truncated=bool(cuts), truncations=cuts)


def _activity_event(
    connection: Connection, reference: ActivityEventReference, run: Run, _: EvidenceSources
) -> ResolvedEvidence:
    row = _one(
        connection,
        select(activity_events).where(
            activity_events.c.batch_id == run.batch_id,
            activity_events.c.event_id == reference.event_id,
        ),
        "activity_event_not_found",
        "Activity Event not found in this Batch.",
    )
    batch = get_batch(connection, run.batch_id)
    bounds = _Bounds()
    return bounds.result(
        reference=reference,
        role="observed_activity",
        source=SourceIdentity(
            type="activity_event", id=row["event_id"], batch_id=run.batch_id, run_id=run.run_id,
            version=f"sha256:{batch.sha256}",
        ),
        dates={"occurred_at": row["occurred_at"], "batch_uploaded_at": batch.uploaded_at},
        applicability=Applicability(
            subject_type="activity_event",
            subject_id=row["event_id"],
            statement=(
                "One observed Activity Event as uploaded; evidence of activity, not of Tool "
                "identity, purpose, data sensitivity or risk. Usage Purpose and Data "
                "Sensitivity Tier are supplied, not inferred."
            ),
        ),
        versions={"batch_schema": batch.schema_version},
        record={
            k: bounds.text(k, v) if isinstance(v, str) else v
            for k, v in row.items()
            if k != "batch_id"
        },
    )


def _usage_context(
    connection: Connection, reference: UsageContextReference, run: Run, _: EvidenceSources
) -> ResolvedEvidence:
    table = usage_context_assessments
    row = _one(
        connection,
        select(table).where(
            table.c.run_id == run.run_id, table.c.context_number == reference.context_number
        ),
        "usage_context_not_found",
        "Usage Context not found in this Analysis Run.",
    )
    bounds = _Bounds()
    record = {k: v for k, v in row.items() if k != "run_id"}
    record["event_ids"] = bounds.items("event_ids", row["event_ids"])
    return bounds.result(
        reference=reference,
        role="analysis_result",
        source=SourceIdentity(
            type="usage_context_assessment", id=str(row["context_number"]),
            batch_id=run.batch_id, run_id=run.run_id, version=row["rule_version"],
        ),
        dates=_run_dates(
            run,
            first_observed_at=row["first_observed_at"],
            last_observed_at=row["last_observed_at"],
        ),
        applicability=Applicability(
            subject_type="usage_context",
            subject_id=str(row["context_number"]),
            statement=(
                "A deterministic contextual-risk assessment of this Usage Context over its "
                "original Batch period; not a global Tool risk, a Policy Status decision or "
                "a compliance determination. Its facts come from synthetic Tool metadata "
                "(metadata_id)."
            ),
        ),
        versions={
            "rule_version": row["rule_version"],
            **_versions(run, "risk_assessment", "tool_metadata_snapshot"),
        },
        record=record,
    )


def _analysis_run(reference: AnalysisRunReference, run: Run) -> ResolvedEvidence:
    return ResolvedEvidence(
        reference=reference,
        role="analysis_provenance",
        source=SourceIdentity(
            type="analysis_run", id=run.run_id, batch_id=run.batch_id, run_id=run.run_id,
            version=run.code_commit,
        ),
        dates=_run_dates(run, run_started_at=run.started_at),
        applicability=Applicability(
            subject_type="analysis_run",
            subject_id=run.run_id,
            statement=(
                "The Run's status, timestamps and versions. Only a succeeded Run exposes "
                "findings; a failed Run's status record is not a finding."
            ),
        ),
        versions=dict(run.versions),
        record={
            "status": run.status,
            "attempt_number": run.attempt_number,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "code_commit": run.code_commit,
            "failure_summary": run.failure_summary,
            "failure_phase": run.failure_phase,
        },
    )


_SOURCE_ROLES: Mapping[str, Role] = {
    "homepage": "vendor_claim",
    "catalog": "vendor_claim",
    "supplied_description": "synthetic_policy",
}
_SOURCE_VERSIONS = {
    "homepage": "website_enrichment",
    "catalog": "known_tool_registry",
    "supplied_description": "tool_metadata_snapshot",
}


def _ai_evidence_sentence(
    connection: Connection, reference: AiEvidenceSentenceReference, run: Run, _: EvidenceSources
) -> ResolvedEvidence:
    row = _candidate_row(connection, ai_determinations, run, reference.candidate_number)
    sentences = row["evidence"]
    if reference.sentence_number > len(sentences):
        raise EvidenceError(
            404,
            "evidence_sentence_not_found",
            "AI evidence sentence not found for this Tool Candidate.",
            {"sentence_count": len(sentences)},
        )
    sentence = sentences[reference.sentence_number - 1]
    source = row["source"]
    bounds = _Bounds()
    return bounds.result(
        reference=reference,
        # The sentence quotes its source; its score is model output, labelled in ``scored_by``.
        role=_SOURCE_ROLES[source["kind"]],
        source=SourceIdentity(
            type=source["kind"], id=source["reference"], batch_id=run.batch_id,
            run_id=run.run_id, version=source.get("version"),
            url=source["reference"] if source["kind"] == "homepage" else None,
        ),
        dates=_run_dates(run, captured_at=source.get("captured_at")),
        applicability=Applicability(
            subject_type="tool_candidate",
            subject_id=str(reference.candidate_number),
            statement=(
                "A sentence from the text this Tool Candidate's AI Determination judged, "
                "scored for showing the Tool's own AI work. It supports, but does not by "
                "itself establish, AI status; an AI Mention never does."
            ),
        ),
        versions=_versions(run, "ai_determination", _SOURCE_VERSIONS[source["kind"]]),
        record={
            "candidate_number": reference.candidate_number,
            "sentence_number": reference.sentence_number,
            "sentence_count": len(sentences),
            "sentence": bounds.text("sentence", sentence["sentence"]),
            "scored_by": {
                "role": "model_output",
                "model": row["model"],
                "stage": row["stage"],
                "probability": sentence["probability"],
            },
            "determination": {
                "determination": row["determination"],
                "stage": row["stage"],
                "reason": row["reason"],
                "needs_review": row["needs_review"],
            },
        },
    )


def _website_capture(
    connection: Connection, reference: WebsiteCaptureReference, run: Run, _: EvidenceSources
) -> ResolvedEvidence:
    row = _one(
        connection,
        select(website_captures).where(
            website_captures.c.run_id == run.run_id, website_captures.c.domain == reference.domain
        ),
        "website_capture_not_found",
        "Website capture not found in this Analysis Run.",
    )
    bounds = _Bounds()
    return bounds.result(
        reference=reference,
        role="vendor_claim",
        source=SourceIdentity(
            type="website_capture", id=row["domain"], batch_id=run.batch_id, run_id=run.run_id,
            url=row["final_url"] or row["requested_url"],
        ),
        dates=_run_dates(run, captured_at=row["captured_at"]),
        applicability=Applicability(
            subject_type="domain",
            subject_id=row["domain"],
            statement=(
                "The vendor's public homepage as captured at captured_at; unverified vendor "
                "claims. A capture whose outcome is not 'extracted' retained no page text."
            ),
        ),
        versions=_versions(run, "website_enrichment"),
        record={
            "requested_url": row["requested_url"],
            "final_url": row["final_url"],
            "outcome": row["outcome"],
            "detail": row["detail"],
            "title": bounds.text("title", row["title"]),
            "page_metadata": {
                key: bounds.text(f"page_metadata.{key}", value)
                for key, value in row["page_metadata"].items()
            },
            "headings": [
                bounds.text("headings", h) for h in bounds.items("headings", row["headings"])
            ],
            "main_text": bounds.text("main_text", row["main_text"]),
        },
    )


def _tool_metadata(
    connection: Connection, reference: ToolMetadataReference, run: Run, sources: EvidenceSources
) -> ResolvedEvidence:
    snapshot = sources.tool_metadata
    if snapshot is None:
        raise EvidenceError(
            501, "tool_metadata_unavailable", "No synthetic Tool metadata snapshot is loaded."
        )
    recorded = run.versions.get("tool_metadata_snapshot")
    if recorded != snapshot.version:
        raise EvidenceError(
            404,
            "source_version_unavailable",
            "The Tool metadata snapshot version this Run recorded is not available.",
            {"recorded_version": recorded, "available_version": snapshot.version},
        )
    row = next((r for r in snapshot.rows if r["metadata_id"] == reference.metadata_id), None)
    if row is None:
        raise EvidenceError(
            404, "tool_metadata_not_found", "Tool metadata row not found in this snapshot."
        )
    bounds = _Bounds()
    return bounds.result(
        reference=reference,
        role="synthetic_policy",
        source=SourceIdentity(
            type="tool_metadata_row", id=row["metadata_id"], batch_id=run.batch_id,
            run_id=run.run_id, version=snapshot.version,
        ),
        dates=_run_dates(run),
        applicability=Applicability(
            subject_type="tool_metadata",
            subject_id=row["metadata_id"],
            statement=(
                "Tool-wide facts and Policy Status of the synthetic demonstration scenario "
                "(governance_fact_basis); not organization policy, verified vendor facts or "
                "a compliance determination."
            ),
        ),
        versions=_versions(run, "tool_metadata_snapshot"),
        record={k: bounds.text(k, v) for k, v in row.items()},
    )


def _category_neighbor(
    connection: Connection, reference: CategoryNeighborReference, run: Run, _: EvidenceSources
) -> ResolvedEvidence:
    row = _candidate_row(connection, category_classifications, run, reference.candidate_number)
    neighbors = row["neighbors"]
    if reference.neighbor_number > len(neighbors):
        raise EvidenceError(
            404,
            "category_neighbor_not_found",
            "Semantic Neighbor not found for this Tool Candidate.",
            {"neighbor_count": len(neighbors)},
        )
    neighbor = neighbors[reference.neighbor_number - 1]
    return ResolvedEvidence(
        reference=reference,
        role="model_output",
        source=SourceIdentity(
            type="catalog_tool", id=neighbor["tool_id"], batch_id=run.batch_id,
            run_id=run.run_id, version=run.versions.get("category_classification"),
        ),
        dates=_run_dates(run),
        applicability=Applicability(
            subject_type="tool_candidate",
            subject_id=str(reference.candidate_number),
            statement=(
                "A Semantic Neighbor: supporting comparison evidence whose catalog Category "
                "voted in the Category Classification; not authority for identity or AI status."
            ),
        ),
        versions=_versions(run, "category_classification", "known_tool_registry"),
        record={
            "candidate_number": reference.candidate_number,
            "neighbor_number": reference.neighbor_number,
            "neighbor_count": len(neighbors),
            **neighbor,
            "classification": {
                "outcome": row["outcome"],
                "method": row["method"],
                "category": row["category"],
                "share": row["share"],
            },
        },
    )


_RESOLVERS: Mapping[type, Callable[..., ResolvedEvidence]] = {
    ActivityEventReference: _activity_event,
    UsageContextReference: _usage_context,
    AiEvidenceSentenceReference: _ai_evidence_sentence,
    WebsiteCaptureReference: _website_capture,
    ToolMetadataReference: _tool_metadata,
    CategoryNeighborReference: _category_neighbor,
}


def _run(connection: Connection, reference: RunReference) -> Run:
    run = get_run(connection, reference.run_id)
    if run is None or run.batch_id != reference.batch_id:
        raise EvidenceError(404, "run_not_found", "Analysis Run not found in this Batch.")
    return run


def _candidate_row(connection: Connection, table, run: Run, candidate_number: int) -> Mapping:
    return _one(
        connection,
        select(table).where(
            table.c.run_id == run.run_id, table.c.candidate_number == candidate_number
        ),
        "candidate_not_found",
        "Tool Candidate not found in this Analysis Run.",
    )


def _one(connection: Connection, query, code: str, message: str) -> Mapping:
    row = connection.execute(query).mappings().one_or_none()
    if row is None:
        raise EvidenceError(404, code, message)
    return row


def _run_dates(run: Run, **dates: str | None) -> dict[str, str | None]:
    return {**dates, "run_completed_at": run.completed_at}


def _versions(run: Run, *names: str) -> dict[str, str]:
    return {name: run.versions[name] for name in names if name in run.versions}


_NUMBER = re.compile(r"[1-9][0-9]{0,8}")


def _number(value: str) -> int:
    if not _NUMBER.fullmatch(value):
        raise _invalid("Record ID numbers must be positive integers")
    return int(value)


def _invalid(message: str) -> EvidenceError:
    return EvidenceError(422, "invalid_reference", message)
