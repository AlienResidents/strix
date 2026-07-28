"""Shared helpers across model-subscription providers (ChatGPT/Codex and Grok).

Each provider module (:mod:`strix.config.codex`, :mod:`strix.config.grok`)
exposes the same small surface — ``subscription_model``, ``auth_mode``,
``is_authenticated`` — so callers that only care "is this run on a subscription,
and which provider?" can stay provider-agnostic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from strix.config import codex, grok


if TYPE_CHECKING:
    from types import ModuleType


_PROVIDERS: tuple[ModuleType, ...] = (codex, grok)


def provider_for_model(model_name: str | None) -> ModuleType | None:
    """Return the subscription provider module that owns ``model_name``'s prefix,
    or None when the model isn't a subscription model."""
    for provider in _PROVIDERS:
        if provider.subscription_model(model_name):
            return provider
    return None


def auth_mode(model_name: str | None) -> str:
    return "subscription" if provider_for_model(model_name) is not None else "api_key"
