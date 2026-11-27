"""Configured Gemini Developer API adapter with bounded requests."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx2
from dotenv import dotenv_values
from google import genai
from google.genai import errors, types

from .profiles import DOCS_ONLY
from .prompts import SYSTEM_INSTRUCTIONS, GroundedPrompt


ENV_FILE = Path(__file__).resolve().parents[1] / ".env.rag"
AnswerStatus = Literal["sufficient", "partial", "insufficient"]
STATUSES = ("sufficient", "partial", "insufficient")
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUSES)},
        "citation_labels": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "status", "citation_labels", "limitations"],
    "additionalProperties": False,
}


class GenerationError(RuntimeError):
    """A safe diagnostic for a failed generation or citation check."""


@dataclass(frozen=True)
class GeminiSettings:
    model: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    status: AnswerStatus
    citation_labels: tuple[str, ...]
    limitations: tuple[str, ...]


def load_settings(path: Path = ENV_FILE) -> GeminiSettings:
    """Read only the dedicated configuration, giving process settings priority."""
    try:
        values = dotenv_values(path, interpolate=False)
    except (OSError, UnicodeError):
        raise GenerationError("Could not read Gemini settings from .env.rag.") from None
    key = (os.environ.get("GEMINI_API_KEY", values.get("GEMINI_API_KEY")) or "").strip()
    model = (os.environ.get("GEMINI_MODEL", values.get("GEMINI_MODEL")) or "").strip()
    if not key:
        raise GenerationError("Set GEMINI_API_KEY in the environment or .env.rag.")
    if not re.fullmatch(r"(?:models/)?gemini-[a-z0-9]+(?:[.-][a-z0-9]+)*", model):
        raise GenerationError("Set GEMINI_MODEL to a valid Gemini model ID, such as gemini-3.5-flash-lite.")
    return GeminiSettings(model, key)


def parse_response(text: str | None) -> GeneratedAnswer:
    """Require the expected JSON fields and types before using any output."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise GenerationError("Gemini returned malformed or empty structured output.") from None
    if (
        not isinstance(data, dict)
        or data.keys() != RESPONSE_SCHEMA["properties"].keys()
        or not isinstance(data["answer"], str)
        or data["status"] not in STATUSES
        or any(
            not isinstance(data[name], list)
            or any(not isinstance(item, str) or not item.strip() for item in data[name])
            for name in ("citation_labels", "limitations")
        )
    ):
        raise GenerationError("Gemini returned an invalid answer structure.")
    return GeneratedAnswer(
        data["answer"].strip(), data["status"], tuple(data["citation_labels"]),
        tuple(item.strip() for item in data["limitations"]),
    )


class GeminiGenerator:
    """Reuse one SDK client. A supplied client is owned by the caller."""

    def __init__(self, settings: GeminiSettings, client=None):
        self.model = settings.model
        self._owns_client = client is None
        try:
            self.client = client if client is not None else genai.Client(
                api_key=settings.api_key,
                vertexai=False,
                http_options=types.HttpOptions(
                    base_url="https://generativelanguage.googleapis.com",
                    api_version="v1beta",
                    timeout=30_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        except (ValueError, OSError, RuntimeError):
            raise GenerationError("Could not initialize the Gemini SDK client.") from None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def generate(self, prompt: GroundedPrompt) -> GeneratedAnswer:
        if prompt.corpus_profile != DOCS_ONLY or any(
            item.chunk.passage.catalog is not None
            or item.chunk.passage.source_role == "tool_evidence"
            for item in prompt.evidence
        ):
            raise GenerationError("Catalog-enabled generation is local only. Gemini was not called.")
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt.user_message,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTIONS,
                    response_mime_type="application/json",
                    response_json_schema=RESPONSE_SCHEMA,
                    max_output_tokens=2048,
                ),
            )
        except errors.APIError as error:
            if error.code == 402:
                message = "Gemini billing blocked the request (HTTP 402). Prepaid credits may be depleted."
            elif error.code == 429:
                message = "Gemini rate limit or quota reached. Try again later."
            elif error.code in (401, 403):
                message = "Gemini rejected authentication or access. Check API key permissions."
            elif error.code in (400, 404):
                message = "Gemini rejected the model or request. Check GEMINI_MODEL and structured-output support."
            else:
                message = "Gemini service request failed. Try again later."
            raise GenerationError(message) from None
        except (httpx2.RequestError, TimeoutError, OSError):
            raise GenerationError("Gemini connection failed or timed out.") from None
        if not response.candidates or any(
            candidate.finish_reason != types.FinishReason.STOP for candidate in response.candidates
        ):
            raise GenerationError("Gemini did not return a complete answer.")
        if len(response.candidates) != 1:
            raise GenerationError("Gemini returned an unexpected number of answers.")
        return parse_response(response.text)
