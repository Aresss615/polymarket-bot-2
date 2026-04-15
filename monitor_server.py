import json
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from config import MONITOR_HOST, MONITOR_PORT


@dataclass
class MonitorServerHandle:
    host: str
    port: int
    server: ThreadingHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def start_monitor_server(engine, host: str = MONITOR_HOST, port: int = MONITOR_PORT) -> MonitorServerHandle:
    """Start a lightweight local HTTP server for the bot monitor."""

    root_dir = Path(__file__).resolve().parent

    class MonitorHandler(BaseHTTPRequestHandler):
        server_version = "PolymarketMonitor/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
            parsed = urlparse(self.path)
            path = parsed.path or "/"

            if path in ("/", "/ticker3.html"):
                self._serve_file(root_dir / "ticker3.html", "text/html; charset=utf-8")
                return
            if path == "/ticker3.css":
                self._serve_file(root_dir / "ticker3.css", "text/css; charset=utf-8")
                return
            if path == "/ticker3.js":
                self._serve_file(root_dir / "ticker3.js", "application/javascript; charset=utf-8")
                return
            if path == "/api/monitor":
                self._serve_json(engine.get_monitor_snapshot())
                return
            if path == "/health":
                self._serve_json({"ok": True})
                return
            if path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib signature
            return

        def _serve_json(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_file(self, path: Path, content_type: str) -> None:
            if not path.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class ReusableThreadingHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = ReusableThreadingHTTPServer((host, port), MonitorHandler)
    thread = threading.Thread(target=server.serve_forever, name="monitor-http", daemon=True)
    thread.start()
    return MonitorServerHandle(host=host, port=port, server=server, thread=thread)
