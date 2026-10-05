"""Local web service for polarization entanglement and quantum state tomography.

Powered by QuTiP (Bell engine) and UIUC KwiatLab (Tomography MLE engine).
"""

from __future__ import annotations

import importlib
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import qtools.tomo.bell as bell_module
except ImportError:
    import bell as bell_module  # type: ignore[no-redef]

try:
    import qtools.tomo.tomography.interface as tomo_interface
except ImportError:
    try:
        from tomography import interface as tomo_interface  # type: ignore[no-redef]
    except ImportError:
        tomo_interface = None  # type: ignore[assignment]


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "PolarizationExplorer/2.1 (QuTiP Bell & Kwiat QST Engines)"
    sys_version = ""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, payload: dict) -> None:
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        url_parts = urlsplit(self.path)
        path = url_parts.path

        if path == "/health":
            self._send_json(200, {
                "status": "ok",
                "backend": "qutip-bell",
                "tomography": "available" if tomo_interface is not None else "unavailable",
            })
            return

        # Tomography API endpoints
        if path == "/api/tomography/presets":
            if tomo_interface is None:
                self._send_json(503, {"detail": "Tomography module not available"})
                return
            self._send_json(200, {"presets": tomo_interface.list_presets()})
            return

        if path == "/api/tomography/preset":
            if tomo_interface is None:
                self._send_json(503, {"detail": "Tomography module not available"})
                return
            query = parse_qs(url_parts.query)
            preset_id = query.get("id", ["bell_state_example"])[0]
            try:
                preset_data = tomo_interface.load_preset(preset_id)
                self._send_json(200, preset_data)
            except Exception as exc:
                self._send_json(404, {"detail": str(exc)})
        if path == "/api/tomography/template":
            if tomo_interface is None:
                self._send_json(503, {"detail": "Tomography module not available"})
                return
            query = parse_qs(url_parts.query)
            n_qubits = int(query.get("n_qubits", ["2"])[0])
            template_type = query.get("type", ["canonical_36"])[0]
            n_detectors = int(query.get("n_detectors", ["1"])[0])
            template = tomo_interface.get_template(n_qubits=n_qubits, template_type=template_type, n_detectors=n_detectors)
            self._send_json(200, template)
            return

        if path not in ("/", "/index.html"):
            self._send_json(404, {"detail": "Not found"})
            return

        page = (BASE_DIR / "index.html").read_bytes()
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in ("/api/calculate", "/api/tomography/run", "/api/tomography/simulate", "/api/tomography/upload"):
            self._send_json(404, {"detail": "Not found"})
            return

        global bell_module, tomo_interface
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000_000:
                raise ValueError("invalid request body length")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")

            # Route 1: Bell explorer calculation
            if path == "/api/calculate":
                bell_module = importlib.reload(bell_module)
                result = bell_module.calculate(payload)
                self._send_json(200, result)
                return

            # Route 2: Tomography reconstruction (MLE)
            if path == "/api/tomography/run":
                if tomo_interface is None:
                    raise RuntimeError("Tomography interface is not installed")
                tomo_interface = importlib.reload(tomo_interface)
                if "n_qubits" in payload:
                    data = payload
                    config = payload.get("config", {})
                else:
                    data = payload.get("data")
                    config = payload.get("config")
                target_state = payload.get("target_state")
                preset_id = payload.get("preset_id")
                result = tomo_interface.run_tomography(
                    config=config,
                    data=data,
                    target_state=target_state,
                    preset_id=preset_id,
                )
                self._send_json(200, result)
                return

            # Route 3: Simulate tomography measurements from a theoretical Bell state
            if path == "/api/tomography/simulate":
                if tomo_interface is None:
                    raise RuntimeError("Tomography interface is not installed")
                tomo_interface = importlib.reload(tomo_interface)
                result = tomo_interface.simulate_counts_from_bell_state(
                    amplitudes=payload.get("amplitudes", {}),
                    state_basis=payload.get("state_basis", "linear"),
                    total_pairs=int(payload.get("total_pairs", 1000)),
                    noise_ratio=float(payload.get("noise_ratio", 0.0)),
                )
                self._send_json(200, result)
                return

            # Route 4: Parse uploaded tomography file (.json, .toml, .txt)
            if path == "/api/tomography/upload":
                if tomo_interface is None:
                    raise RuntimeError("Tomography interface is not installed")
                tomo_interface = importlib.reload(tomo_interface)
                content = payload.get("content", "")
                filename = payload.get("filename", "upload.txt")
                result = tomo_interface.parse_tomo_file(content, filename)
                self._send_json(200, result)
                return

        except (TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            self._send_json(422, {"detail": str(exc)})
            return
        except Exception as exc:
            self._send_json(500, {"detail": f"Internal server error: {exc}"})
            return

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run_server(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> None:
    address = (host, port)
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(address, RequestHandler)
    url = f"http://{address[0]}:{address[1]}"
    print(f"Polarization & Tomography server ready at {url} (QuTiP & Kwiat QST engines)")
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
