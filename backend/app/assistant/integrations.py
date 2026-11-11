"""Provider-independent model decisions and safe execution metadata."""

from typing import Annotated, Literal, Protocol

from pydantic import Field, JsonValue

from app.assistant.contracts import (
    Contract,
    ExecutionStep,
    Finding,
    PinnedScope,
    Text,
    ToolName,
)


class ToolCall(Contract):
    kind: Literal["tool_call"] = "tool_call"
    tool: ToolName
    arguments: dict[str, JsonValue]


class AnswerDecision(Contract):
    kind: Literal["answer"] = "answer"
    findings: Annotated[tuple[Finding, ...], Field(min_length=1)]
    limitations: tuple[Text, ...] = ()


class StopDecision(Contract):
    kind: Literal["stop"] = "stop"
    reason: Literal["clarification_required", "unsupported", "insufficient_evidence"]
    message: Text


AgentDecision = Annotated[
    ToolCall | AnswerDecision | StopDecision, Field(discriminator="kind")
]


class ToolDescription(Contract):
    name: ToolName
    description: Text
    arguments_schema: dict[str, JsonValue]


class DecisionContext(Contract):
    instructions: Text
    question: Text
    scope: PinnedScope
    observations: tuple[ExecutionStep, ...]
    tools: tuple[ToolDescription, ...]
    remaining_tool_calls: int
    remaining_model_calls: int


MetadataText = Annotated[Text, Field(max_length=256)]
TokenCount = Annotated[int, Field(strict=True, ge=0)]


class TokenUsage(Contract):
    # Missing means unavailable, not zero. Counts may overlap; never sum them.
    prompt: TokenCount | None = None
    output: TokenCount | None = None
    thoughts: TokenCount | None = None
    cached: TokenCount | None = None
    total: TokenCount | None = None


class ModelMetadata(Contract):
    sdk_version: MetadataText | None = None
    adapter_version: MetadataText | None = None
    api_version: MetadataText | None = None
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] | None = None
    resolved_model: MetadataText | None = None
    response_id: MetadataText | None = None
    finish_reason: MetadataText | None = None
    block_reason: MetadataText | None = None
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None = None
    max_output_tokens: TokenCount | None = None
    timeout_ms: Annotated[int, Field(strict=True, ge=1)] | None = None
    retry_attempts: Annotated[int, Field(strict=True, ge=1)] | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)


class ModelResult(Contract):
    decision: dict[str, JsonValue]
    metadata: ModelMetadata


class ModelError(Exception):
    """Safe provider failure with metadata, never a raw response or SDK exception."""

    def __init__(
        self,
        code: Literal["model_failed", "invalid_model_response"],
        metadata: ModelMetadata,
    ):
        super().__init__(code)
        self.code = code
        self.metadata = metadata


class AgentModel(Protocol):
    """One cancellable async provider request per decision, with retries disabled."""

    provider: str
    model_id: str
    request_metadata: ModelMetadata

    async def decide(self, context: DecisionContext) -> ModelResult: ...
