"""Tests for scan telemetry emission."""

from __future__ import annotations

from typing import Any

import pytest

from strix.report.state import ReportState
from strix.telemetry import posthog, scarf


@pytest.mark.parametrize(
    ("backend", "sent_attribute"),
    [
        (posthog, "posthog_scan_ended_sent"),
        (scarf, "scarf_scan_ended_sent"),
    ],
)
def test_scan_ended_is_sent_once_per_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: Any,
    sent_attribute: str,
) -> None:
    state = ReportState(run_name="test-run")
    sent_events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        backend,
        "_send",
        lambda event, properties: sent_events.append((event, properties)),
    )

    backend.end(state, exit_reason="finished_by_tool")
    backend.end(state, exit_reason="user_exit")

    assert getattr(state, sent_attribute) is True
    assert len(sent_events) == 1
    assert sent_events[0][0] == "scan_ended"
    assert sent_events[0][1]["exit_reason"] == "finished_by_tool"
