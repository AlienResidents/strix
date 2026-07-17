"""Local HTTP server that serves the viewer SPA and a run's data from disk.

Design notes:
- Uses only the standard library (no new runtime dependency). The workload is
  serving static files plus a handful of JSON reads off disk, so an async stack
  buys nothing here.
- The browser polls the JSON endpoints (~1s) rather than using SSE: a finished
  run stops polling, and short-lived polls survive sleep/network blips without
  server-side connection state, which suits a stdlib ThreadingHTTPServer.
- All reads happen per-request straight from disk, so the same server serves a
  live in-progress run and a finished one identically; the SPA distinguishes
  them via the ``finished`` flag on /api/run.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from strix.viewer.transcript import (
    build_run_state,
    read_report_markdown,
    read_run_summary,
    read_vulnerabilities,
)


logger = logging.getLogger(__name__)


def bundle_dir() -> Path:
    """Directory holding the committed, prebuilt SPA (index.html + assets)."""
    return Path(__file__).resolve().parent / "viewer_dist"


def bundle_is_built() -> bool:
    return (bundle_dir() / "index.html").is_file()


class _ViewerState:
    def __init__(self, run_dir: Path, assets_dir: Path) -> None:
        self.run_dir = run_dir
        self.assets_dir = assets_dir


def _make_handler(state: _ViewerState) -> type[BaseHTTPRequestHandler]:
    class ViewerHandler(BaseHTTPRequestHandler):
        server_version = "StrixViewer/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug("viewer %s - %s", self.address_string(), format % args)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path.startswith("/api/"):
                    self._handle_api(path)
                else:
                    self._handle_static(path)
            except BrokenPipeError:
                # The browser closed the connection mid-response (e.g. it
                # navigated away between polls). Not an error.
                logger.debug("viewer client disconnected during %s", path)
            except Exception:
                # A bad request must never kill the worker thread.
                logger.exception("viewer request failed: %s", path)
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            try:
                if path == "/api/event":
                    self._handle_event()
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
            except BrokenPipeError:
                logger.debug("viewer client disconnected during POST %s", path)
            except Exception:
                # A bad request must never kill the worker thread.
                logger.exception("viewer request failed: POST %s", path)
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})

        def _handle_event(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                body = {}
            # Only the viewer's own sign-up/upsell CTA click is forwarded, as an
            # anonymous PostHog event that respects the global telemetry opt-out.
            if isinstance(body, dict) and body.get("event") == "cta_clicked":
                cta = str(body.get("cta") or "unknown")
                from strix.telemetry import posthog  # noqa: PLC0415

                posthog.viewer_cta_clicked(cta)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()

        def _handle_api(self, path: str) -> None:
            run_dir = state.run_dir
            if path == "/api/run":
                self._send_json(HTTPStatus.OK, read_run_summary(run_dir))
            elif path == "/api/vulnerabilities":
                self._send_json(HTTPStatus.OK, read_vulnerabilities(run_dir))
            elif path == "/api/report":
                self._send_json(HTTPStatus.OK, {"markdown": read_report_markdown(run_dir)})
            elif path == "/api/transcript":
                self._send_json(HTTPStatus.OK, build_run_state(run_dir))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

        def _handle_static(self, path: str) -> None:
            target = self._resolve_asset(path)
            if target is None:
                # SPA fallback: unknown non-asset routes render index.html so
                # client-side deep links work.
                target = state.assets_dir / "index.html"
            if not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            content = target.read_bytes()
            content_type, _ = mimetypes.guess_type(str(target))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _resolve_asset(self, path: str) -> Path | None:
            rel = unquote(path).lstrip("/")
            if not rel or rel.endswith("/"):
                return None
            root = state.assets_dir.resolve()
            candidate = (root / rel).resolve()
            # Path-traversal guard: never serve outside the bundle root.
            if root != candidate and root not in candidate.parents:
                logger.warning("viewer rejected traversal attempt: %s", path)
                return None
            return candidate if candidate.is_file() else None

        def _send_json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ViewerHandler


def serve(
    run_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> tuple[ThreadingHTTPServer, str]:
    """Start the viewer server on a background thread and return (server, url).

    Binds an ephemeral port by default. If a fixed ``port`` is requested but in
    use, falls back to an ephemeral port. Reused by both the ``strix view``
    command and the in-TUI launcher; callers own the server's lifetime.
    """
    assets_dir = bundle_dir()
    state = _ViewerState(run_dir=run_dir, assets_dir=assets_dir)
    handler = _make_handler(state)

    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError:
        if port == 0:
            raise
        logger.info("viewer port %s unavailable, falling back to an ephemeral port", port)
        httpd = ThreadingHTTPServer((host, 0), handler)

    httpd.daemon_threads = True
    bound_port = int(httpd.server_address[1])
    url = f"http://{host}:{bound_port}"

    thread = threading.Thread(target=httpd.serve_forever, name="strix-viewer", daemon=True)
    thread.start()

    if open_browser:
        _open_browser(url)

    return httpd, url


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - launching the browser is best-effort
        logger.debug("could not open browser for %s", url, exc_info=True)


__all__ = ["bundle_dir", "bundle_is_built", "serve"]
