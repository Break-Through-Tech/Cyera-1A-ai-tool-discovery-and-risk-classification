"""Offline tests using small wire doubles, independently of the backend runtime."""

import asyncio
import json
from threading import Event, Lock, get_ident
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock

from rag_bot.backend_adapter import BackendModules, BackendRetrievalAdapter, NAMESPACE_BYTES
from rag_bot.evidence import EvidenceResolution, PassageEvidence
from rag_bot.service import Ranking, RetrievalRequest, RetrievalResult, RetrievedExcerpt


class Wire:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self, *, mode):
        def convert(value):
            if isinstance(value, Wire):
                return {k: convert(v) for k, v in vars(value).items()}
            if isinstance(value, dict):
                return {k: convert(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [convert(v) for v in value]
            return value

        return convert(self)


class EvidenceError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def bounded_json(value, maximum_bytes):
    if isinstance(value, Wire):
        value = value.model_dump(mode="json")
    data = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(data) > maximum_bytes:
        raise ValueError("Too large.")
    return data


def modules():
    contracts = SimpleNamespace(**{
        name: type(name, (Wire,), {}) for name in
        ("PinnedScope", "PassageEvidence", "ToolSuccess", "ToolLimitation", "ToolFailure")
    })
    tools = SimpleNamespace(RetrieveContextArgs=type("RetrieveContextArgs", (Wire,), {}),
                            bounded_json=bounded_json)
    evidence = SimpleNamespace(EvidenceError=EvidenceError, **{
        name: type(name, (Wire,), {}) for name in
        ("PassageReference", "ResolvedEvidence", "SourceIdentity", "Applicability")
    })
    return BackendModules(contracts, tools, evidence)


def hit(number=1, excerpt="Documentation excerpt."):
    return RetrievedExcerpt(PassageEvidence(
        "c" * 64, "doc-" + "d" * 64, "e" * 64, f"{number:020x}", "section-id",
        "project_policy", excerpt, "CONTEXT.md", "Definitions",
    ), Ranking(number, 0.8))


class AdapterTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = modules()
        self.scope = self.backend.contracts.PinnedScope()
        self.arguments = self.backend.tools.RetrieveContextArgs(query="Query", limit=2)
        self.service = Mock(_dispatch_capacity=Lock())
        self.service.retrieve.return_value = RetrievalResult("data", (hit(),))

    def adapter(self, **kwargs):
        options = {"authorize_scope": lambda scope: scope is self.scope,
                   "authorize_passage": lambda connection, reference: True} | kwargs
        return BackendRetrievalAdapter(self.service, self.backend, **options)

    async def test_maps_args_using_worker_and_preserves_evidence(self):
        event_loop_thread = get_ident()

        def retrieve(request):
            self.assertNotEqual(get_ident(), event_loop_thread)
            self.assertEqual(request, RetrievalRequest("Query", 2))
            return RetrievalResult("data", (hit(),))

        self.service.retrieve.side_effect = retrieve
        adapter = self.adapter()
        for _ in range(2):
            result = await adapter(self.scope, self.arguments)
            self.assertEqual(result.outcome, "data")
            item, = result.evidence
            self.assertEqual(item.evidence_id, hit().evidence.reference)
            self.assertEqual(item.passage_id, hit().evidence.chunk_id)
            self.assertEqual(item.excerpt, hit().evidence.excerpt)
            self.assertEqual(result.data["matches"][0]["section_passage_id"], "section-id")
        self.assertEqual(self.service.retrieve.call_count, 2)

    async def test_disabled_denied_invalid_and_multibyte_arguments(self):
        for adapter, scope, args, expected in (
            (BackendRetrievalAdapter(self.service, self.backend), self.scope, self.arguments, "unavailable"),
            (self.adapter(), self.backend.contracts.PinnedScope(), self.arguments, "unsupported"),
            (self.adapter(), self.scope, object(), "invalid_tool_arguments"),
            (self.adapter(), self.scope, self.backend.tools.RetrieveContextArgs(
                query="界" * 1400, limit=2), "invalid_tool_arguments"),
        ):
            result = await adapter(scope, args)
            self.assertEqual(getattr(result, "reason", getattr(result, "code", None)), expected)
        self.service.retrieve.assert_not_called()

    async def test_maps_distinct_service_outcomes_and_sanitizes_failures(self):
        adapter = self.adapter()
        for status, attribute, value in (
            ("no_matches", "outcome", "no_matches"),
            ("unavailable", "reason", "unavailable"),
            ("unsupported_input", "reason", "unsupported"),
            ("invalid_input", "code", "invalid_tool_arguments"),
            ("execution_failure", "code", "retrieval_failed"),
        ):
            self.service.retrieve.return_value = RetrievalResult(status, message="/private/path")
            result = await adapter(self.scope, self.arguments)
            self.assertEqual(getattr(result, attribute), value)
            self.assertNotIn("/private/path", str(vars(result)))
        self.service.retrieve.side_effect = OSError("/private/path")
        result = await adapter(self.scope, self.arguments)
        self.assertEqual(result.code, "retrieval_failed")

    async def test_prefix_overhead_unicode_and_explicit_truncation(self):
        first, second = hit(1, "界" * 150), hit(2, "🙂" * 180)
        self.service.retrieve.return_value = RetrievalResult("data", (first, second))
        full = await self.adapter()(self.scope, self.arguments)
        raw_bytes = len(bounded_json(full, 32768))
        result = await self.adapter(max_result_bytes=raw_bytes)(self.scope, self.arguments)
        self.assertTrue(result.truncated)
        self.assertIn("omitted", result.qualifications[-1])
        self.assertEqual([row.excerpt for row in result.evidence], [first.evidence.excerpt])
        payload = full.model_dump(mode="json")
        for row in payload["evidence"]:
            row["evidence_id"] = "x" * NAMESPACE_BYTES + ":" + row["evidence_id"]
        exact_limit = len(bounded_json(payload, 32768))
        result = await self.adapter(max_result_bytes=exact_limit)(self.scope, self.arguments)
        self.assertFalse(result.truncated)
        result = await self.adapter(max_result_bytes=exact_limit - 1)(self.scope, self.arguments)
        self.assertTrue(result.truncated)

    async def test_oversized_individual_excerpt_is_a_failure(self):
        self.service.retrieve.return_value = RetrievalResult("data", (hit(1, "界" * 1000),))
        result = await self.adapter(max_result_bytes=500)(self.scope, self.arguments)
        self.assertEqual(result.code, "retrieval_result_too_large")

    async def wait_started(self, event):
        async with asyncio.timeout(2):
            while not event.is_set():
                await asyncio.sleep(0.001)

    async def test_cancellation_and_timeout_leave_capacity_with_running_worker(self):
        for cancel in (True, False):
            started, release = Event(), Event()

            def retrieve(request):
                started.set()
                release.wait(2)
                return RetrievalResult("no_matches")

            self.service.retrieve.side_effect = retrieve
            adapter = self.adapter(timeout_seconds=1 if cancel else 0.1)
            task = asyncio.create_task(adapter(self.scope, self.arguments))
            try:
                await self.wait_started(started)
                self.assertEqual((await self.adapter()(self.scope, self.arguments)).code, "retrieval_busy")
                if cancel:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                else:
                    self.assertEqual((await task).code, "retrieval_timeout")
                self.assertEqual((await adapter(self.scope, self.arguments)).code, "retrieval_busy")
            finally:
                release.set()
            async with asyncio.timeout(2):
                while adapter._capacity.locked():
                    await asyncio.sleep(0.001)
            self.assertEqual((await adapter(self.scope, self.arguments)).outcome, "no_matches")

    def test_resolver_preserves_identity_and_requires_authorization(self):
        source = hit().evidence
        reference = self.backend.evidence.PassageReference(
            corpus_version=source.corpus_version, document_id=source.document_id,
            document_version=source.document_version, passage_id=source.chunk_id,
        )
        self.service.resolve.return_value = EvidenceResolution("resolved", source)
        with self.assertRaises(EvidenceError) as blocked:
            self.adapter(authorize_passage=None).resolve_passage(None, reference)
        self.assertEqual(blocked.exception.status_code, 501)
        self.service.resolve.assert_not_called()
        resolved = self.adapter().resolve_passage(None, reference)
        self.assertEqual(resolved.reference, reference)
        self.assertEqual(resolved.record["excerpt"], source.excerpt)
        self.assertEqual(resolved.role, "governance_guidance")
        self.service.resolve.assert_called_once_with(source.reference)
        self.service.resolve.return_value = EvidenceResolution("version_mismatch")
        with self.assertRaises(EvidenceError) as mismatch:
            self.adapter().resolve_passage(None, reference)
        self.assertEqual(mismatch.exception.code, "source_version_unavailable")
