"""Tests for STOAITH stall fencing in ReportUsageHooks.

A stall turn is an LLM turn whose model response requests only bookkeeping
tools. A sub-agent that accumulates STRIX_STALL_TURN_LIMIT consecutive stall
turns is force-stopped; the root agent is warned but never fenced; any turn
that requests an external-action (or unknown) tool resets the counter; 0
disables the fence entirely.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from strix.core.hooks import AgentStallDetectedError, ReportUsageHooks


def _make_hooks(stall_turn_limit: int = 80) -> ReportUsageHooks:
    return ReportUsageHooks(model="test-model", stall_turn_limit=stall_turn_limit)


def _make_context(parent_id: str | None = "root-1", agent_id: str = "child-agent") -> MagicMock:
    ctx: MagicMock = MagicMock()
    ctx.context = {"agent_id": agent_id, "parent_id": parent_id}
    return ctx


def _agent(name: str = "child") -> MagicMock:
    agent = MagicMock()
    agent.name = name
    return agent


def _tool_item(name: str) -> SimpleNamespace:
    return SimpleNamespace(type="function_call", name=name)


def _response(*names: str) -> MagicMock:
    response = MagicMock()
    response.output = [_tool_item(n) for n in names] or None
    return response


def test_default_stall_limit_is_80() -> None:
    hooks = ReportUsageHooks(model="test-model")
    assert hooks._stall_turn_limit == 80


def test_negative_stall_limit_rejected() -> None:
    with pytest.raises(ValueError, match="stall_turn_limit"):
        ReportUsageHooks(model="test-model", stall_turn_limit=-1)


def test_stall_error_is_runtime_error() -> None:
    err = AgentStallDetectedError("boom")
    assert isinstance(err, RuntimeError)


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_stall_warns_at_25_50_75(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=4)
    agent = _agent()
    ctx = _make_context()
    contents: list[str] = []

    # Turn 1: stall 1/4 = 25% -> NOTICE.
    items: list[Any] = []
    await hooks.on_llm_start(ctx, agent, None, items)
    contents.append(items[-1]["content"])
    # Turn 2: stall 2/4 = 50% -> URGENT.
    items = []
    await hooks.on_llm_start(ctx, agent, None, items)
    contents.append(items[-1]["content"])
    # Turn 3: stall 3/4 = 75% -> CRITICAL.
    items = []
    await hooks.on_llm_start(ctx, agent, None, items)
    contents.append(items[-1]["content"])

    assert "[NOTICE]" in contents[0]
    assert "[URGENT]" in contents[1]
    assert "[CRITICAL]" in contents[2]


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_stall_fences_subagent_exactly_at_limit(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=4)
    agent = _agent()
    ctx = _make_context()

    # Turns 1-3: stall climbs 1, 2, 3 (warnings, no fence).
    for _ in range(3):
        await hooks.on_llm_start(ctx, agent, None, [])
    # Turn 4: stall == 4 == limit -> fence.
    with pytest.raises(AgentStallDetectedError, match="stall limit 4"):
        await hooks.on_llm_start(ctx, agent, None, [])


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_external_tool_resets_counter_before_fence(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=3)
    agent = _agent()
    ctx = _make_context()

    # Turn 1: stall 1.
    await hooks.on_llm_start(ctx, agent, None, [])
    # Response requests exec_command (external) -> resets to 0.
    await hooks.on_llm_end(ctx, agent, _response("exec_command"))
    # Turns 2-3: stall 1, then 2 (still below limit 3, no fence).
    await hooks.on_llm_start(ctx, agent, None, [])
    await hooks.on_llm_start(ctx, agent, None, [])


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_unknown_tool_counts_as_progress(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=3)
    agent = _agent()
    ctx = _make_context()

    # Turn 1: stall 1.
    await hooks.on_llm_start(ctx, agent, None, [])
    # Response requests an unknown tool -> fails safe as progress (reset).
    await hooks.on_llm_end(ctx, agent, _response("some_unknown_tool"))
    # Turns 2-3: stall 1, then 2 (below limit 3, no fence).
    await hooks.on_llm_start(ctx, agent, None, [])
    await hooks.on_llm_start(ctx, agent, None, [])


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_bookkeeping_tool_does_not_reset_counter(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=3)
    agent = _agent()
    ctx = _make_context()

    # Turn 1: stall 1.
    await hooks.on_llm_start(ctx, agent, None, [])
    # Response requests "think" (bookkeeping) -> no reset.
    await hooks.on_llm_end(ctx, agent, _response("think"))
    # Turns 2-3: stall 2, then 3 -> fence exactly at 3.
    await hooks.on_llm_start(ctx, agent, None, [])
    with pytest.raises(AgentStallDetectedError):
        await hooks.on_llm_start(ctx, agent, None, [])


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_root_agent_warned_but_never_fenced(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=4)
    agent = _agent(name="root")
    ctx = _make_context(parent_id=None)
    warnings: list[str] = []

    for _ in range(6):
        items: list[Any] = []
        await hooks.on_llm_start(ctx, agent, None, items)
        if items:
            warnings.append(items[-1]["content"])

    # Root receives NOTICE/URGENT/CRITICAL warnings but is never fenced.
    assert len(warnings) >= 3
    assert "[NOTICE]" in warnings[0]
    assert "[CRITICAL]" in warnings[-1]


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_disabled_fence_never_warns_or_fences(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=0)
    agent = _agent()
    ctx = _make_context()

    for _ in range(10):
        items: list[Any] = []
        await hooks.on_llm_start(ctx, agent, None, items)
        assert items == []


@pytest.mark.asyncio
@patch("strix.core.hooks.get_global_report_state", return_value=None)
async def test_counters_are_isolated_per_agent(_state: MagicMock) -> None:
    hooks = _make_hooks(stall_turn_limit=3)
    agent = _agent()

    # Agent A: stall 1, 2, then fence at 3.
    ctx_a = _make_context(agent_id="agent-a")
    await hooks.on_llm_start(ctx_a, agent, None, [])
    await hooks.on_llm_start(ctx_a, agent, None, [])
    with pytest.raises(AgentStallDetectedError):
        await hooks.on_llm_start(ctx_a, agent, None, [])

    # Agent B: fresh context, no inherited counter.
    ctx_b = _make_context(agent_id="agent-b")
    await hooks.on_llm_start(ctx_b, agent, None, [])
    await hooks.on_llm_start(ctx_b, agent, None, [])
    # B is at 2, below the limit; no raise.
