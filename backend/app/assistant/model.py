"""Gemini Developer API adapter. Function declarations never execute application code."""

import json
from enum import Enum
from typing import Annotated, Self

from google import genai
from google.genai import errors, types
from pydantic import Field, SecretStr, field_validator

from app.assistant.contracts import Contract, Text
from app.assistant.integrations import (
    AnswerDecision,
    DecisionContext,
    ModelError,
    ModelMetadata,
    ModelResult,
    StopDecision,
    TokenUsage,
    ToolCall,
)
from app.config import Settings


class GeminiConfig(Contract):
    api_key: SecretStr
    model_id: Annotated[
        Text, Field(pattern=r"^(models/)?gemini-[A-Za-z0-9._-]+$", max_length=200)
    ]
    timeout_seconds: Annotated[
        float, Field(strict=True, gt=0, le=600, allow_inf_nan=False)
    ] = 30
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=32768)] = 4096

    @field_validator("api_key")
    @classmethod
    def require_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or "\n" in key or "\r" in key:
            raise ValueError("GEMINI_API_KEY must be nonblank and single-line")
        return SecretStr(key)


_ANSWER = "return_findings"
_STOP = "stop_investigation"
_ADAPTER_INSTRUCTIONS = """
Use exactly one native function call per response. Do not emit prose or multiple
parallel calls. Use return_findings for a cited answer or stop_investigation for
a clarification, unsupported request, or insufficient evidence. These two
functions only return responses; they do not execute an operation. Select other
functions only to request backend tool execution. Never claim the requested
function has already executed. This is a fresh decision over the supplied
snapshot, not a continuation of a provider-managed conversation.
"""


def _terminal_declaration(
    name: str, description: str, schema: type[Contract]
) -> types.FunctionDeclaration:
    parameters = schema.model_json_schema()
    parameters["properties"].pop("kind")
    return types.FunctionDeclaration(
        name=name, description=description, parameters_json_schema=parameters
    )


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return str(value.value) if isinstance(value, Enum) else str(value)


class GeminiModel:
    provider = "gemini"

    def __init__(self, config: GeminiConfig, *, client: genai.Client | None = None):
        self.model_id = config.model_id
        self.request_metadata = ModelMetadata(
            sdk_version=genai.__version__,
            adapter_version="gemini-native-functions-v1",
            api_version="v1beta",
            temperature=0,
            max_output_tokens=config.max_output_tokens,
            timeout_ms=max(1, int(config.timeout_seconds * 1000)),
            retry_attempts=1,
        )
        self._client = client or genai.Client(
            api_key=config.api_key.get_secret_value(),
            vertexai=False,
            enterprise=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com",
                api_version="v1beta",
                timeout=self.request_metadata.timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self | None:
        # A key alone must not enable a model or break unrelated backend workflows.
        if not settings.gemini_model:
            return None
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_MODEL requires GEMINI_API_KEY")
        return cls(
            GeminiConfig(
                api_key=SecretStr(settings.gemini_api_key),
                model_id=settings.gemini_model,
                timeout_seconds=settings.gemini_timeout_seconds,
                max_output_tokens=settings.gemini_max_output_tokens,
            )
        )

    async def aclose(self) -> None:
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()

    async def decide(self, context: DecisionContext) -> ModelResult:
        declarations = [
            _terminal_declaration(
                _ANSWER,
                "Return findings supported by observed evidence IDs.",
                AnswerDecision,
            ),
            _terminal_declaration(
                _STOP,
                "Return clarification, an unsupported request, or insufficient evidence.",
                StopDecision,
            ),
        ]
        if context.remaining_tool_calls > 0:
            for tool in context.tools:
                declarations.append(
                    types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters_json_schema=tool.arguments_schema
                        if tool.arguments_schema.get("properties")
                        else None,
                    )
                )
        names = [declaration.name for declaration in declarations]
        config = types.GenerateContentConfig(
            system_instruction=context.instructions + "\n" + _ADAPTER_INSTRUCTIONS,
            tools=[types.Tool(function_declarations=declarations)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=names,
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            candidate_count=1,
            temperature=0,
            max_output_tokens=self.request_metadata.max_output_tokens,
        )
        payload = context.model_dump(mode="json", exclude={"instructions", "tools"})
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents=json.dumps(payload, allow_nan=False, ensure_ascii=False),
                config=config,
            )
        except errors.APIError as error:
            status = (
                error.code
                if isinstance(error.code, int) and 100 <= error.code <= 599
                else None
            )
            raise ModelError(
                "model_failed",
                self.request_metadata.model_copy(update={"http_status": status}),
            ) from None
        metadata = self._response_metadata(response)
        candidates = response.candidates or []
        if (
            len(candidates) != 1
            or metadata.finish_reason != "STOP"
            or metadata.block_reason
        ):
            raise ModelError("invalid_model_response", metadata)
        parts = candidates[0].content.parts if candidates[0].content else []
        visible = [part for part in (parts or []) if not part.thought]
        if len(visible) != 1 or visible[0].function_call is None:
            raise ModelError("invalid_model_response", metadata)
        call = visible[0].function_call
        if call.name not in names or "kind" in (call.args or {}):
            raise ModelError("invalid_model_response", metadata)
        try:
            if call.name == _ANSWER:
                decision = AnswerDecision.model_validate(call.args or {})
            elif call.name == _STOP:
                decision = StopDecision.model_validate(call.args or {})
            else:
                decision = ToolCall(tool=call.name, arguments=call.args or {})
        except ValueError:
            raise ModelError("invalid_model_response", metadata) from None
        return ModelResult(decision=decision.model_dump(mode="json"), metadata=metadata)

    def _response_metadata(
        self, response: types.GenerateContentResponse
    ) -> ModelMetadata:
        candidate = response.candidates[0] if response.candidates else None
        usage = response.usage_metadata
        block = (
            _enum_value(response.prompt_feedback.block_reason)
            if response.prompt_feedback
            else None
        )
        if block == "BLOCKED_REASON_UNSPECIFIED":
            block = None
        return ModelMetadata(
            **self.request_metadata.model_dump(
                exclude={
                    "resolved_model",
                    "response_id",
                    "finish_reason",
                    "block_reason",
                    "usage",
                }
            ),
            resolved_model=response.model_version,
            response_id=response.response_id,
            finish_reason=_enum_value(candidate.finish_reason) if candidate else None,
            block_reason=block,
            usage=TokenUsage(
                prompt=usage.prompt_token_count,
                output=usage.candidates_token_count,
                thoughts=usage.thoughts_token_count,
                cached=usage.cached_content_token_count,
                total=usage.total_token_count,
            )
            if usage
            else TokenUsage(),
        )
