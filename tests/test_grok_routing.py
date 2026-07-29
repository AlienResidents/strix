"""Grok subscription routing through StrixProvider.get_model."""

from __future__ import annotations

from unittest import mock

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from strix.config import grok, subscription
from strix.config.models import StrixProvider
from strix.interface import utils
from strix.report import state as state_mod


def test_grok_prefix_routes_to_chat_completions(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = mock.MagicMock()
    monkeypatch.setattr(grok, "get_subscription_client", lambda: client)

    model = StrixProvider().get_model("grok/grok-4")

    assert isinstance(model, OpenAIChatCompletionsModel)
    # The provider strips the grok/ prefix and passes xAI's bare model slug.
    assert model.model == "grok-4"


def test_non_subscription_model_is_not_hijacked_by_grok(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def _boom() -> object:
        msg = "grok client must not be built for a non-grok model"
        raise AssertionError(msg)

    monkeypatch.setattr(grok, "get_subscription_client", _boom)

    # A metered xai/* key model must fall through to the normal provider path,
    # not the subscription route.
    model = StrixProvider().get_model("xai/grok-4")
    assert not (isinstance(model, OpenAIChatCompletionsModel) and model.model == "grok-4")


def test_provider_label_names_the_subscription() -> None:
    assert subscription.provider_label("grok/grok-4") == "Grok"
    assert subscription.provider_label("chatgpt/gpt-5.4") == "ChatGPT"
    # Metered API-key models are not subscriptions.
    assert subscription.provider_label("xai/grok-4") is None
    assert subscription.provider_label("openai/gpt-5.4") is None


def test_run_record_reports_grok_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = mock.MagicMock()
    settings.llm.model = "grok/grok-4"
    monkeypatch.setattr(state_mod, "load_settings", lambda: settings)

    record = state_mod.ReportState(run_name="run-test").run_record
    assert record["auth_mode"] == "subscription"
    assert record["subscription_provider"] == "Grok"


def test_subscription_label_prefers_persisted_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = mock.MagicMock()
    settings.llm.model = "chatgpt/gpt-5.4"  # current settings point at ChatGPT
    monkeypatch.setattr(utils, "load_settings", lambda: settings)

    # A resumed Grok run keeps its persisted provider even though settings changed.
    resumed = mock.MagicMock(
        run_record={"auth_mode": "subscription", "subscription_provider": "Grok"}
    )
    assert utils._subscription_label(resumed) == "Grok subscription"

    # With no persisted provider, it derives the label from settings (not a
    # hardcoded default).
    fresh = mock.MagicMock(run_record={})
    assert utils._subscription_label(fresh) == "ChatGPT subscription"
