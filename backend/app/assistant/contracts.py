"""Provider-independent contracts; these models do not authorize access or verify claims.

The backend resolves scope and evidence. Model-generated values must never be
accepted as proof that a Run succeeded, a source exists, or a tool executed.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
References = Annotated[tuple[Text, ...], Field(min_length=1)]
ToolName = Literal[
    "describe_dataset",
    "summarize_usage",
    "compare_usage",
    "get_risk_assessments",
    "get_evidence",
    "retrieve_context",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunReference(Contract):
    batch_id: Text
    run_id: Text


class EventTimeRange(Contract):
    """UTC interval: inclusive start, exclusive end, resolved before tools run."""

    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("Event-time boundaries must use UTC")
        return value

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Event-time start must precede exclusive end")
        return self


class ScopeFilters(Contract):
    """Empty tuples mean no restriction; unsupported filters must not be ignored."""

    departments: tuple[Text, ...] = ()
    categories: tuple[Text, ...] = ()
    ai_statuses: tuple[Literal["ai", "non_ai", "unresolved"], ...] = ()
    risk_tiers: tuple[Literal["High", "Medium", "Lower", "unresolved"], ...] = ()
    flagged: bool | None = None


class PinnedScope(Contract):
    """Backend-selected Runs, not a moving 'latest' pointer or an access grant."""

    runs: Annotated[tuple[RunReference, ...], Field(min_length=1)]
    event_time: EventTimeRange
    filters: ScopeFilters = Field(default_factory=ScopeFilters)
    qualifications: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def one_run_per_batch(self) -> Self:
        if len({run.batch_id for run in self.runs}) != len(self.runs):
            raise ValueError("Scope must pin exactly one Run per contributing Batch")
        if len({run.run_id for run in self.runs}) != len(self.runs):
            raise ValueError("Scope cannot repeat a Run across Batches")
        return self


class RecordEvidence(Contract):
    kind: Literal["record"] = "record"
    evidence_id: Text
    run: RunReference
    record_type: Literal["activity_event", "usage_context", "analysis_run"]
    record_id: Text


class AggregateEvidence(Contract):
    kind: Literal["aggregate"] = "aggregate"
    evidence_id: Text
    scope: PinnedScope
    operation: Text
    # Backend-owned reproducible query specification, not executable SQL.
    query: dict[str, JsonValue]
    metric_definitions: References
    drilldown_reference: Text


class PassageEvidence(Contract):
    kind: Literal["passage"] = "passage"
    evidence_id: Text
    corpus_version: Text
    document_id: Text
    document_version: Text
    passage_id: Text
    source_role: Literal["project_policy", "general_guidance", "tool_evidence"]
    excerpt: Text


Evidence = Annotated[
    RecordEvidence | AggregateEvidence | PassageEvidence, Field(discriminator="kind")
]


class ToolSuccess(Contract):
    status: Literal["succeeded"] = "succeeded"
    outcome: Literal["data", "no_matches"]
    summary: Text
    data: dict[str, JsonValue]
    evidence: tuple[Evidence, ...] = ()
    qualifications: tuple[Text, ...] = ()
    truncated: bool = False
    continuation: Text | None = None

    @model_validator(mode="after")
    def disclose_truncation(self) -> Self:
        if self.truncated and not self.qualifications:
            raise ValueError("Truncated results must disclose their limitations")
        if self.continuation is not None and not self.truncated:
            raise ValueError("Continuation requires a truncated result")
        return self


class ToolLimitation(Contract):
    status: Literal["limited"] = "limited"
    reason: Literal["unavailable", "unsupported", "clarification_required"]
    message: Text


class ToolFailure(Contract):
    """Safe diagnostics only; raw exceptions and credentials do not belong here."""

    status: Literal["failed"] = "failed"
    code: Text
    message: Text


ToolOutcome = Annotated[
    ToolSuccess | ToolLimitation | ToolFailure, Field(discriminator="status")
]


class ExecutionStep(Contract):
    """Backend receipt of a completed attempt, never an LLM-authored narrative.

    Arguments must be operation-validated and safe for analyst disclosure before
    recording. Typed operation arguments will be defined with the integrations.
    """

    step_id: Text
    sequence: Annotated[int, Field(strict=True, ge=1)]
    tool: ToolName
    scope: PinnedScope
    arguments: dict[str, JsonValue]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: ToolOutcome

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("Completion cannot precede execution start")
        return self


class FactualClaim(Contract):
    text: Text
    evidence_ids: References


class Finding(Contract):
    facts: Annotated[tuple[FactualClaim, ...], Field(min_length=1)]
    interpretation: Text
    limitations: tuple[Text, ...] = ()
    advisory_next_steps: tuple[Text, ...] = ()


class GroundedAnswer(Contract):
    """A candidate answer, not a certification that its claims are supported."""

    scope: PinnedScope
    findings: Annotated[tuple[Finding, ...], Field(min_length=1)]
    limitations: tuple[Text, ...] = ()
    stop_reason: Literal["sufficient_evidence", "budget_reached"]
    unfinished_work: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def disclose_budget_stop(self) -> Self:
        if self.stop_reason == "budget_reached" and not self.unfinished_work:
            raise ValueError("Budget stops must disclose unfinished investigation")
        return self


def validate_answer_references(
    answer: GroundedAnswer, evidence: tuple[Evidence, ...]
) -> None:
    """Check supplied references and Run membership, not existence or claim support.

    The service must supply backend-resolved evidence and separately enforce
    access, source resolution, query scope, and claim-support evaluation.
    """
    by_id = {item.evidence_id: item for item in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("Evidence IDs must be unique")
    for finding in answer.findings:
        for claim in finding.facts:
            for evidence_id in claim.evidence_ids:
                if evidence_id not in by_id:
                    raise ValueError(f"Unknown evidence reference: {evidence_id}")
                item = by_id[evidence_id]
                if isinstance(item, RecordEvidence) and item.run not in answer.scope.runs:
                    raise ValueError("Record evidence is outside the pinned Runs")
                if isinstance(item, AggregateEvidence) and item.scope != answer.scope:
                    raise ValueError("Aggregate evidence must match the answer scope")
