"""Tests for the local run viewer (strix.viewer) and its path helpers."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import TYPE_CHECKING

from strix.core.paths import latest_run_dir, runs_base_dir
from strix.viewer.server import serve
from strix.viewer.transcript import (
    build_run_state,
    read_report_markdown,
    read_run_summary,
    read_vulnerabilities,
)


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_run(base: Path, name: str, *, status: str, end_time: str | None) -> Path:
    run_dir = base / "strix_runs" / name
    state_dir = run_dir / ".state"
    state_dir.mkdir(parents=True)
    record = {"run_name": name, "status": status, "end_time": end_time}
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    agents = {
        "statuses": {"root": "completed", "child": "running"},
        "names": {"root": "strix", "child": "recon"},
        "parent_of": {"root": None, "child": "root"},
    }
    (state_dir / "agents.json").write_text(json.dumps(agents), encoding="utf-8")
    return run_dir


def test_latest_run_dir_none_when_no_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert latest_run_dir() is None
    assert runs_base_dir() == tmp_path / "strix_runs"


def test_latest_run_dir_picks_newest_by_record_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    older = _make_run(tmp_path, "old", status="completed", end_time="2026-01-01T00:00:00Z")
    newer = _make_run(tmp_path, "new", status="running", end_time=None)
    # Force a newer mtime on the second run's record.
    os.utime(newer / "run.json", (2_000_000_000, 2_000_000_000))
    os.utime(older / "run.json", (1_000_000_000, 1_000_000_000))
    assert latest_run_dir() == newer


def test_read_run_summary_finished_flag(tmp_path: Path) -> None:
    finished = _make_run(tmp_path, "done", status="completed", end_time="2026-01-01T00:00:00Z")
    live = _make_run(tmp_path, "live", status="running", end_time=None)
    assert read_run_summary(finished)["finished"] is True
    assert read_run_summary(live)["finished"] is False
    # A terminal status without an end_time is not "finished".
    partial = _make_run(tmp_path, "partial", status="failed", end_time=None)
    assert read_run_summary(partial)["finished"] is False


def test_read_missing_artifacts_return_defaults(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, "empty", status="running", end_time=None)
    assert read_vulnerabilities(run_dir) == []
    assert read_report_markdown(run_dir) == ""


def test_build_run_state_from_agents_json(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, "graph", status="running", end_time=None)
    state = build_run_state(run_dir)
    ids = {a["id"] for a in state["agents"]}
    assert ids == {"root", "child"}
    child = next(a for a in state["agents"] if a["id"] == "child")
    assert child["parent_id"] == "root"
    assert child["name"] == "recon"
    # No agents.db, so no message/tool events.
    assert state["events"] == []


def _get(url: str) -> tuple[int, str, bytes]:
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - localhost test server
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def test_server_serves_api_and_static(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, "served", status="completed", end_time="2026-01-01T00:00:00Z")

    assets = tmp_path / "bundle"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (assets / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr("strix.viewer.server.bundle_dir", lambda: assets)

    httpd, url = serve(run_dir, open_browser=False)
    try:
        status, ctype, body = _get(f"{url}/api/run")
        assert status == 200
        assert "application/json" in ctype
        assert json.loads(body)["finished"] is True

        status, _, body = _get(f"{url}/api/transcript")
        assert {a["id"] for a in json.loads(body)["agents"]} == {"root", "child"}

        # Real asset is served.
        status, ctype, _ = _get(f"{url}/assets/app.js")
        assert status == 200

        # Unknown non-API route falls back to index.html (SPA routing).
        status, ctype, body = _get(f"{url}/agents/root")
        assert status == 200
        assert b"<div id=root>" in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_event_endpoint_forwards_cta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, "evt", status="running", end_time=None)
    assets = tmp_path / "bundle"
    assets.mkdir()
    (assets / "index.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr("strix.viewer.server.bundle_dir", lambda: assets)

    seen: list[str] = []
    monkeypatch.setattr("strix.telemetry.posthog.viewer_cta_clicked", seen.append)

    httpd, url = serve(run_dir, open_browser=False)
    try:
        body = json.dumps({"event": "cta_clicked", "cta": "PR reviews"}).encode()
        req = urllib.request.Request(  # noqa: S310 - localhost test server
            f"{url}/api/event", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            assert resp.status == 204
        assert seen == ["PR reviews"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, "guard", status="completed", end_time="2026-01-01T00:00:00Z")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    assets = tmp_path / "bundle"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html>index", encoding="utf-8")
    monkeypatch.setattr("strix.viewer.server.bundle_dir", lambda: assets)

    httpd, url = serve(run_dir, open_browser=False)
    try:
        # A traversal target must never leak the file; it falls back to index.html.
        _, _, body = _get(f"{url}/..%2f..%2fsecret.txt")
        assert b"top secret" not in body
    finally:
        httpd.shutdown()
        httpd.server_close()
