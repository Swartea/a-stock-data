#!/usr/bin/env python3
"""Local HTTP surface for the global-index daily-K research page.

Standard library only (``http.server`` + ``urllib.parse``): no third-party
runtime dependency, no provider logic in the browser, and no network listener
beyond loopback by default.

Endpoints:

* ``GET /``            — the research page (selector metadata + one API URL);
* ``GET /api/daily-k``  — the single research endpoint the page calls, which
  delegates to :func:`analysis.research.global_market_research
  .build_global_market_research`;
* ``GET /api/indices``  — selector options derived from ``list_global_indices``.

Every failure is answered as JSON with a stable ``status`` rather than a traceback
or a 500 page, so malformed dates or malformed provider rows cannot crash the
page.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

# Running this file directly puts ``scripts/`` on sys.path, not the repo root.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from analysis.research.global_indices import get_global_index
from analysis.research.global_market_research import (
    build_global_market_research,
    list_index_choices,
    list_research_markets,
)
from analysis.research.market_research_view import (
    render_global_market_research_page,
    selector_options,
)

API_PATH = "/api/daily-k"
INDICES_PATH = "/api/indices"
DEFAULT_WINDOW_DAYS = 30


def default_window(
    days: int = DEFAULT_WINDOW_DAYS,
    *,
    timezone_name: str = "Asia/Shanghai",
) -> tuple[str, str]:
    """Return a canonical window ending on today's date in the index timezone."""

    today = datetime.now(ZoneInfo(timezone_name)).date()
    return (today - timedelta(days=max(1, days))).isoformat(), today.isoformat()


def _clean(value: Any, limit: int = 64) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:limit] if trimmed else None


def build_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    """Turn a parsed query string into one research payload.

    Never raises: an unknown index, a bad date, or a provider error all come
    back as an explicit ``status`` the page can render.
    """

    index_id = _clean((query.get("index_id") or [None])[0])
    try:
        spec = get_global_index(index_id) if index_id else None
    except (KeyError, TypeError, ValueError):
        spec = None
    start_date, end_date = default_window(
        timezone_name=spec.timezone if spec is not None else "Asia/Shanghai"
    )
    requested_start = _clean((query.get("start_date") or [None])[0])
    requested_end = _clean((query.get("end_date") or [None])[0])
    if requested_start:
        start_date = requested_start
    if requested_end:
        end_date = requested_end

    if index_id is None:
        return {
            "status": "error",
            "name": "—",
            "index_id": "",
            "market": "",
            "currency": "",
            "timezone": "",
            "provider_symbol": "",
            "publisher": "",
            "local_code": "",
            "availability": "unknown",
            "freshness": "unknown",
            "data_date": None,
            "source": None,
            "provider_status": None,
            "bar_count": 0,
            "bars": [],
            "trading_day_status": "unknown",
            "start_date": start_date,
            "end_date": end_date,
            "evaluated_at": None,
            "degraded": False,
            "failure_reason": "VALIDATION: index_id is required",
            "unavailable_reason": None,
            "units": {"price": "index_points", "volume": "unavailable"},
        }

    try:
        result = build_global_market_research(index_id, start_date, end_date)
    except (TypeError, ValueError, KeyError) as exc:
        message = exc.args[0] if exc.args else str(exc)
        return {
            "status": "error",
            "name": "—",
            "index_id": index_id,
            "market": "",
            "currency": "",
            "timezone": "",
            "provider_symbol": "",
            "publisher": "",
            "local_code": "",
            "availability": "unknown",
            "freshness": "unknown",
            "data_date": None,
            "source": None,
            "provider_status": None,
            "bar_count": 0,
            "bars": [],
            "trading_day_status": "unknown",
            "start_date": start_date,
            "end_date": end_date,
            "evaluated_at": None,
            "degraded": False,
            "failure_reason": f"VALIDATION: {message}",
            "unavailable_reason": None,
            "units": {"price": "index_points", "volume": "unavailable"},
        }
    return result.as_dict()


def make_handler(research_callable: Any = None):
    """Build a request handler; ``research_callable`` enables fixture isolation."""

    service = research_callable or build_payload

    class ResearchHandler(BaseHTTPRequestHandler):
        server_version = "MarketResearch/1.0"

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                page = render_global_market_research_page()
                self._send(page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == INDICES_PATH:
                body = json.dumps(
                    {
                        "markets": list(list_research_markets()),
                        "indices": [dict(choice) for choice in list_index_choices()],
                    },
                    ensure_ascii=False,
                )
                self._send(body.encode("utf-8"), "application/json; charset=utf-8")
                return
            if parsed.path == API_PATH:
                try:
                    payload = service(parse_qs(parsed.query))
                except Exception as exc:
                    payload = {
                        "status": "error",
                        "availability": "unknown",
                        "freshness": "unknown",
                        "bars": [],
                        "bar_count": 0,
                        "trading_day_status": "unknown",
                        "failure_reason": f"research service error: {type(exc).__name__}",
                    }
                body = json.dumps(payload, ensure_ascii=False)
                self._send(body.encode("utf-8"), "application/json; charset=utf-8")
                return
            self._send(b'{"status":"error"}', "application/json; charset=utf-8", 404)

        def log_message(self, *args: Any) -> None:  # keep CLI output clean
            return

    return ResearchHandler


def serve(host: str = "127.0.0.1", port: int = 8765, research_callable: Any = None):
    """Create (but do not start) a loopback research server."""

    server = ThreadingHTTPServer((host, port), make_handler(research_callable))
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    httpd = serve(args.host, args.port)
    print(f"research page: http://{args.host}:{args.port}/  (api: {API_PATH})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
