"""Local web service for the two-photon polarization explorer, powered by qtools.tomo.bell."""

from __future__ import annotations

import importlib
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

try:
    import qtools.tomo.bell as bell_module
except ImportError:
    import bell as bell_module  # type: ignore[no-redef]

BASE_DIR = Path(__file__).resolve().parent


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "PolarizationExplorer/2.0 (QuTiP Bell Engine)"
    sys_version = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._send_json(200, {"status": "ok", "backend": "qutip-bell"})
            return
        if path not in ("/", "/index.html"):
            self._send_json(404, {"detail": "Not found"})
            return
        page = (BASE_DIR / "index.html").read_bytes()
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/calculate":
            self._send_json(404, {"detail": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("invalid request body length")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")

            # Reload module during development for live code changes
            global bell_module
            bell_module = importlib.reload(bell_module)
            result = bell_module.calculate(payload)
        except (TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            self._send_json(422, {"detail": str(exc)})
            return
        except Exception as exc:
            self._send_json(500, {"detail": f"Internal server error: {exc}"})
            return
        self._send_json(200, result)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    address = (host, port)
    server = ThreadingHTTPServer(address, RequestHandler)
    url = f"http://{address[0]}:{address[1]}"
    print(f"Polarization explorer ready at {url} (powered by QuTiP bell engine)")
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping polarization explorer")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
