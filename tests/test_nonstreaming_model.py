"""Tests for the non-streaming wrapper used on custom OpenAI-compatible endpoints."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
from agents.items import ModelResponse
from agents.model_settings import ModelSettings
from agents.models.interface import Model, ModelTracing
from agents.usage import Usage
from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemDoneEvent,
    ResponseStreamEvent,
)

from strix.config.models import StrixProvider, _NonStreamingModel, _to_response_usage


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _tool_call() -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        arguments='{"command": "ls"}',
        call_id="call_1",
        name="terminal_execute",
        type="function_call",
    )


class _FakeModel(Model):
    def __init__(self, response: ModelResponse) -> None:
        self.model = "fake-model"
        self._response = response
        self.get_response_calls = 0

    async def get_response(self, *_args: object, **_kwargs: object) -> ModelResponse:
        self.get_response_calls += 1
        return self._response

    async def stream_response(  # pragma: no cover
        self, *_args: object, **_kwargs: object
    ) -> AsyncIterator[ResponseStreamEvent]:
        for _ in range(0):
            yield cast("ResponseStreamEvent", None)
        raise AssertionError("inner stream_response must never be called")


def _settings(*, api_base: str | None, stream_mode: str = "auto") -> SimpleNamespace:
    return SimpleNamespace(
        llm=SimpleNamespace(
            model="openai/glm",
            api_base=api_base,
            stream_mode=stream_mode,
            reasoning_effort="high",
        )
    )


def test_to_response_usage_maps_token_details() -> None:
    usage = Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15)
    usage.input_tokens_details.cached_tokens = 4
    usage.output_tokens_details.reasoning_tokens = 3
    mapped = _to_response_usage(usage)
    assert mapped is not None
    assert (mapped.input_tokens, mapped.output_tokens, mapped.total_tokens) == (10, 5, 15)
    assert mapped.input_tokens_details.cached_tokens == 4
    assert mapped.output_tokens_details.reasoning_tokens == 3


def test_to_response_usage_none() -> None:
    assert _to_response_usage(None) is None


@pytest.mark.asyncio
async def test_stream_response_synthesizes_tool_call_from_non_streamed() -> None:
    tool_call = _tool_call()
    inner = _FakeModel(
        ModelResponse(
            output=[tool_call],
            usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
            response_id="resp_123",
        )
    )
    wrapper = _NonStreamingModel(inner)

    events = [
        event
        async for event in wrapper.stream_response(
            "sys",
            "hi",
            ModelSettings(),
            [],
            None,
            [],
            ModelTracing.DISABLED,
        )
    ]

    assert inner.get_response_calls == 1
    item_done = [e for e in events if isinstance(e, ResponseOutputItemDoneEvent)]
    completed = [e for e in events if isinstance(e, ResponseCompletedEvent)]
    assert len(item_done) == 1
    assert item_done[0].item == tool_call
    assert len(completed) == 1
    final = completed[0].response
    assert final.output == [tool_call]
    assert final.id == "resp_123"
    assert final.usage is not None
    assert final.usage.total_tokens == 15
    # sequence numbers are strictly increasing
    assert [e.sequence_number for e in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_stream_response_delegates_get_response() -> None:
    inner = _FakeModel(
        ModelResponse(output=[], usage=Usage(), response_id=None),
    )
    wrapper = _NonStreamingModel(inner)
    result = await wrapper.get_response(
        "sys", "hi", ModelSettings(), [], None, [], ModelTracing.DISABLED
    )
    assert result is inner._response
    assert inner.get_response_calls == 1


def test_get_model_auto_streams_custom_endpoint() -> None:
    sentinel = _FakeModel(ModelResponse(output=[], usage=Usage(), response_id=None))
    with (
        patch("strix.config.models.load_settings", return_value=_settings(api_base="http://x/v1")),
        patch(
            "agents.models.multi_provider.MultiProvider.get_model",
            return_value=sentinel,
        ),
    ):
        model = StrixProvider().get_model("openai/glm")
    assert model is sentinel


def test_get_model_auto_streams_hosted() -> None:
    sentinel = _FakeModel(ModelResponse(output=[], usage=Usage(), response_id=None))
    with (
        patch("strix.config.models.load_settings", return_value=_settings(api_base="")),
        patch(
            "agents.models.multi_provider.MultiProvider.get_model",
            return_value=sentinel,
        ),
    ):
        model = StrixProvider().get_model("openai/gpt-4o")
    assert model is sentinel


def test_get_model_stream_mode_never_wraps() -> None:
    sentinel = _FakeModel(ModelResponse(output=[], usage=Usage(), response_id=None))
    with (
        patch(
            "strix.config.models.load_settings",
            return_value=_settings(api_base="http://x/v1", stream_mode="never"),
        ),
        patch(
            "agents.models.multi_provider.MultiProvider.get_model",
            return_value=sentinel,
        ),
    ):
        model = StrixProvider().get_model("openai/glm")
    assert isinstance(model, _NonStreamingModel)
