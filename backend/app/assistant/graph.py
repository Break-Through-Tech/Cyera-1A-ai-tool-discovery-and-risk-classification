"""Bounded single-agent workflow. Scope and integrations are supplied by the backend."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Annotated, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import Field, TypeAdapter
from sqlalchemy import Engine

from app.assistant import store
from app.assistant.contracts import (
    AssistantResponse,
    Contract,
    ExecutionStep,
    GroundedAnswer,
    LimitedResponse,
    PinnedScope,
    ToolFailure,
    ToolLimitation,
    ToolSuccess,
)
from app.assistant.integrations import (
    AgentDecision,
    AgentModel,
    DecisionContext,
    ModelError,
    ModelMetadata,
    StopDecision,
    ToolCall,
)
from app.assistant.prompts import INSTRUCTIONS, PROMPT_VERSION
from app.assistant.tools import InvalidToolResult, ToolRegistry, bounded_json


class ExecutionLimits(Contract):
    max_tool_calls: Annotated[int, Field(strict=True, ge=0, le=100)] = 8
    max_model_calls: Annotated[int, Field(strict=True, ge=1, le=100)] = 8
    max_turn_seconds: Annotated[float, Field(gt=0, le=600, allow_inf_nan=False)] = 60
    max_argument_bytes: Annotated[int, Field(strict=True, ge=1)] = 4096
    max_tool_result_bytes: Annotated[int, Field(strict=True, ge=1)] = 32768
    max_model_output_bytes: Annotated[int, Field(strict=True, ge=1)] = 32768
    max_context_bytes: Annotated[int, Field(strict=True, ge=1)] = 131072


class WorkflowState(TypedDict):
    turn_id: str
    question: str
    scope: PinnedScope
    briefing: bool
    deadline: float
    steps: tuple[ExecutionStep, ...]
    model_calls: int
    tool_calls: int
    pending: ToolCall | None
    response: AssistantResponse | None
    failure: ToolFailure | None


_BRIEFING_CALLS = (
    ToolCall(tool="describe_dataset", arguments={}),
    ToolCall(
        tool="summarize_usage",
        arguments={"metric": "event_count", "group_by": ["department"]},
    ),
    ToolCall(tool="get_risk_assessments", arguments={"focus": "all"}),
)
_DECISION = TypeAdapter(AgentDecision)


class Assistant:
    def __init__(
        self,
        engine: Engine,
        model: AgentModel,
        tools: ToolRegistry,
        limits: ExecutionLimits | None = None,
    ):
        self.engine = engine
        self.model = model
        self.tools = tools
        self.limits = limits or ExecutionLimits()
        graph = StateGraph(WorkflowState)
        graph.add_node("briefing", self._briefing)
        graph.add_node("decide", self._decide)
        graph.add_node("execute", self._execute_pending)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "briefing")
        graph.add_conditional_edges("briefing", self._after_execution)
        graph.add_conditional_edges("decide", self._after_decision)
        graph.add_conditional_edges("execute", self._after_execution)
        graph.add_edge("finalize", END)
        self._graph = graph.compile()

    async def run_turn(
        self,
        *,
        question: str,
        scope: PinnedScope,
        briefing: bool = False,
    ) -> store.StoredTurn:
        if briefing and len(scope.runs) != 1:
            raise ValueError(
                "A Batch briefing requires exactly one pinned Batch and Run"
            )
        turn = store.start_turn(
            self.engine,
            question=question,
            scope=scope,
            model_id=self.model.model_id,
            prompt_version=PROMPT_VERSION,
        )
        state = WorkflowState(
            turn_id=turn.turn_id,
            question=turn.question,
            scope=turn.scope,
            briefing=briefing,
            deadline=monotonic() + self.limits.max_turn_seconds,
            steps=(),
            model_calls=0,
            tool_calls=0,
            pending=None,
            response=None,
            failure=None,
        )
        try:
            await self._graph.ainvoke(
                state,
                config={
                    "recursion_limit": 3
                    * (self.limits.max_model_calls + self.limits.max_tool_calls)
                    + 20,
                },
            )
        except (Exception, asyncio.CancelledError) as error:
            # Unexpected/storage failures reach the caller, never a partial answer.
            # A post-commit error must not rewrite an already finalized turn.
            if store.get_turn(self.engine, turn.turn_id).status == "running":
                cancelled = isinstance(error, asyncio.CancelledError)
                store.fail_turn(
                    self.engine,
                    turn.turn_id,
                    ToolFailure(
                        code="turn_cancelled" if cancelled else "workflow_failed",
                        message="Investigation was cancelled; retry."
                        if cancelled
                        else "Investigation failed; retry.",
                    ),
                )
            raise
        return store.get_turn(self.engine, turn.turn_id)

    async def _briefing(self, state: WorkflowState) -> WorkflowState:
        if not state["briefing"]:
            return state
        if self.limits.max_tool_calls < len(_BRIEFING_CALLS):
            return self._budget_stop(
                state, "Standard Batch briefing summaries were not completed."
            )
        for call in _BRIEFING_CALLS:
            state = await self._execute(state, call)
            if state["failure"] or state["response"]:
                return state
            outcome = state["steps"][-1].outcome
            if isinstance(outcome, ToolLimitation):
                return {
                    **state,
                    "response": LimitedResponse(
                        scope=state["scope"],
                        reason="clarification_required"
                        if outcome.reason == "clarification_required"
                        else "unsupported",
                        message=outcome.message
                        if outcome.reason == "clarification_required"
                        else "The standard briefing requires query capabilities that are not available.",
                        limitations=self._qualifications(state),
                    ),
                }
        return state

    async def _decide(self, state: WorkflowState) -> WorkflowState:
        if (
            monotonic() >= state["deadline"]
            or state["model_calls"] >= self.limits.max_model_calls
        ):
            return self._budget_stop(
                state,
                "The final answer and any remaining investigations were not completed.",
            )
        sequence = state["model_calls"] + 1
        context = DecisionContext(
            instructions=INSTRUCTIONS,
            question=state["question"],
            scope=state["scope"],
            observations=state["steps"],
            tools=self.tools.descriptions(),
            remaining_tool_calls=self.limits.max_tool_calls - state["tool_calls"],
            remaining_model_calls=self.limits.max_model_calls - sequence,
        )
        try:
            context_json = bounded_json(context, self.limits.max_context_bytes)
        except ValueError:
            return self._failure(
                state,
                "context_limit",
                "Investigation context exceeds its limit; narrow the request.",
            )
        state = {**state, "model_calls": sequence}
        metadata = self.model.request_metadata
        store.start_model_call(
            self.engine,
            state["turn_id"],
            sequence=sequence,
            provider=self.model.provider,
            requested_model=self.model.model_id,
            context_sha256=sha256(context_json).hexdigest(),
            metadata=metadata,
        )
        try:
            async with asyncio.timeout(max(0, state["deadline"] - monotonic())):
                result = await self.model.decide(context.model_copy(deep=True))
                metadata = result.metadata
                if monotonic() >= state["deadline"]:
                    raise TimeoutError
        except TimeoutError:
            return self._model_failure(
                state, metadata, "model_timeout", "The model request timed out; retry."
            )
        except ModelError as error:
            return self._model_failure(
                state,
                error.metadata,
                error.code,
                "The model request failed or returned an invalid response; retry.",
            )
        except Exception:  # noqa: BLE001 - Provider boundary: retain only safe diagnostics.
            return self._model_failure(
                state, metadata, "model_failed", "The model request failed; retry."
            )
        try:
            decision = _DECISION.validate_json(
                bounded_json(result.decision, self.limits.max_model_output_bytes)
            )
        except (ValueError, TypeError):
            return self._model_failure(
                state,
                metadata,
                "invalid_model_response",
                "The model returned an invalid response; retry.",
            )
        store.finish_model_call(
            self.engine, state["turn_id"], sequence, metadata=metadata
        )
        if isinstance(decision, ToolCall):
            if state["tool_calls"] >= self.limits.max_tool_calls:
                return self._budget_stop(
                    state, f"Requested {decision.tool} follow-up was not executed."
                )
            return {**state, "pending": decision}
        response: AssistantResponse
        if isinstance(decision, StopDecision):
            response = LimitedResponse(
                scope=state["scope"],
                reason=decision.reason,
                message=decision.message,
                limitations=self._qualifications(state),
            )
        else:
            response = GroundedAnswer(
                scope=state["scope"],
                findings=decision.findings,
                limitations=tuple(
                    dict.fromkeys((*decision.limitations, *self._qualifications(state)))
                ),
                stop_reason="sufficient_evidence",
            )
        return {**state, "response": response}

    async def _execute_pending(self, state: WorkflowState) -> WorkflowState:
        if state["pending"] is None:
            raise ValueError("No validated tool decision is pending")
        return await self._execute(state, state["pending"])

    async def _execute(self, state: WorkflowState, call: ToolCall) -> WorkflowState:
        if (
            monotonic() >= state["deadline"]
            or state["tool_calls"] >= self.limits.max_tool_calls
        ):
            return self._budget_stop(
                state, f"Requested {call.tool} operation was not executed."
            )
        try:
            arguments = self.tools.prepare(
                call, state["scope"], self.limits.max_argument_bytes
            )
        except ValueError:
            return self._failure(
                state,
                "invalid_tool_arguments",
                "The requested tool arguments are invalid; retry.",
            )
        step_id = f"step_{uuid4().hex}"
        started_at = datetime.now(UTC)
        cancelled = False
        try:
            async with asyncio.timeout(max(0, state["deadline"] - monotonic())):
                outcome = await self.tools.invoke(
                    call.tool,
                    state["scope"],
                    arguments,
                    reference_namespace=step_id,
                    maximum_bytes=self.limits.max_tool_result_bytes,
                )
                if monotonic() >= state["deadline"]:
                    raise TimeoutError
        except asyncio.CancelledError:
            cancelled = True
            outcome = ToolFailure(
                code="tool_cancelled", message="Tool execution was cancelled; retry."
            )
        except TimeoutError:
            outcome = ToolFailure(
                code="tool_timeout", message="Tool execution timed out; retry."
            )
        except InvalidToolResult:
            outcome = ToolFailure(
                code="invalid_tool_result",
                message="The tool returned invalid results; retry.",
            )
        except Exception:  # noqa: BLE001 - Tool boundary: retain only safe diagnostics.
            outcome = ToolFailure(
                code="tool_failed", message="Tool execution failed; retry."
            )
        step = ExecutionStep(
            step_id=step_id,
            sequence=len(state["steps"]) + 1,
            tool=call.tool,
            scope=state["scope"],
            arguments=arguments.model_dump(mode="json"),
            started_at=started_at,
            completed_at=datetime.now(UTC),
            outcome=outcome,
        )
        store.append_step(self.engine, state["turn_id"], step)
        if cancelled:
            raise asyncio.CancelledError
        return {
            **state,
            "steps": (*state["steps"], step),
            "tool_calls": state["tool_calls"] + 1,
            "pending": None,
            "failure": outcome if isinstance(outcome, ToolFailure) else None,
        }

    async def _finalize(self, state: WorkflowState) -> WorkflowState:
        if state["failure"] is not None:
            store.fail_turn(self.engine, state["turn_id"], state["failure"])
        elif state["response"] is not None:
            try:
                store.finish_turn(self.engine, state["turn_id"], state["response"])
            except ValueError:
                state = self._failure(
                    state,
                    "invalid_answer",
                    "The answer references could not be validated; retry.",
                )
                store.fail_turn(self.engine, state["turn_id"], state["failure"])
        else:
            raise ValueError("Workflow ended without a response or failure")
        return state

    def _model_failure(
        self,
        state: WorkflowState,
        metadata: ModelMetadata,
        code: str,
        message: str,
    ) -> WorkflowState:
        store.finish_model_call(
            self.engine,
            state["turn_id"],
            state["model_calls"],
            metadata=metadata,
            failure=ToolFailure(code=code, message=message),
        )
        return self._failure(state, code, message)

    @staticmethod
    def _after_execution(state: WorkflowState) -> str:
        return "finalize" if state["failure"] or state["response"] else "decide"

    @staticmethod
    def _after_decision(state: WorkflowState) -> str:
        return "execute" if state["pending"] else "finalize"

    @staticmethod
    def _failure(state: WorkflowState, code: str, message: str) -> WorkflowState:
        return {
            **state,
            "pending": None,
            "response": None,
            "failure": ToolFailure(code=code, message=message),
        }

    def _budget_stop(self, state: WorkflowState, unfinished_work: str) -> WorkflowState:
        return {
            **state,
            "pending": None,
            "response": LimitedResponse(
                scope=state["scope"],
                reason="budget_reached",
                message="The execution budget was reached before a final answer was produced. Investigation remains unfinished.",
                limitations=self._qualifications(state),
                unfinished_work=(unfinished_work,),
            ),
        }

    @staticmethod
    def _qualifications(state: WorkflowState) -> tuple[str, ...]:
        qualifications = list(state["scope"].qualifications)
        for step in state["steps"]:
            if isinstance(step.outcome, ToolSuccess):
                qualifications.extend(step.outcome.qualifications)
            elif isinstance(step.outcome, ToolLimitation):
                qualifications.append(step.outcome.message)
        return tuple(dict.fromkeys(qualifications))
