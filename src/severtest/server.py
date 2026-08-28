from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "cases"
REPORTS = ROOT / "reports"
RUNS: dict[str, dict[str, Any]] = {}


def start_run(case: str, env: dict[str, str]) -> str:
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"id": run_id, "case": case, "status": "queued"}

    def worker() -> None:
        RUNS[run_id]["status"] = "running"
        command = ["bash", "scripts/run_local_smoke.sh"]
        process_env = os.environ.copy()
        process_env.update(env)
        process_env["CASE_FILE"] = f"/cases/{case}"
        result = subprocess.run(command, cwd=ROOT, env=process_env, capture_output=True, text=True)
        RUNS[run_id].update({"status": "passed" if result.returncode == 0 else "failed", "exit_code": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]})

    threading.Thread(target=worker, daemon=True).start()
    return run_id


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            return self.send_json(200, {"status": "ok"})
        if self.path == "/cases":
            cases = []
            for path in sorted(CASES.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    cases.append({"id": data.get("id", path.stem), "name": data.get("name", path.stem), "file": path.name})
                except (OSError, ValueError):
                    continue
            return self.send_json(200, {"cases": cases})
        if self.path == "/runs":
            return self.send_json(200, {"runs": list(RUNS.values())[-50:]})
        if self.path.startswith("/runs/"):
            run = RUNS.get(self.path.removeprefix("/runs/"))
            return self.send_json(200 if run else 404, run or {"error": "run not found"})
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/runs":
            return self.send_json(404, {"error": "not found"})
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            env = {key: str(payload[key]) for key in ("UID_VALUE", "GATE_HOST", "GATE_PORT") if key in payload}
            requested = payload.get("cases", payload.get("case"))
            if isinstance(requested, str):
                requested = [requested]
            if not isinstance(requested, list) or not requested:
                raise ValueError("case or cases is required")
            run_ids = []
            for item in requested:
                case = str(item)
                if not (CASES / case).is_file() or Path(case).name != case:
                    raise ValueError(f"unknown case: {case}")
                run_ids.append(start_run(case, env))
            return self.send_json(202, {"run_ids": run_ids})
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})


def main() -> None:
    port = int(os.getenv("SEVERTEST_API_PORT", "8088"))
    print(f"severtest API listening on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
