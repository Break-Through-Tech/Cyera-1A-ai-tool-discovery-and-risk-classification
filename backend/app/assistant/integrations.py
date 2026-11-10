"""Provider-facing decision interface; no SDK or production model is installed here."""

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


class AgentModel(Protocol):
    """Implementations must use cancellable async I/O and return structured data."""

    model_id: str

    async def decide(self, context: DecisionContext) -> dict[str, JsonValue]: ...
