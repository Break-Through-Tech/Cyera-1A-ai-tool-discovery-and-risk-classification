"""Verify the adapter with source blobs from the audited upstream commit.

This checks the actual model declarations and ToolRegistry without running
FastAPI, the database, or LangGraph. Source is read from an existing audited
checkout, or from a JSON path-to-source mapping on stdin.
"""

import argparse
import ast
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace

from .backend_adapter import ARGUMENT_BYTES, AUDITED_REVISION, RESULT_BYTES, BackendModules, BackendRetrievalAdapter
from .evidence import EvidenceResolution, PassageEvidence
from .service import Ranking, RetrievalResult, RetrievedExcerpt


BLOBS = {
    "backend/app/assistant/contracts.py": "20e5b1aa4b1893a8b4fb63f1a386afca6edee821",
    "backend/app/assistant/integrations.py": "07717dbd667bb27ed060da2f70fb268ef2e9bd75",
    "backend/app/assistant/tools.py": "876f3caa1891b688f461d4ebe40500c4459642c2",
    "backend/app/evidence.py": "cf9cb272d82af55a6a5ff2cba16d1a3d90ab5210",
    "backend/app/errors.py": "c90d72f2955780f71675410e73c7799f31e34157",
    "backend/app/assistant/graph.py": "3fdb1eb6a8bb7ca238e1a1c2809749fbe8692b60",
}


ADAPTER_BLOB = {"backend/app/assistant/adapters.py": "143388d57f5363c6881043d0d7f282f79b6211f3"}


def verified_modules(sources, *, passage_path=False):
    required = BLOBS | ADAPTER_BLOB if passage_path else BLOBS
    for path, digest in required.items():
        raw = sources[path].encode("utf-8")
        if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != digest:
            raise ValueError(f"Source does not match the audited revision: {path}")

    def initialize(path, *, names=None, imports=(), context=None, methods=None):
        name = path.removeprefix("backend/").removesuffix(".py").replace("/", ".")
        module = ModuleType(name)
        if context:
            vars(module).update(context)
        sys.modules[name] = module
        tree = ast.parse(sources[path], filename=path)
        if names is not None:
            tree.body = [
                node for node in tree.body if getattr(node, "name", None) in names
                or (isinstance(node, ast.ImportFrom) and node.module in imports)
                or (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in names)
            ]
        if methods:
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name in methods:
                    node.body = [child for child in node.body if getattr(child, "name", None) in methods[node.name]]
        exec(compile(tree, path, "exec"), vars(module))
        return module

    contracts = initialize("backend/app/assistant/contracts.py")
    integrations = initialize("backend/app/assistant/integrations.py")
    tools = initialize("backend/app/assistant/tools.py")
    errors = initialize("backend/app/errors.py", names={"AppError"}, imports=("typing",))
    resolver_names = {"PassageResolver", "EvidenceSources", "resolve_evidence"} if passage_path else set()
    evidence = initialize("backend/app/evidence.py", imports=("typing", "pydantic", "dataclasses", "collections.abc"), names={
        "Role", "Number", "Name", "ActivityEventReference", "UsageContextReference",
        "AnalysisRunReference", "AiEvidenceSentenceReference", "WebsiteCaptureReference",
        "ToolMetadataReference", "CategoryNeighborReference", "PassageReference",
        "AggregateReference", "RecordReference", "EvidenceReference", "SourceIdentity",
        "Applicability", "Truncation", "ResolvedEvidence", "EvidenceError",
    } | resolver_names, context={"AppError": errors.AppError, "Connection": object,
                                 "ToolMetadataSnapshot": type("ToolMetadataSnapshot", (), {}),
                                 **{key: getattr(contracts, key)
                                               for key in ("Contract", "RunReference", "Text")}})
    graph = initialize("backend/app/assistant/graph.py", names={"ExecutionLimits"},
                       imports=("typing", "pydantic"), context={"Contract": contracts.Contract})
    backend = BackendModules(contracts, tools, evidence)
    limits = graph.ExecutionLimits()
    if not passage_path:
        return backend, integrations, limits
    adapters = initialize(
        "backend/app/assistant/adapters.py",
        names={"QueryTools", "_parse_reference", "_reference_key", "_Stop", "_unsupported",
               "_RECORD_TYPES", "_NAMESPACE_BYTES"},
        imports=("collections.abc", "pydantic"),
        methods={"QueryTools": {"__init__", "get_evidence", "_fit", "_fits"}},
        context={
            **{key: getattr(contracts, key) for key in (
                "ToolOutcome", "ToolSuccess", "ToolLimitation", "ToolFailure", "PinnedScope",
            )},
            **{key: getattr(evidence, key) for key in (
                "PassageReference", "RecordReference", "EvidenceError", "resolve_evidence",
                "EvidenceSources",
            )},
            "Engine": object, "Connection": object, "_Read": SimpleNamespace,
            "GetEvidenceArgs": tools.GetEvidenceArgs, "json": json,
        },
    )
    return backend, integrations, limits, adapters


async def verify(sources):
    backend, integrations, limits = verified_modules(sources)
    c, t, e = backend.contracts, backend.tools, backend.evidence
    assert (limits.max_argument_bytes, limits.max_tool_result_bytes) == (ARGUMENT_BYTES, RESULT_BYTES)
    now = datetime.now(UTC)
    scope = c.PinnedScope(runs=(c.RunReference(batch_id="fixture-batch", run_id="fixture-run"),),
                          event_time=c.EventTimeRange(start=now, end=now + timedelta(seconds=1)))
    first = PassageEvidence("a" * 64, "doc-" + "b" * 64, "c" * 64, "d" * 20,
                            "fixture-section", "project_policy", "界🙂" * 30,
                            "CONTEXT.md", "Definitions")
    second = PassageEvidence("a" * 64, "doc-" + "b" * 64, "c" * 64, "e" * 20,
                             "fixture-section", "project_policy", "界🙂" * 300,
                             "CONTEXT.md", "Definitions")
    calls = []

    def retrieve(request):
        calls.append(request)
        return RetrievalResult("data", (RetrievedExcerpt(first, Ranking(1, 0.8)),
                                        RetrievedExcerpt(second, Ranking(2, 0.7))))

    def resolve(key):
        return (EvidenceResolution("resolved", first) if key == first.reference
                else EvidenceResolution("version_mismatch"))

    adapter = BackendRetrievalAdapter(
        SimpleNamespace(retrieve=retrieve, resolve=resolve, _dispatch_capacity=Lock()), backend,
        authorize_scope=lambda supplied: supplied == scope, authorize_passage=lambda *_: True,
        max_result_bytes=1500,
    )
    registry = t.ToolRegistry({"retrieve_context": adapter})
    arguments = registry.prepare(integrations.ToolCall(
        tool="retrieve_context", arguments={"query": "  definition  ", "limit": 2}
    ), scope, limits.max_argument_bytes)
    namespace = "step_" + "a" * 32
    result = await registry.invoke("retrieve_context", scope, arguments,
                                   reference_namespace=namespace, maximum_bytes=1500)
    assert isinstance(result, c.ToolSuccess) and result.truncated and result.qualifications
    assert len(calls) == 1 and (calls[0].query, calls[0].limit) == ("definition", 2)
    item, = result.evidence
    assert isinstance(item, c.PassageEvidence) and item.evidence_id == f"{namespace}:{first.reference}"
    assert item.excerpt == first.excerpt and item.passage_id == first.chunk_id

    reference = e.PassageReference(corpus_version=item.corpus_version, document_id=item.document_id,
                                   document_version=item.document_version, passage_id=item.passage_id)
    resolved = adapter.resolve_passage(None, reference)
    assert isinstance(resolved, e.ResolvedEvidence) and resolved.record["excerpt"] == first.excerpt
    try:
        adapter.resolve_passage(None, reference.model_copy(update={"document_version": "f" * 64}))
    except e.EvidenceError as error:
        assert error.code == "source_version_unavailable" and error.status_code == 404
    else:
        raise AssertionError("Stale evidence unexpectedly resolved.")
    print(f"Verified audited contract models, ToolRegistry, limits, and resolver mapping at {AUDITED_REVISION}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, help="Root containing the exact audited source blobs")
    args = parser.parse_args()
    sources = ({path: (args.checkout / path).read_bytes().decode("utf-8") for path in BLOBS}
               if args.checkout is not None else json.load(sys.stdin))
    asyncio.run(verify(sources))


if __name__ == "__main__":
    main()
