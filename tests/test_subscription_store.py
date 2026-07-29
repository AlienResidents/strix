"""Shared subscription credential store: secure writes and cross-provider locking."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

from strix.config import codex, grok, subscription_store


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_write_creates_owner_only_file(tmp_path: Path) -> None:
    path = tmp_path / ".strix" / "subscription-auth.json"
    subscription_store.write(path, {"grok": {"type": "oauth", "access": "a", "refresh": "r"}})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # No stray temp file is left behind.
    assert not path.with_suffix(".json.tmp").exists()


def test_providers_share_store_without_clobbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / ".strix" / "subscription-auth.json"
    monkeypatch.setattr(codex, "AUTH_PATH", store)
    monkeypatch.setattr(grok, "AUTH_PATH", store)

    codex.save_record({"type": "oauth", "access": "c", "refresh": "r", "account_id": "acct"})
    grok.save_record({"type": "oauth", "access": "g", "refresh": "r"})

    data = subscription_store.read(store)
    assert data["codex"]["access"] == "c"
    assert data["grok"]["access"] == "g"

    # Logging one provider out leaves the other's credential intact.
    grok.logout()
    remaining = subscription_store.read(store)
    assert "grok" not in remaining
    assert remaining["codex"]["access"] == "c"


def test_guard_is_reentrant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / ".strix" / "subscription-auth.json"
    monkeypatch.setattr(grok, "AUTH_PATH", store)
    # Persisting while already holding the guard must not deadlock — this mirrors
    # a token refresh saving its new record inside the refresh critical section.
    with subscription_store.guard(store):
        grok.save_record({"type": "oauth", "access": "g", "refresh": "r"})
    record = grok.read_record()
    assert record is not None
    assert record["access"] == "g"
