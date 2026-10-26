"""TypeSafe Jev: typed ADR 0001 questions answered with probabilities.

Question text is copied unchanged from ``notebooks/ai_cascade/jev_judge.py``; editing it, the model
or the cutoffs is a new AI Determination version that needs re-validation on freshly labeled pages.
"""

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import Engine, insert, select

from app.clock import utc_now
from app.db.tables import jev_responses

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"
RETRIES = 5
REQUEST_TIMEOUT_SECONDS = 120
_RETRY_STATUSES = (429, 500, 502, 503, 529)

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
EVIDENCE_INSTRUCTIONS = ("This sentence from the page shows the product's own AI (or learned model) performing a "
                         "specific task for its users: \"{}\"")

Judge = Callable[[Mapping[str, Any]], Mapping[str, Any]]
"""Answers one Jev request body with ``{"model", "answers", ...}``."""

Post = Callable[[bytes, Mapping[str, str]], tuple[int, bytes]]


class JudgeUnavailable(Exception):
    """Jev could not answer: no API key, a rejected request, or repeated transient failures."""


def request_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _urllib_post(data: bytes, headers: Mapping[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(ENDPOINT, data=data, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class JevClient:
    def __init__(
        self,
        api_key: str | None,
        post: Post = _urllib_post,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self._post = post
        self._sleep = sleep

    def __call__(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._api_key:
            raise JudgeUnavailable("TYPESAFE_API_KEY is not set")
        data = json.dumps(body, ensure_ascii=False).encode()
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        for attempt in range(RETRIES):
            try:
                status, content = self._post(data, headers)
            except OSError as error:
                status, content = None, type(error).__name__.encode()
            if status == 200:
                return json.loads(content)
            if status is not None and status not in _RETRY_STATUSES:
                break
            if attempt < RETRIES - 1:
                self._sleep(2**attempt)
        logger.warning("Jev request failed: %s %r", status, content[:300])
        raise JudgeUnavailable(f"Jev request failed with status {status}")


class CachedJudge:
    """Replays a stored answer for an identical request, so re-analysis does not ask Jev again."""

    def __init__(self, engine: Engine, judge: Judge):
        self._engine = engine
        self._judge = judge

    def __call__(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        key = request_hash(body)
        with self._engine.connect() as connection:
            stored = connection.execute(
                select(jev_responses.c.response).where(jev_responses.c.request_hash == key)
            ).scalar_one_or_none()
        if stored is not None:
            return stored
        response = self._judge(body)
        with self._engine.begin() as connection:
            connection.execute(
                insert(jev_responses)
                .values(
                    request_hash=key,
                    model=response["model"],
                    response=response,
                    created_at=utc_now(),
                )
                .prefix_with("OR IGNORE")
            )
        return response
