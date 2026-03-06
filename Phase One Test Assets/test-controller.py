#!/usr/bin/env python3
"""
Test controller server for Phase 1.
Manages the WebSocket server and alignment server as subprocesses.
Provides HTTP API for start/stop/restart, status, logs, and metrics.

Port: 8098
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Config ────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
CARGO = os.environ.get("CARGO", str(Path.home() / ".cargo" / "bin" / "cargo"))
VENV_PY311 = str(PROJECT_DIR / "tts-venv" / "bin" / "python3.11")
VENV_PYTHON = VENV_PY311  # Default to 3.11 — packages installed there, not under 3.14
VENV_PY312 = str(PROJECT_DIR / "qwen-tts-venv" / "bin" / "python3.12")
NATIVE_DIR = str(PROJECT_DIR / "packages" / "native-bridge")


def _py_server(name, port, script, python=None, extra_args=None):
    """Helper to define a Python engine server."""
    py = python or VENV_PYTHON
    cmd = [py, os.path.join(NATIVE_DIR, script)]
    if extra_args:
        cmd.extend(extra_args)
    return {
        "name": name,
        "port": port,
        "cmd": cmd,
        "build_cmd": None,
        "health_url": f"http://127.0.0.1:{port}/health",
        "env": {},
    }


SERVERS = {
    "ws": {
        "name": "WebSocket Server",
        "port": 21740,
        "cmd": [str(PROJECT_DIR / "target" / "debug" / "web-vox-server")],
        "build_cmd": [
            CARGO, "build",
            "--manifest-path", str(PROJECT_DIR / "Cargo.toml"),
            "--bin", "web-vox-server",
        ],
        "health_url": None,
        "env": {"RUST_LOG": "info"},
    },
    "chatterbox":  _py_server("Chatterbox",       21741, "chatterbox_server.py"),
    "kokoro":      _py_server("Kokoro",            21742, "kokoro_server.py"),
    "coqui":       _py_server("Coqui VCTK",        21743, "coqui_server.py",
                              extra_args=["--model", "tts_models/en/vctk/vits"]),
    "qwen":        _py_server("Qwen3-TTS",         21744, "qwen_tts_server.py",
                              python=VENV_PY312 if os.path.exists(VENV_PY312) else VENV_PYTHON),
    "coqui-xtts":  _py_server("Coqui XTTS v2",     21745, "coqui_xtts_server.py",
                              extra_args=["--lazy"]),
    "qwen-clone":  _py_server("Qwen3-TTS Clone",   21746, "qwen_tts_clone_server.py",
                              python=VENV_PY312 if os.path.exists(VENV_PY312) else VENV_PYTHON,
                              extra_args=["--lazy"]),
    "alignment":   _py_server("Forced Alignment",  21747, "alignment_server.py",
                              extra_args=["--port", "21747"]),
}

# ── Managed Process ──────────────────────────────────────────

class ManagedServer:
    def __init__(self, key, config):
        self.key = key
        self.config = config
        self.process = None
        self.logs = deque(maxlen=500)
        self.start_time = None
        self._reader_thread = None
        self._lock = threading.Lock()

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def pid(self):
        return self.process.pid if self.running else None

    @property
    def uptime(self):
        if self.start_time and self.running:
            return time.time() - self.start_time
        return 0

    def start(self):
        with self._lock:
            if self.running:
                return {"ok": True, "msg": "Already running", "pid": self.pid}

            # Build if needed
            build_cmd = self.config.get("build_cmd")
            if build_cmd:
                self._log("BUILD", f"Building: {' '.join(build_cmd[-3:])}")
                try:
                    result = subprocess.run(
                        build_cmd, capture_output=True, text=True, timeout=120
                    )
                    if result.returncode != 0:
                        err = result.stderr.strip().split("\n")[-3:]
                        self._log("ERROR", f"Build failed: {'; '.join(err)}")
                        return {"ok": False, "msg": f"Build failed: {err[-1] if err else 'unknown'}"}
                    self._log("BUILD", "Build succeeded")
                except Exception as e:
                    self._log("ERROR", f"Build error: {e}")
                    return {"ok": False, "msg": str(e)}

            # Check binary exists
            binary = self.config["cmd"][0]
            if not os.path.exists(binary):
                self._log("ERROR", f"Binary not found: {binary}")
                return {"ok": False, "msg": f"Binary not found: {binary}"}

            # Start process
            env = {**os.environ, **self.config.get("env", {})}
            self._log("START", f"Starting on port {self.config['port']}...")
            try:
                self.process = subprocess.Popen(
                    self.config["cmd"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    preexec_fn=os.setsid,
                )
                self.start_time = time.time()

                # Start log reader thread
                self._reader_thread = threading.Thread(
                    target=self._read_output, daemon=True
                )
                self._reader_thread.start()

                # Wait a moment and check it's still alive
                time.sleep(1.5)
                if not self.running:
                    return {"ok": False, "msg": "Process exited immediately"}

                self._log("START", f"Running (PID {self.pid})")
                return {"ok": True, "pid": self.pid}
            except Exception as e:
                self._log("ERROR", f"Start failed: {e}")
                return {"ok": False, "msg": str(e)}

    def stop(self):
        with self._lock:
            if not self.running:
                return {"ok": True, "msg": "Already stopped"}

            pid = self.pid
            self._log("STOP", f"Stopping (PID {pid})...")
            try:
                # Kill process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    self.process.wait(timeout=3)
            except ProcessLookupError:
                pass
            except Exception as e:
                self._log("ERROR", f"Stop error: {e}")

            self.process = None
            self.start_time = None
            self._log("STOP", f"Stopped (was PID {pid})")
            return {"ok": True}

    def restart(self):
        self.stop()
        time.sleep(0.5)
        return self.start()

    def get_metrics(self):
        if not self.running:
            return {"cpu_percent": 0, "memory_mb": 0, "threads": 0}
        try:
            ps = subprocess.run(
                ["ps", "-p", str(self.pid), "-o", "%cpu,rss,nlwp", "--no-headers"],
                capture_output=True, text=True, timeout=3,
            )
            if ps.returncode != 0:
                # macOS ps doesn't support nlwp, try without
                ps = subprocess.run(
                    ["ps", "-p", str(self.pid), "-o", "%cpu,rss"],
                    capture_output=True, text=True, timeout=3,
                )
            parts = ps.stdout.strip().split()
            if len(parts) >= 2:
                return {
                    "cpu_percent": float(parts[0]),
                    "memory_mb": round(int(parts[1]) / 1024, 1),
                    "threads": int(parts[2]) if len(parts) > 2 else None,
                }
        except Exception:
            pass
        return {"cpu_percent": 0, "memory_mb": 0, "threads": None}

    def get_status(self):
        metrics = self.get_metrics() if self.running else {"cpu_percent": 0, "memory_mb": 0, "threads": None}
        return {
            "key": self.key,
            "name": self.config["name"],
            "port": self.config["port"],
            "running": self.running,
            "pid": self.pid,
            "uptime_secs": round(self.uptime, 1),
            **metrics,
        }

    def get_logs(self, last_n=200):
        return list(self.logs)[-last_n:]

    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._log("OUT", text)
        except Exception:
            pass

    def _log(self, level, msg):
        entry = {
            "time": time.time(),
            "time_str": time.strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        }
        self.logs.append(entry)


# ── Global state ─────────────────────────────────────────────

servers = {}
metrics_history = {}
_metrics_thread = None


def init_servers():
    global servers, metrics_history
    for key, cfg in SERVERS.items():
        servers[key] = ManagedServer(key, cfg)
        metrics_history[key] = deque(maxlen=120)


def metrics_collector():
    """Background thread: sample metrics every 5 seconds."""
    while True:
        for key, srv in servers.items():
            if srv.running:
                m = srv.get_metrics()
                m["time"] = time.time()
                metrics_history[key].append(m)
        time.sleep(5)


# ── HTTP Handler ─────────────────────────────────────────────

class ControllerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress default logging

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip("/")

        if path == "/status":
            data = {key: srv.get_status() for key, srv in servers.items()}
            self._json_response(data)

        elif path.startswith("/logs/"):
            key = path.split("/")[-1]
            if key in servers:
                self._json_response({"logs": servers[key].get_logs()})
            else:
                self._json_response({"error": f"Unknown server: {key}"}, 404)

        elif path == "/metrics":
            data = {}
            for key in servers:
                data[key] = {
                    "current": servers[key].get_metrics() if servers[key].running else None,
                    "history": list(metrics_history[key]),
                }
            self._json_response(data)

        elif path == "/health":
            self._json_response({"status": "ok"})

        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        path = self.path.rstrip("/")

        # /start/<key>, /stop/<key>, /restart/<key>
        parts = path.strip("/").split("/")
        if len(parts) == 2:
            action, key = parts
            if key not in servers:
                self._json_response({"error": f"Unknown server: {key}"}, 404)
                return
            if action == "start":
                result = servers[key].start()
                self._json_response(result)
            elif action == "stop":
                result = servers[key].stop()
                self._json_response(result)
            elif action == "restart":
                result = servers[key].restart()
                self._json_response(result)
            else:
                self._json_response({"error": f"Unknown action: {action}"}, 400)
        else:
            self._json_response({"error": "Bad request"}, 400)


# ── Main ─────────────────────────────────────────────────────

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8098

    init_servers()

    # Start metrics collector
    t = threading.Thread(target=metrics_collector, daemon=True)
    t.start()

    print(f"  [controller] Test controller running on http://127.0.0.1:{port}")
    print(f"  [controller] Manages: {', '.join(s['name'] for s in SERVERS.values())}")

    server = HTTPServer(("127.0.0.1", port), ControllerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [controller] Shutting down — stopping managed servers...")
        for srv in servers.values():
            srv.stop()
        server.server_close()
        print("  [controller] Done.")


if __name__ == "__main__":
    main()
