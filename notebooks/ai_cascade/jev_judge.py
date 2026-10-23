"""Jev (TypeSafe System One) judge: typed ADR 0001 questions answered with probabilities instead of a generated verdict.

The key is read from TYPESAFE_API_KEY, falling back to the repository's gitignored .env file.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cascade_v2 as base

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE.parents[1] / ".env"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
CACHE = HERE / "jev_cache.json"
FULL_TEXT_CHARS = 12000
WORKERS = 8
RETRIES = 5

DETERMINATION_CRITERIA = {
    "ai": "The page shows the product's own AI performing work for its users: AI is the core offering, or a concrete "
          "AI feature is included (for example AI writes summaries, generates images, answers questions, transcribes, "
          "converts plain-English requests or screenshots into code). The word 'AI' is not required.",
    "non_ai": "AI appears only as something other than the product's own functionality: the product's subject or "
              "customers (securing, tracking, or hosting other people's AI), content such as blog, news, or course "
              "topics, integrations naming AI vendors, or an explicit denial. Or the product is conventional software "
              "with no AI claim.",
    "unresolved": "The only product AI evidence is a vague claim with no described task ('AI-powered platform', "
                  "'smarter with AI'), or the page does not describe a product (parked domain, login wall, error page).",
}
QUESTIONS = {
    "determination": {"type": "choice", "criteria": DETERMINATION_CRITERIA,
                      "instructions": "Using only this homepage text, does the product itself use AI to do work for its "
                                      "users? Do not use outside knowledge of the company."},
    "own_ai_task": {"type": "noul", "instructions": "The page shows this product's own AI (or learned model) performing a "
                                                    "specific task for its users."},
    "ai_only_subject": {"type": "noul", "instructions": "AI appears on this page only as something other than the "
                                                        "product's own functionality: its subject or customers, content "
                                                        "topics, integrations with AI vendors, or a denial."},
    "vague_ai_claim": {"type": "noul", "instructions": "The page claims the product uses AI only in vague marketing terms, "
                                                       "without describing any task the AI performs."},
    "describes_product": {"type": "noul", "instructions": "The page describes what a product or service does; it is not a "
                                                          "parked or for-sale domain, login or cookie wall, error page, or "
                                                          "bare navigation."},
}


def api_key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise KeyError("TYPESAFE_API_KEY is not set")


def state_for(capture, mode):
    f = base.fields(capture)
    if mode == "snippets":
        return {"title": f["title"], "meta_description": f["meta_description"],
                "snippets": [s["text"] for s in base.mention_snippets(capture)]}
    return {"title": f["title"], "meta_description": f["meta_description"], "headings": f["headings"],
            "page_text": f["body"][:FULL_TEXT_CHARS]}


def request_body(capture, mode):
    return {"model": MODEL, "state": state_for(capture, mode), "questions": QUESTIONS}


def request_id(body):
    return "j_" + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _call(body):
    data = json.dumps(body, ensure_ascii=False).encode()
    for attempt in range(RETRIES):
        req = urllib.request.Request(ENDPOINT, data=data, headers={"Authorization": f"Bearer {api_key()}",
                                                                   "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 529) or attempt == RETRIES - 1:
                raise RuntimeError(f"Jev HTTP {e.code}: {e.read()[:300]!r}") from None
            time.sleep(2 ** attempt)


def ask(captures, mode="snippets"):
    """Return {sample_id: answers dict} for each capture, calling Jev only for request bodies not already cached."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    bodies = {c["sample_id"]: request_body(c, mode) for c in captures}
    todo = {request_id(b): b for b in bodies.values() if request_id(b) not in cache}
    with ThreadPoolExecutor(WORKERS) as pool:
        for rid, result in zip(todo, pool.map(_call, todo.values())):
            cache[rid] = {"model": result["model"], "answers": result["answers"], "usage": result["usage"]}
    if todo:
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {s: cache[request_id(b)] for s, b in bodies.items()}


EVIDENCE_SENTENCES = 60
EVIDENCE_MIN_CHARS = 20
EVIDENCE_INSTRUCTIONS = ("This sentence from the page shows the product's own AI (or learned model) performing a "
                         "specific task for its users: \"{}\"")


def evidence_sentences(capture):
    """Title, meta description, then gate-matching sentences, then other sentences, up to EVIDENCE_SENTENCES."""
    f = base.fields(capture)
    body = [s[:base.SNIPPET_CHARS] for loc in ("headings", "body") for s in base.sentences(f[loc])
            if len(s) >= EVIDENCE_MIN_CHARS]
    ordered = [f["title"], f["meta_description"]] + [s for s in body if base.gate(s)] + [s for s in body if not base.gate(s)]
    out = []
    for s in ordered:
        if s and s not in out:
            out.append(s)
    return out[:EVIDENCE_SENTENCES]


def ask_evidence(captures):
    """Return {sample_id: [(probability, sentence), ...]} sorted strongest first, in a request separate from the decision."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    bodies, sentences_for = {}, {}
    for c in captures:
        sents = evidence_sentences(c)
        sentences_for[c["sample_id"]] = sents
        bodies[c["sample_id"]] = {"model": MODEL, "state": state_for(c, "full"),
                                  "questions": {f"e{i}": {"type": "noul", "instructions": EVIDENCE_INSTRUCTIONS.format(s)}
                                                for i, s in enumerate(sents)}} if sents else None
    todo = {request_id(b): b for b in bodies.values() if b and request_id(b) not in cache}
    with ThreadPoolExecutor(WORKERS) as pool:
        for rid, result in zip(todo, pool.map(_call, todo.values())):
            cache[rid] = {"model": result["model"], "answers": result["answers"], "usage": result["usage"]}
    if todo:
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out = {}
    for s, b in bodies.items():
        answers = cache[request_id(b)]["answers"] if b else {}
        out[s] = sorted(((answers[f"e{i}"]["noul"], sent) for i, sent in enumerate(sentences_for[s])), reverse=True)
    return out


def features(result):
    a = result["answers"]
    p = a["determination"]["probabilities"]
    return {"p_ai": p["ai"], "p_non_ai": p["non_ai"], "p_unresolved": p["unresolved"],
            "own_ai_task": a["own_ai_task"]["noul"], "ai_only_subject": a["ai_only_subject"]["noul"],
            "vague_ai_claim": a["vague_ai_claim"]["noul"], "describes_product": a["describes_product"]["noul"]}
