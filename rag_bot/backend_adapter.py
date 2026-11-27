"""Opt-in compatibility boundary for the audited upstream assistant contracts."""

import asyncio
from dataclasses import asdict, dataclass
from math import isfinite
from types import ModuleType

from .service import RetrievalRequest, RetrievalService


AUDITED_REVISION = "d271c83de9b9bf222546612f9bb66fd108ce247c"
ARGUMENT_BYTES = 4096
RESULT_BYTES = 32768
# Upstream adds an ASCII step ID (37 bytes today) and a colon. Reserve 64
# bytes for the namespace itself so the adapter can fit results before invoke.
NAMESPACE_BYTES = 64
DOCUMENT_SCOPE = "Approved project documentation only. No Batch or Run findings are included."


@dataclass(frozen=True)
class BackendModules:
    """Inject the actual app.assistant.contracts, app.assistant.tools, and app.evidence modules."""

    contracts: ModuleType
    tools: ModuleType
    evidence: ModuleType


class BackendRetrievalAdapter:
    """Experimental ToolHandler and PassageResolver, disabled without explicit checks."""

    def __init__(self, service: RetrievalService, backend: BackendModules, *,
                 authorize_scope=None, authorize_passage=None,
                 max_argument_bytes: int = ARGUMENT_BYTES,
                 max_result_bytes: int = RESULT_BYTES, timeout_seconds: float = 60):
        if (type(max_argument_bytes) is not int or max_argument_bytes < 1
                or type(max_result_bytes) is not int or max_result_bytes < 1
                or not isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("Invalid retrieval adapter limits.")
        self.service = service
        self.backend = backend
        self.authorize_scope = authorize_scope
        self.authorize_passage = authorize_passage
        self.max_argument_bytes = max_argument_bytes
        self.max_result_bytes = max_result_bytes
        self.timeout_seconds = timeout_seconds
        self._capacity = service._dispatch_capacity
        if not self._fits(self._oversized()):
            raise ValueError("Result byte limit must fit a safe failure outcome.")

    async def __call__(self, scope, arguments):
        """Handle a validated tool call without blocking the event loop."""
        c = self.backend.contracts
        if self.authorize_scope is None:
            return self._bounded(c.ToolLimitation(reason="unavailable",
                                                  message="Document retrieval is disabled."))
        if not isinstance(scope, c.PinnedScope) or not isinstance(arguments, self.backend.tools.RetrieveContextArgs):
            return self._bounded(c.ToolFailure(code="invalid_tool_arguments",
                                               message="Invalid retrieval arguments."))
        try:
            self.backend.tools.bounded_json(arguments, self.max_argument_bytes)
        except (ValueError, TypeError):
            return self._bounded(c.ToolFailure(code="invalid_tool_arguments",
                                               message="Retrieval arguments exceed the byte limit."))
        try:
            if self.authorize_scope(scope) is not True:
                return self._bounded(c.ToolLimitation(reason="unsupported",
                                                      message="Scope is not approved for document retrieval."))
        except Exception:
            return self._failed()
        if not self._capacity.acquire(blocking=False):
            return self._bounded(c.ToolFailure(code="retrieval_busy",
                                               message="Document retrieval is busy. Retry shortly."))

        try:
            worker = asyncio.get_running_loop().run_in_executor(None, self._retrieve, arguments)
        except Exception:
            self._capacity.release()
            return self._failed()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await asyncio.shield(worker)
        except TimeoutError:
            return self._bounded(c.ToolFailure(code="retrieval_timeout",
                                               message="Document retrieval timed out."))
        except Exception:
            return self._failed()

    def _retrieve(self, arguments):
        try:
            result = self.service.retrieve(RetrievalRequest(arguments.query, arguments.limit))
            return self._map_result(result)
        except Exception:
            return self._failed()
        finally:
            # The worker owns capacity even when its caller has stopped awaiting it.
            self._capacity.release()

    def _map_result(self, result):
        c = self.backend.contracts
        if result.status == "unavailable":
            return self._bounded(c.ToolLimitation(reason="unavailable",
                                                  message="Document retrieval resources are unavailable."))
        if result.status == "unsupported_input":
            return self._bounded(c.ToolLimitation(reason="unsupported",
                                                  message="Query exceeds the embedding token limit."))
        if result.status == "invalid_input":
            return self._bounded(c.ToolFailure(code="invalid_tool_arguments",
                                               message="Invalid retrieval arguments."))
        if result.status == "no_matches":
            return self._bounded(c.ToolSuccess(outcome="no_matches", summary="No relevant passages.",
                                               data={"matches": []}, qualifications=(DOCUMENT_SCOPE,)))
        if result.status != "data" or not result.matches:
            return self._failed()

        evidence, rows = [], []
        for match in result.matches:
            hit = match.evidence
            if hit.source_role != "project_policy":
                return self._failed()
            evidence.append(c.PassageEvidence(
                evidence_id=hit.reference, corpus_version=hit.corpus_version,
                document_id=hit.document_id, document_version=hit.document_version,
                passage_id=hit.chunk_id, source_role=hit.source_role, excerpt=hit.excerpt,
            ))
            rows.append({"passage_id": hit.chunk_id, "section_passage_id": hit.section_passage_id,
                         "source_path": hit.source_path, "heading": hit.heading,
                         "ranking": asdict(match.ranking)})

        for count in range(len(evidence), 0, -1):
            omitted = len(evidence) - count
            qualifications = (DOCUMENT_SCOPE,)
            if omitted:
                qualifications += (f"Preview: {omitted} lower-ranked passage(s) omitted to fit the byte limit.",)
            outcome = c.ToolSuccess(outcome="data", summary=f"Returned {count} relevant passage(s).",
                                    data={"matches": rows[:count]}, evidence=tuple(evidence[:count]),
                                    qualifications=qualifications, truncated=bool(omitted))
            if self._fits(outcome):
                return outcome
        return self._oversized()

    def _fits(self, outcome):
        payload = outcome.model_dump(mode="json")
        for source in payload.get("evidence", ()):
            source["evidence_id"] = "x" * NAMESPACE_BYTES + ":" + source["evidence_id"]
        try:
            self.backend.tools.bounded_json(payload, self.max_result_bytes)
        except (TypeError, ValueError):
            return False
        return True

    def _oversized(self):
        return self.backend.contracts.ToolFailure(code="retrieval_result_too_large",
                                                  message="Retrieval result exceeds the byte limit.")

    def _bounded(self, outcome):
        return outcome if self._fits(outcome) else self._oversized()

    def _failed(self):
        return self._bounded(self.backend.contracts.ToolFailure(code="retrieval_failed",
                                                               message="Document retrieval failed."))

    def resolve_passage(self, connection, reference):
        """Demonstrate the synchronous PassageResolver using the same snapshot."""
        e = self.backend.evidence
        if not isinstance(reference, e.PassageReference):
            raise e.EvidenceError(422, "invalid_reference", "Invalid passage reference.")
        try:
            authorized = (self.authorize_passage is not None
                          and self.authorize_passage(connection, reference) is True)
        except Exception:
            raise e.EvidenceError(500, "passage_resolution_failed", "Passage resolution failed.") from None
        if not authorized:
            raise e.EvidenceError(501, "passage_corpus_unavailable", "Passage inspection is unavailable.")
        key = ":".join(("passage", reference.corpus_version, reference.document_id,
                        reference.document_version, reference.passage_id))
        try:
            result = self.service.resolve(key)
        except Exception:
            raise e.EvidenceError(500, "passage_resolution_failed", "Passage resolution failed.") from None
        failures = {
            "malformed_reference": (422, "invalid_reference", "Invalid passage reference."),
            "not_found": (404, "passage_not_found", "Passage not found."),
            "version_mismatch": (404, "source_version_unavailable", "Source version is unavailable."),
            "unavailable": (501, "passage_corpus_unavailable", "Passage inspection is unavailable."),
        }
        if result.status in failures:
            raise e.EvidenceError(*failures[result.status])
        hit = result.evidence
        if hit is None or hit.reference != key or hit.source_role != "project_policy":
            raise e.EvidenceError(500, "passage_resolution_failed", "Passage resolution failed.")
        return e.ResolvedEvidence(
            reference=reference,
            role="governance_guidance",
            source=e.SourceIdentity(type="project_document", id=hit.document_id,
                                    version=hit.document_version),
            dates={},
            applicability=e.Applicability(subject_type="passage", subject_id=hit.chunk_id,
                                          statement=DOCUMENT_SCOPE),
            versions={"corpus": hit.corpus_version, "document": hit.document_version},
            record={"excerpt": hit.excerpt, "heading": hit.heading, "source_path": hit.source_path,
                    "section_passage_id": hit.section_passage_id, "source_role": hit.source_role},
        )
