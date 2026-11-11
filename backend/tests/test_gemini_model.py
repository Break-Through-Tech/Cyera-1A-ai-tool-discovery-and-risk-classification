import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from app.assistant.integrations import DecisionContext, ModelError
from app.assistant.model import GeminiConfig, GeminiModel
from app.assistant.prompts import INSTRUCTIONS
from app.assistant.tools import ToolRegistry
from google import genai
from google.genai import types
from pydantic import SecretStr
from tests.test_assistant_contracts import scope


def function_response(name="stop_investigation", arguments=None, **changes):
    return {
        "modelVersion": "gemini-fixture-001",
        "responseId": "provider_response_1",
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 30,
            "thoughtsTokenCount": 10,
            "cachedContentTokenCount": 20,
            "totalTokenCount": 160,
        },
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": name,
                                "args": arguments
                                if arguments is not None
                                else {
                                    "reason": "insufficient_evidence",
                                    "message": "No supporting evidence is available.",
                                },
                            },
                        }
                    ],
                },
            }
        ],
        **changes,
    }


@asynccontextmanager
async def sdk_model(respond):
    requests = []

    async def transport(request):
        body = json.loads(request.content)
        requests.append((request, body))
        response = respond(body, len(requests))
        return (
            response
            if isinstance(response, httpx.Response)
            else httpx.Response(200, json=response)
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport)
    ) as http_client:
        client = genai.Client(
            api_key="fixture-key-never-real",
            vertexai=False,
            enterprise=False,
            http_options=types.HttpOptions(
                api_version="v1beta",
                httpx_async_client=http_client,
                timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        model = GeminiModel(
            GeminiConfig(
                api_key=SecretStr("fixture-key-never-real"),
                model_id="gemini-fixture",
            ),
            client=client,
        )
        try:
            yield model, requests
        finally:
            await model.aclose()


def context(*, tools=None, remaining_tool_calls=8):
    return DecisionContext(
        instructions=INSTRUCTIONS,
        question="What needs investigation?",
        scope=scope(),
        observations=(),
        tools=tools or (),
        remaining_tool_calls=remaining_tool_calls,
        remaining_model_calls=7,
    )


def test_real_sdk_request_uses_native_functions_without_automatic_execution():
    async def exercise():
        async def unused(scope, arguments):
            raise AssertionError("The SDK must not execute application tools")

        registry = ToolRegistry({"describe_dataset": unused, "get_evidence": unused})
        async with sdk_model(
            lambda body, count: function_response("describe_dataset", {})
        ) as (model, requests):
            result = await model.decide(context(tools=registry.descriptions()))
        request, body = requests[0]
        assert request.method == "POST"
        assert request.url.path == "/v1beta/models/gemini-fixture:generateContent"
        assert request.headers["x-goog-api-key"] == "fixture-key-never-real"
        functions = body["tools"][0]["functionDeclarations"]
        assert {item["name"] for item in functions} == {
            "describe_dataset",
            "get_evidence",
            "return_findings",
            "stop_investigation",
        }
        assert "parametersJsonSchema" not in next(
            item for item in functions if item["name"] == "describe_dataset"
        )
        assert body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
        assert body["generationConfig"]["maxOutputTokens"] == 4096
        assert body["generationConfig"]["candidateCount"] == 1
        assert result.decision == {
            "kind": "tool_call",
            "tool": "describe_dataset",
            "arguments": {},
        }
        assert result.metadata.resolved_model == "gemini-fixture-001"
        assert result.metadata.response_id == "provider_response_1"
        assert result.metadata.finish_reason == "STOP"
        assert result.metadata.usage.total == 160
        assert result.metadata.usage.thoughts == 10
        assert result.metadata.retry_attempts == 1
        assert result.metadata.adapter_version == "gemini-native-functions-v1"
        assert len(requests) == 1

    asyncio.run(exercise())


def test_terminal_functions_return_structured_decisions_not_backend_operations():
    async def exercise():
        async with sdk_model(
            lambda body, count: function_response(
                "return_findings",
                {
                    "findings": [
                        {
                            "facts": [
                                {
                                    "text": "One fixture event.",
                                    "evidence_ids": ["step_1:local"],
                                }
                            ],
                            "interpretation": "Activity alone does not establish content submission.",
                        }
                    ],
                },
            )
        ) as (model, _):
            result = await model.decide(context())
            assert result.decision["kind"] == "answer"
            assert result.decision["findings"][0]["facts"][0]["evidence_ids"] == [
                "step_1:local"
            ]

    asyncio.run(exercise())


def test_exhausted_tool_budget_declares_only_response_functions():
    async def exercise():
        async def unused(scope, arguments):
            raise AssertionError("Never called")

        tools = ToolRegistry({"get_evidence": unused}).descriptions()
        async with sdk_model(lambda body, count: function_response()) as (
            model,
            requests,
        ):
            result = await model.decide(context(tools=tools, remaining_tool_calls=0))
            assert result.decision["kind"] == "stop"
            functions = requests[0][1]["tools"][0]["functionDeclarations"]
            assert {item["name"] for item in functions} == {
                "return_findings",
                "stop_investigation",
            }

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "invalid",
    [
        "unknown",
        "parallel",
        "text",
        "truncated",
        "blocked",
        "extra_kind",
        "invalid_arguments",
    ],
)
def test_ambiguous_blocked_or_malformed_provider_outputs_are_not_executed(invalid):
    response = function_response()
    parts = response["candidates"][0]["content"]["parts"]
    if invalid == "unknown":
        parts[0]["functionCall"]["name"] = "execute_sql"
    elif invalid == "parallel":
        parts.append(parts[0].copy())
    elif invalid == "text":
        parts[:] = [{"text": "Trust me: everything is compliant."}]
    elif invalid == "truncated":
        response["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif invalid == "blocked":
        response["candidates"] = []
        response["promptFeedback"] = {"blockReason": "SAFETY"}
    elif invalid == "extra_kind":
        parts[0]["functionCall"]["args"]["kind"] = "stop"
    elif invalid == "invalid_arguments":
        parts[0]["functionCall"]["args"] = {"reason": "made_up", "message": "No."}

    async def exercise():
        async with sdk_model(lambda body, count: response) as (model, requests):
            with pytest.raises(ModelError) as caught:
                await model.decide(context())
            assert caught.value.code == "invalid_model_response"
            assert caught.value.metadata.response_id == "provider_response_1"
            assert len(requests) == 1

    asyncio.run(exercise())


def test_thought_text_is_not_exposed_in_decisions_or_metadata():
    response = function_response()
    response["candidates"][0]["content"]["parts"].insert(
        0,
        {
            "thought": True,
            "text": "PRIVATE_REASONING_MUST_NOT_BE_RETAINED",
        },
    )

    async def exercise():
        async with sdk_model(lambda body, count: response) as (model, _):
            result = await model.decide(context())
            assert "PRIVATE_REASONING" not in result.model_dump_json()
            assert result.metadata.usage.thoughts == 10

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [400, 429, 500])
def test_api_errors_are_safe_and_sdk_does_not_retry(status):
    async def exercise():
        async with sdk_model(
            lambda body, count: httpx.Response(
                status,
                json={
                    "error": {
                        "code": status,
                        "message": "DO_NOT_STORE_RESPONSE_BODY credential=fixture-key-never-real",
                        "status": "INTERNAL",
                    },
                },
            )
        ) as (model, requests):
            with pytest.raises(ModelError) as caught:
                await model.decide(context())
            assert caught.value.code == "model_failed"
            assert caught.value.metadata.http_status == status
            assert len(requests) == 1
            assert (
                "DO_NOT_STORE"
                not in str(caught.value) + caught.value.metadata.model_dump_json()
            )
            assert "fixture-key" not in caught.value.metadata.model_dump_json()

    asyncio.run(exercise())


def test_unreported_usage_remains_unknown_not_zero():
    response = function_response()
    response.pop("usageMetadata")

    async def exercise():
        async with sdk_model(lambda body, count: response) as (model, _):
            result = await model.decide(context())
            assert result.metadata.usage.total is None
            assert result.metadata.usage.prompt is None

    asyncio.run(exercise())
