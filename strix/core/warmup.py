"""Preflight probe: verify the model emits structured tool calls when streamed.

Strix is entirely tool-driven and runs every agent turn as a streamed request.
Some OpenAI-compatible endpoints return a valid ``tool_calls`` response when a
completion is requested non-streamed, but under streaming they emit the tool
call as plain assistant text (or drop it entirely) and close the stream. The
Agents SDK then sees a normal final message, the scan makes no progress, and it
either stalls waiting for input or burns turns on empty output.

There is no safe client-side way to execute a tool call the endpoint never
streamed, so we detect the missing capability up front — using the same
streaming path the scan uses — and fail loudly with actionable guidance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from agents import ModelSettings, ModelTracing
from agents.tool import FunctionTool
from openai.types.responses import ResponseFunctionToolCall

from strix.config.models import StrixProvider


if TYPE_CHECKING:
    from strix.config.settings import Settings


logger = logging.getLogger(__name__)

_PROBE_RETRIES = 2

_GUIDANCE = (
    "The configured LLM endpoint did not return a structured tool call when "
    "streamed.\n\n"
    "Strix drives every action through native `tool_calls`, and it streams every "
    "turn. Some OpenAI-compatible servers return tool calls correctly for a "
    "non-streamed request but, when streamed, emit the tool call as plain text "
    "(or omit it) and end the response — so Strix can never act.\n\n"
    "Fixes:\n"
    "  - llama.cpp / llama-server: start with `--jinja` so the chat template "
    "produces streamed `tool_calls` deltas.\n"
    "  - Ollama: use a model whose template wires tool calling, and disable "
    "'thinking' if the template can't stream tools alongside it.\n"
    "  - vLLM: set a matching `--tool-call-parser` (and `--enable-auto-tool-choice`) "
    "for the served model.\n"
    "  - Other gateways: confirm streamed tool calling works for this model "
    "(a non-streamed test is not enough).\n\n"
    "If you know the endpoint streams tool calls correctly, set "
    "STRIX_SKIP_TOOL_CALL_PROBE=1 to skip this check."
)

_TOOL_CONFIG_ERROR_MARKERS = (
    "jinja",
    "tool call parser",
    "tool-call-parser",
    "tool_choice",
    "does not support tools",
    "tools param",
    "tool use is not supported",
)


class ToolCallingUnsupportedError(RuntimeError):
    """The endpoint cannot return structured tool calls over a streamed request."""


async def _noop_invoke(_ctx: Any, _args: str) -> str:
    return "ok"


_PROBE_TOOL = FunctionTool(
    name="strix_ready_check",
    description="Report readiness. Call this to acknowledge you can use tools.",
    params_json_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    },
    on_invoke_tool=_noop_invoke,
    strict_json_schema=True,
)

_PROBE_SYSTEM = (
    "You are a setup probe. You can only respond by calling the provided tool. "
    "Do not produce any other output."
)
_PROBE_INPUT = 'Call the `strix_ready_check` tool now with {"status": "ok"}.'


def requires_tool_call_probe(model_name: str, settings: Settings) -> bool:
    """Only self-hosted / OpenAI-compatible routes, where the streaming leak happens."""
    return model_name.startswith("ollama/") or bool(settings.llm.api_base)


def _is_tool_config_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TOOL_CONFIG_ERROR_MARKERS)


async def _stream_saw_tool_call(
    model_name: str, model_settings: ModelSettings, *, timeout: float | None
) -> bool:
    model = StrixProvider().get_model(model_name)

    async def _run() -> bool:
        stream = model.stream_response(
            system_instructions=_PROBE_SYSTEM,
            input=_PROBE_INPUT,
            model_settings=model_settings,
            tools=[_PROBE_TOOL],
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
        # Drain the whole stream rather than returning early: the SDK wraps it in
        # a span that must be closed in the context it was opened in.
        saw_tool_call = False
        async for event in stream:
            item = getattr(event, "item", None)
            if isinstance(item, ResponseFunctionToolCall):
                saw_tool_call = True
            response = getattr(event, "response", None)
            if response is not None and any(
                isinstance(out, ResponseFunctionToolCall)
                for out in getattr(response, "output", []) or []
            ):
                saw_tool_call = True
        return saw_tool_call

    if timeout is not None:
        return await asyncio.wait_for(_run(), timeout=timeout)
    return await _run()


async def probe_tool_calling(
    model_name: str,
    settings: Settings,
    *,
    request_timeout: float | None = None,
) -> None:
    """Fail fast if a streamed request to ``model_name`` yields no structured tool call.

    No-op for hosted providers and when ``STRIX_SKIP_TOOL_CALL_PROBE`` is set.
    """
    if settings.llm.skip_tool_call_probe or not requires_tool_call_probe(model_name, settings):
        return

    model_settings = ModelSettings(
        parallel_tool_calls=False,
        include_usage=True,
    )

    last_exc: Exception | None = None
    for attempt in range(_PROBE_RETRIES + 1):
        try:
            saw_tool_call = await _stream_saw_tool_call(
                model_name, model_settings, timeout=request_timeout
            )
        except ToolCallingUnsupportedError:
            raise
        except Exception as exc:
            if _is_tool_config_error(exc):
                logger.debug("Tool-call probe hit a tool-config error", exc_info=True)
                raise ToolCallingUnsupportedError(_GUIDANCE) from exc
            last_exc = exc
            logger.debug(
                "Tool-call probe attempt %d/%d failed transiently",
                attempt + 1,
                _PROBE_RETRIES + 1,
                exc_info=True,
            )
            continue

        if saw_tool_call:
            logger.info("Tool-call probe passed for model %s", model_name)
            return
        raise ToolCallingUnsupportedError(_GUIDANCE)

    # All attempts raised transient errors; surface the last one unchanged so the
    # caller's existing connection-error handling reports it.
    if last_exc is not None:
        raise last_exc
