"""Typed adapters to teammate-owned operations. No queries or retrieval live here."""

import json
from collections.abc import Mapping
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, TypeAdapter

from app.assistant.contracts import (
    AggregateEvidence,
    Contract,
    EventTimeRange,
    PinnedScope,
    RecordEvidence,
    Text,
    ToolLimitation,
    ToolName,
    ToolOutcome,
    ToolSuccess,
)
from app.assistant.integrations import ToolCall, ToolDescription

Metric = Literal["event_count", "distinct_employees", "tools", "usage_contexts"]


class DescribeDatasetArgs(Contract):
    pass


class SummarizeUsageArgs(Contract):
    metric: Metric = "event_count"
    group_by: Annotated[
        tuple[Literal["department", "category", "ai_status", "risk_tier"], ...],
        Field(max_length=4),
    ] = ()
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    continuation: Text | None = None


class CompareUsageArgs(Contract):
    baseline: EventTimeRange
    current: EventTimeRange
    metric: Metric = "event_count"


class GetRiskAssessmentsArgs(Contract):
    focus: Literal["all", "flagged", "unapproved", "unresolved", "missing_facts"] = (
        "all"
    )
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    continuation: Text | None = None


class GetEvidenceArgs(Contract):
    references: Annotated[tuple[Text, ...], Field(min_length=1, max_length=20)]


class RetrieveContextArgs(Contract):
    query: Annotated[Text, Field(max_length=2000)]
    limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5


ToolArguments = (
    DescribeDatasetArgs
    | SummarizeUsageArgs
    | CompareUsageArgs
    | GetRiskAssessmentsArgs
    | GetEvidenceArgs
    | RetrieveContextArgs
)
_ARGUMENT_TYPES: dict[ToolName, type[ToolArguments]] = {
    "describe_dataset": DescribeDatasetArgs,
    "summarize_usage": SummarizeUsageArgs,
    "compare_usage": CompareUsageArgs,
    "get_risk_assessments": GetRiskAssessmentsArgs,
    "get_evidence": GetEvidenceArgs,
    "retrieve_context": RetrieveContextArgs,
}
_DESCRIPTIONS: dict[ToolName, str] = {
    "describe_dataset": "Describe scope coverage, available dimensions, and missing facts.",
    "summarize_usage": "Return deterministic counts or grouped usage summaries.",
    "compare_usage": "Compare two explicit UTC periods within the pinned scope.",
    "get_risk_assessments": "Read stored risk tiers, reasons, flags, and unknown facts.",
    "get_evidence": "Inspect supporting references within the pinned scope.",
    "retrieve_context": "Retrieve retained context with versioned passage references.",
}


class ToolHandler(Protocol):
    async def __call__(
        self, scope: PinnedScope, arguments: ToolArguments
    ) -> ToolOutcome: ...


class InvalidToolResult(ValueError):
    pass


def bounded_json(value: object, maximum_bytes: int) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    data = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(data) > maximum_bytes:
        raise ValueError("Payload exceeds the configured byte limit")
    return data


class ToolRegistry:
    def __init__(self, handlers: Mapping[ToolName, ToolHandler]):
        name_adapter = TypeAdapter(ToolName)
        self._handlers = {
            name_adapter.validate_python(name): handler
            for name, handler in handlers.items()
        }

    def descriptions(self) -> tuple[ToolDescription, ...]:
        return tuple(
            ToolDescription(
                name=name,
                description=_DESCRIPTIONS[name],
                arguments_schema=_ARGUMENT_TYPES[name].model_json_schema(),
            )
            for name in _ARGUMENT_TYPES
            if name in self._handlers
        )

    def prepare(
        self, call: ToolCall, scope: PinnedScope, maximum_bytes: int
    ) -> ToolArguments:
        bounded_json(call.arguments, maximum_bytes)
        arguments = _ARGUMENT_TYPES[call.tool].model_validate(call.arguments)
        if isinstance(arguments, CompareUsageArgs):
            for period in (arguments.baseline, arguments.current):
                if (
                    period.start < scope.event_time.start
                    or period.end > scope.event_time.end
                ):
                    raise ValueError(
                        "Comparison periods cannot expand the pinned scope"
                    )
        return arguments

    async def invoke(
        self,
        name: ToolName,
        scope: PinnedScope,
        arguments: ToolArguments,
        *,
        reference_namespace: str,
        maximum_bytes: int,
    ) -> ToolOutcome:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolLimitation(
                reason="unavailable", message=f"{name} is not connected."
            )
        raw = await handler(scope, arguments)
        try:
            result = TypeAdapter(ToolOutcome).validate_json(
                bounded_json(raw, maximum_bytes)
            )
            if isinstance(result, ToolSuccess):
                ids = [source.evidence_id for source in result.evidence]
                if len(set(ids)) != len(ids):
                    raise ValueError("Duplicate evidence IDs within a tool result")
                for source in result.evidence:
                    if (
                        isinstance(source, RecordEvidence)
                        and source.run not in scope.runs
                    ):
                        raise ValueError("Evidence references an out-of-scope Run")
                    if isinstance(source, AggregateEvidence) and source.scope != scope:
                        raise ValueError(
                            "Aggregate scope differs from the requested scope"
                        )
                result = result.model_copy(
                    update={
                        "evidence": tuple(
                            source.model_copy(
                                update={
                                    "evidence_id": f"{reference_namespace}:{source.evidence_id}"
                                }
                            )
                            for source in result.evidence
                        )
                    }
                )
            bounded_json(result, maximum_bytes)
            return result
        except (ValueError, TypeError) as error:
            raise InvalidToolResult(
                "Tool returned invalid or oversized evidence/results"
            ) from error
