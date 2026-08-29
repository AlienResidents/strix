"""Tests for reasoning-effort plumbing to non-Codex (OpenRouter) routes.

The real bind is the request-time gate in ``make_model_settings``, which used
to require ``model_supports_reasoning(model_name)``. LiteLLM's hardcoded
``supports_reasoning`` map has no entry for the Strix OpenRouter models (GLM,
Kimi, DeepSeek bare or ``openai/``-prefixed), so an explicit operator-set
effort was silently dropped for every one of them. These tests pin both halves
of the fix: the pure ``resolve_reasoning_effort`` mapping, and the relaxed gate
that lets an ``openai/``-prefixed route receive the effort regardless of the
LiteLLM table.
"""

from __future__ import annotations

from typing import Any

import pytest
from agents.model_settings import ModelSettings
from openai.types.shared import Reasoning

from strix.config import codex
from strix.config.models import (
    model_supports_reasoning,
    resolve_reasoning_effort,
)
from strix.core import inputs as inputs_mod
from strix.core.inputs import make_model_settings


@pytest.mark.parametrize(
    ("effort", "supported", "expected"),
    [
        # supported is None -> operator's literal request passes through.
        ("max", None, "max"),
        ("xhigh", None, "xhigh"),
        ("high", None, "high"),
        ("medium", None, "medium"),
        ("low", None, "low"),
        ("minimal", None, "minimal"),
        # effort directly in supported -> unchanged.
        ("max", ["max", "high", "low"], "max"),
        ("high", ["max", "high", "low"], "high"),
        ("low", ["max", "high", "low"], "low"),
        # Nearest at-or-below wins, never escalating above the request.
        # OpenRouter reports highest-first; the resolver must be order-insensitive.
        ("medium", ["max", "high", "low"], "low"),
        ("xhigh", ["max", "high", "low"], "high"),
        ("minimal", ["max", "high", "low"], "low"),
        # supported reversed: same result as highest-first.
        ("medium", ["low", "high", "max"], "low"),
        ("xhigh", ["low", "high", "max"], "high"),
        # Nothing at or below -> take the lowest supported above.
        ("minimal", ["high", "max"], "high"),
        ("low", ["medium", "high", "max"], "medium"),
        # effort already the only option.
        ("max", ["max"], "max"),
        ("high", ["high"], "high"),
    ],
)
def test_resolve_reasoning_effort(
    effort: str | None, supported: list[str] | None, expected: str | None
) -> None:
    assert resolve_reasoning_effort(effort, supported=supported) == expected


@pytest.mark.parametrize("effort", [None, "none"])
def test_resolve_reasoning_effort_none_and_disabled_map_to_none(
    effort: str | None,
) -> None:
    """None and "none" mean send nothing and let the provider default stand.

    Sending ``effort: "none"`` is rejected by any route that reports
    ``mandatory: true`` (e.g. ``z-ai/glm-5.3``), and silently sending nothing
    is strictly safer than erroring.
    """
    assert resolve_reasoning_effort(effort, supported=["max", "high", "low"]) is None
    assert resolve_reasoning_effort(effort, supported=None) is None


def test_resolve_reasoning_effort_does_not_mutate_supported() -> None:
    supported = ["max", "high", "low"]
    original = list(supported)
    resolve_reasoning_effort("medium", supported=supported)
    assert supported == original


def test_resolve_reasoning_effort_unknown_route_gets_literal_request() -> None:
    # supported=None is the get_model codepath today: no network catalog lookup.
    assert resolve_reasoning_effort("max", supported=None) == "max"
    assert resolve_reasoning_effort("xhigh", supported=None) == "xhigh"


def test_openrouter_models_have_no_litellm_supports_reasoning_flag() -> None:
    """Prove the premise: these routes report no reasoning support from litellm.

    If any of these flips to True, the hardcoded table gained entries and the
    original gate would no longer have been the blocker -- this test documents
    that the OpenRouter routes genuinely return False today.
    """
    for model in (
        "openai/z-ai/glm-5.3",
        "openai/moonshotai/kimi-k3",
        "openai/deepseek/deepseek-v4-flash-0731",
    ):
        assert not model_supports_reasoning(model), model


@pytest.mark.parametrize(
    "model_name",
    [
        "openai/z-ai/glm-5.3",
        "openai/moonshotai/kimi-k3",
        "openai/deepseek/deepseek-v4-flash-0731",
    ],
)
def test_openrouter_openai_route_receives_max_effort_despite_litellm(model_name: str) -> None:
    """``max`` must survive to the request on an openai/-prefixed OpenRouter route
    even though ``model_supports_reasoning`` returns False for it."""
    assert not model_supports_reasoning(model_name)  # guard: premise of the fix
    settings = make_model_settings("max", model_name=model_name, request_timeout=30)
    # "max" rides as a raw body field (see _reasoning_settings); it must reach
    # the wire via extra_body, and the timeout stays in extra_args.
    assert settings.reasoning is None
    assert settings.extra_args == {"timeout": 30}
    assert settings.extra_body == {"reasoning_effort": "max"}


def test_openrouter_openai_route_receives_high_effort_as_reasoning() -> None:
    """A non-max effort lands as ``ModelSettings.reasoning`` on an OpenRouter
    route that litellm thinks is not reasoning-capable."""
    settings = make_model_settings("high", model_name="openai/z-ai/glm-5.3")
    assert settings.reasoning is not None
    assert settings.reasoning.effort == "high"


def test_openrouter_route_keeps_operator_literal_effort_when_supported() -> None:
    """resolve_reasoning_effort with a future supported catalog must not rewrite
    an effort the route already accepts."""
    assert resolve_reasoning_effort("max", supported=["max", "high", "low"]) == "max"
    assert resolve_reasoning_effort("high", supported=["max", "high", "low"]) == "high"


def test_codex_path_is_not_double_applied() -> None:
    """make_model_settings runs for every model including Codex, but the Codex
    backend already gets its effort via ``_CodexResponsesModel._codex_settings``.
    The gate must skip the subscription path so the effort is not applied twice."""
    assert codex.subscription_model("chatgpt/gpt-5")  # guard: is a subscription model
    settings = make_model_settings("max", model_name="chatgpt/gpt-5", request_timeout=30)
    assert settings.reasoning is None
    assert settings.extra_args == {"timeout": 30}


def test_reasoning_effort_survives_model_settings_json_dump() -> None:
    """ModelSettings.to_json_dict() must stay serializable when reasoning effort
    is attached, mirroring the timeout extra_args guard."""
    settings = ModelSettings(reasoning=Reasoning(effort="max"))
    dumped = settings.to_json_dict()
    assert dumped["reasoning"]["effort"] == "max"


def test_reasoning_effort_and_timeout_coexist_in_model_settings() -> None:
    """A model built for an OpenRouter route carries both the reasoning effort
    and the request timeout, and both survive to_json_dict()."""
    settings = make_model_settings("max", model_name="openai/z-ai/glm-5.3", request_timeout=30)
    dumped = settings.to_json_dict()
    assert dumped["reasoning"] is None
    assert dumped["extra_args"] == {"timeout": 30}
    assert dumped["extra_body"] == {"reasoning_effort": "max"}


def test_gate_still_requires_explicit_non_none_effort() -> None:
    """No effort configured (None or "none") sends nothing, even on an
    openai/-prefixed OpenRouter route."""
    empty = make_model_settings(None, model_name="openai/z-ai/glm-5.3")
    assert empty.reasoning is None
    zero = make_model_settings("none", model_name="openai/z-ai/glm-5.3")
    assert zero.reasoning is None


def test_non_openai_route_only_applies_effort_when_litellm_supports_it(
    monkeypatch: Any,
) -> None:
    """Routes that are not openai/-prefixed do not get the relaxation: an effort
    is applied only if the LiteLLM table still reports reasoning support."""

    # Force litellm to say "not reasoning-capable" for every model.
    monkeypatch.setattr(inputs_mod, "model_supports_reasoning", lambda _name: False)

    # A non-openai/-prefixed route must NOT get the relaxation, so no effort.
    non_openai = make_model_settings("high", model_name="anthropic/claude-sonnet-4-5")
    assert non_openai.reasoning is None

    # An openai/-prefixed route still gets its explicit effort despite the same
    # "not reasoning-capable" verdict, because the manufacturer table is wrong.
    openai_route = make_model_settings("high", model_name="openai/z-ai/glm-5.3")
    assert openai_route.reasoning is not None
    assert openai_route.reasoning.effort == "high"
