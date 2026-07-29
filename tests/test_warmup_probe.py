from __future__ import annotations

import types
from typing import TYPE_CHECKING, Any

import pytest
from openai.types.responses import ResponseFunctionToolCall

from strix.core import warmup
from strix.core.warmup import (
    ToolCallingUnsupportedError,
    probe_tool_calling,
    requires_tool_call_probe,
)


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _settings(*, api_base: str | None = None, skip: bool = False) -> Any:
    return types.SimpleNamespace(
        llm=types.SimpleNamespace(api_base=api_base, skip_tool_call_probe=skip),
    )


def _tool_call_event() -> Any:
    return types.SimpleNamespace(
        item=ResponseFunctionToolCall(
            arguments='{"status": "ok"}',
            call_id="call_1",
            name="strix_ready_check",
            type="function_call",
        ),
    )


def _text_event() -> Any:
    # A completed response whose output is a plain message, no tool call.
    return types.SimpleNamespace(
        item=None,
        response=types.SimpleNamespace(output=[types.SimpleNamespace(type="message")]),
    )


class _FakeModel:
    def __init__(self, events: list[Any] | None = None, raises: Exception | None = None) -> None:
        self._events = events or []
        self._raises = raises

    def stream_response(self, **_kwargs: Any) -> AsyncIterator[Any]:
        events = self._events
        raises = self._raises

        async def _gen() -> AsyncIterator[Any]:
            if raises is not None:
                raise raises
            for event in events:
                yield event

        return _gen()


def _patch_model(monkeypatch: pytest.MonkeyPatch, model: _FakeModel) -> None:
    monkeypatch.setattr(
        warmup, "StrixProvider", lambda: types.SimpleNamespace(get_model=lambda _m: model)
    )


def test_requires_probe_only_for_custom_endpoints_and_ollama() -> None:
    assert requires_tool_call_probe("openai/glm-5.2", _settings(api_base="http://x")) is True
    assert requires_tool_call_probe("ollama/llama3", _settings()) is True
    assert requires_tool_call_probe("openai/gpt-4o", _settings()) is False
    assert requires_tool_call_probe("anthropic/claude", _settings()) is False


@pytest.mark.asyncio
async def test_probe_skipped_for_hosted_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # Would raise if it tried to stream; gating must short-circuit first.
    _patch_model(monkeypatch, _FakeModel(raises=RuntimeError("should not be called")))
    await probe_tool_calling("openai/gpt-4o", _settings())


@pytest.mark.asyncio
async def test_probe_skipped_when_setting_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model(monkeypatch, _FakeModel(raises=RuntimeError("should not be called")))
    await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x", skip=True))


@pytest.mark.asyncio
async def test_probe_passes_on_streamed_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model(monkeypatch, _FakeModel(events=[_tool_call_event()]))
    await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x"))


@pytest.mark.asyncio
async def test_probe_passes_when_tool_call_only_in_final_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = types.SimpleNamespace(
        item=None,
        response=types.SimpleNamespace(
            output=[
                ResponseFunctionToolCall(
                    arguments="{}",
                    call_id="c",
                    name="strix_ready_check",
                    type="function_call",
                )
            ]
        ),
    )
    _patch_model(monkeypatch, _FakeModel(events=[completed]))
    await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x"))


@pytest.mark.asyncio
async def test_probe_aborts_when_only_text_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model(monkeypatch, _FakeModel(events=[_text_event()]))
    with pytest.raises(ToolCallingUnsupportedError):
        await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x"))


@pytest.mark.asyncio
async def test_probe_aborts_on_tool_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model(monkeypatch, _FakeModel(raises=RuntimeError("tools param requires --jinja flag")))
    with pytest.raises(ToolCallingUnsupportedError):
        await probe_tool_calling("ollama/llama3", _settings(api_base="http://x"))


@pytest.mark.asyncio
async def test_probe_retries_transient_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    good = _FakeModel(events=[_tool_call_event()])

    class _Flaky:
        def stream_response(self, **kwargs: Any) -> AsyncIterator[Any]:
            calls["n"] += 1
            if calls["n"] == 1:

                async def _boom() -> AsyncIterator[Any]:
                    for _ in range(0):  # make this a generator without an unreachable yield
                        yield None
                    raise ConnectionError("transient")

                return _boom()
            return good.stream_response(**kwargs)

    _patch_model(monkeypatch, _Flaky())  # type: ignore[arg-type]
    await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x"))
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_probe_surfaces_persistent_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_model(monkeypatch, _FakeModel(raises=ConnectionError("down")))
    with pytest.raises(ConnectionError):
        await probe_tool_calling("openai/glm-5.2", _settings(api_base="http://x"))
