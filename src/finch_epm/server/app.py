"""Local web server for dashboard rendering.

Uses Python's built-in http.server -- zero external dependencies.
Serves a single-page dashboard app that fetches data via JSON API endpoints.
"""

from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from finch_epm.cache.base import CacheEngine
from finch_epm.dashboard.fdash import load_fdash
from finch_epm.dashboard.models import DashboardSpec
from finch_epm.dashboard.resolver import resolve_queries

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATE_DIR = Path(__file__).parent / "templates"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard serving."""

    server: DashboardHTTPServer

    def do_GET(self) -> None:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)
        # Flatten single-value params
        params = {k: v[0] if len(v) == 1 else v for k, v in query_params.items()}

        if path == "/" or path == "":
            self._serve_template("dashboard.html")
        elif path == "/api/dashboard":
            self._serve_dashboard_spec()
        elif path.startswith("/api/query/"):
            query_name = path[len("/api/query/"):]
            self._serve_query(query_name, params)
        elif path.startswith("/api/export/"):
            query_name = path[len("/api/export/"):]
            self._serve_export(query_name)
        elif path.startswith("/api/filter/"):
            filter_name = path[len("/api/filter/"):]
            self._serve_filter_options(filter_name)
        elif path == "/api/staleness":
            self._serve_staleness()
        elif path.startswith("/static/"):
            filename = path[len("/static/"):]
            self._serve_static(filename)
        else:
            self._send_error(404, "Not found")

    def _serve_template(self, name: str) -> None:
        template_path = _TEMPLATE_DIR / name
        if not template_path.exists():
            self._send_error(404, f"Template not found: {name}")
            return
        content = template_path.read_bytes()
        self._send_response(200, content, "text/html; charset=utf-8")

    def _serve_static(self, filename: str) -> None:
        # Prevent directory traversal
        safe_name = Path(filename).name
        file_path = _STATIC_DIR / safe_name
        if not file_path.exists():
            self._send_error(404, f"Static file not found: {safe_name}")
            return
        suffix = file_path.suffix
        content_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")
        content = file_path.read_bytes()
        self._send_response(200, content, content_type)

    def _serve_dashboard_spec(self) -> None:
        spec = self.server.dashboard_spec
        data = {
            "name": spec.name,
            "description": spec.description,
            "sources": spec.sources,
            "queries": [
                {"name": q.name, "sql": q.sql, "source": q.source}
                for q in spec.queries
            ],
            "parameters": {
                name: {
                    "name": p.name,
                    "type": p.type,
                    "default": p.default,
                    "label": p.label,
                }
                for name, p in spec.parameters.items()
            },
            "filters": [
                {
                    "name": f.name,
                    "label": f.label,
                    "parameter": f.parameter,
                    "default": f.default,
                    "multi": f.multi,
                }
                for f in spec.filters
            ],
            "charts": [
                {
                    "type": c.type,
                    "title": c.title,
                    "data": c.data,
                    "cross_filter": c.cross_filter,
                    **c.config,
                }
                for c in spec.charts
            ],
        }
        self._send_json(data)

    def _serve_query(self, query_name: str, params: dict | None = None) -> None:
        spec = self.server.dashboard_spec
        cache = self.server.cache

        query = spec.get_query(query_name)
        if query is None:
            self._send_error(404, f"Query not found: {query_name}")
            return

        try:
            # Pass URL query params as parameter overrides
            results = resolve_queries(spec, cache, parameter_overrides=params)
            result = results.get(query_name)
            if result is None:
                self._send_error(500, f"Query execution returned no result: {query_name}")
                return

            data = {
                "query_name": query_name,
                "column_names": result.column_names,
                "column_types": result.column_types,
                "rows": result.rows,
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
                "staleness": {
                    "level": result.staleness.level.value,
                    "last_synced_at": (
                        result.staleness.last_synced_at.isoformat()
                        if result.staleness.last_synced_at
                        else None
                    ),
                },
                "served_from": result.served_from,
            }
            self._send_json(data)
        except Exception as e:
            logger.exception("Query execution failed: %s", query_name)
            self._send_error(500, f"Query failed: {e}")

    def _serve_filter_options(self, filter_name: str) -> None:
        """Execute a filter's query and return the dropdown options."""
        spec = self.server.dashboard_spec
        cache = self.server.cache

        filter_spec = None
        for f in spec.filters:
            if f.name == filter_name:
                filter_spec = f
                break

        if filter_spec is None:
            self._send_error(404, f"Filter not found: {filter_name}")
            return

        try:
            from finch_epm.cache.models import QueryRequest
            result = cache.execute_query(QueryRequest(sql=filter_spec.query))
            options = []
            for row in result.rows:
                value = row[0]
                label = row[1] if len(row) > 1 else row[0]
                options.append({"value": value, "label": label})

            self._send_json({
                "name": filter_name,
                "label": filter_spec.label,
                "parameter": filter_spec.parameter,
                "default": filter_spec.default,
                "multi": filter_spec.multi,
                "options": options,
            })
        except Exception as e:
            logger.exception("Filter query failed: %s", filter_name)
            self._send_error(500, f"Filter query failed: {e}")

    def _serve_export(self, query_name: str) -> None:
        """Export query results as CSV for download."""
        import csv
        import io

        spec = self.server.dashboard_spec
        cache = self.server.cache

        query = spec.get_query(query_name)
        if query is None:
            self._send_error(404, f"Query not found: {query_name}")
            return

        try:
            results = resolve_queries(spec, cache)
            result = results.get(query_name)
            if result is None or not result.rows:
                self._send_error(404, "No data to export")
                return

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(result.column_names)
            for row in result.rows:
                writer.writerow(row)

            content = output.getvalue().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{query_name}.csv"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.exception("Export failed: %s", query_name)
            self._send_error(500, f"Export failed: {e}")

    def _serve_staleness(self) -> None:
        # Placeholder -- return basic staleness info
        self._send_json({"status": "ok"})

    def _send_json(self, data: Any) -> None:
        content = json.dumps(data, default=str).encode("utf-8")
        self._send_response(200, content, "application/json; charset=utf-8")

    def _send_response(self, code: int, content: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _send_error(self, code: int, message: str) -> None:
        content = json.dumps({"error": message}).encode("utf-8")
        self._send_response(code, content, "application/json; charset=utf-8")

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default access logging to stderr
        logger.debug(format, *args)


class DashboardHTTPServer(HTTPServer):
    """HTTP server with dashboard context."""

    def __init__(
        self,
        address: tuple[str, int],
        dashboard_spec: DashboardSpec,
        cache: CacheEngine,
    ) -> None:
        self.dashboard_spec = dashboard_spec
        self.cache = cache
        super().__init__(address, DashboardHandler)


class DashboardServer:
    """High-level dashboard server that wraps the HTTP server.

    Usage::

        server = DashboardServer("path/to/dashboard.fdash", cache)
        server.start(port=8765, open_browser=True)
        # Blocks until Ctrl+C
    """

    def __init__(
        self,
        fdash_path: str | Path,
        cache: CacheEngine,
    ) -> None:
        self.fdash_path = Path(fdash_path)
        self.cache = cache
        self.spec = load_fdash(self.fdash_path)
        self._httpd: DashboardHTTPServer | None = None

    def start(self, port: int = 8765, open_browser: bool = True) -> None:
        """Start the server and optionally open a browser.

        Blocks until the server is stopped (Ctrl+C or stop()).
        """
        self._httpd = DashboardHTTPServer(
            ("127.0.0.1", port), self.spec, self.cache
        )

        url = f"http://127.0.0.1:{port}"
        print(f"Serving dashboard: {self.spec.name}")
        print(f"URL: {url}")
        print("Press Ctrl+C to stop.")

        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()

        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server.")
        finally:
            self._httpd.server_close()

    def stop(self) -> None:
        """Stop the server from another thread."""
        if self._httpd:
            self._httpd.shutdown()
