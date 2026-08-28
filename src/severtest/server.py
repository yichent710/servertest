from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "cases"
REPORTS = ROOT / "reports"
RUNS: dict[str, dict[str, Any]] = {}


def diagnose(report: dict[str, Any] | None, exit_code: int) -> dict[str, Any]:
    if not report:
        return {"title": "测试执行异常", "stage": "执行器", "cause": "没有生成结构化报告", "developer_hint": "检查客户端是否启动、报告目录挂载和进程退出日志。"}
    failed_assertions = [item for item in report.get("assertions", []) if not item.get("passed")]
    failed_event = next((item for item in reversed(report.get("events", [])) if item.get("status") == "FAILED"), None)
    if failed_assertions:
        names = "、".join(item.get("name", item.get("metric", "未知断言")) for item in failed_assertions)
        return {"title": "业务结果不符合预期", "stage": "结果断言", "cause": f"失败断言：{names}", "developer_hint": "对照实际值与期望值，检查需求口径、活动配置、Actor 状态更新和响应字段计算。"}
    if failed_event:
        error = str(failed_event.get("details", {}).get("error", "未知错误"))
        if "load initial actor" in error:
            return {"title": "Actor 加载失败", "stage": "加载玩家数据", "cause": error, "developer_hint": "检查 UID、Gate→Garden RPC、Redis Stream 消费组及 Actor 加载日志。"}
        if "websocket.Dial" in error:
            return {"title": "无法连接 Gate", "stage": "建立连接", "cause": error, "developer_hint": "检查宿主机端口映射、/ws 路径、Gate 容器状态和网络可达性。"}
        return {"title": "测试步骤执行失败", "stage": failed_event.get("step", "未知步骤"), "cause": error, "developer_hint": report.get("failure_analysis", "根据失败时间检查 Garden 对应请求日志。")}
    if exit_code == 0:
        return {"title": "测试通过", "stage": "全部步骤", "cause": "所有步骤和断言均通过", "developer_hint": "无需处理。"}
    return {"title": "测试进程异常退出", "stage": "执行器", "cause": f"退出码 {exit_code}", "developer_hint": "检查客户端日志和 Docker 运行环境。"}


def load_generated_report(stdout: str) -> tuple[str | None, dict[str, Any] | None]:
    match = re.search(r"evidence=(.+)", stdout)
    if not match:
        return None, None
    path = Path(match.group(1).strip()) / "milestone-v2-smoke.json"
    try:
        return str(path), json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return str(path), None


def start_run(case: str, env: dict[str, str]) -> str:
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"id": run_id, "case": case, "status": "queued", "created_at": datetime.now(timezone.utc).isoformat()}

    def worker() -> None:
        RUNS[run_id]["status"] = "running"
        command = ["bash", "scripts/run_local_smoke.sh"]
        process_env = os.environ.copy()
        process_env.update(env)
        process_env["CASE_FILE"] = f"/cases/{case}"
        result = subprocess.run(command, cwd=ROOT, env=process_env, capture_output=True, text=True)
        report_path, report = load_generated_report(result.stdout)
        RUNS[run_id].update({"status": "passed" if result.returncode == 0 else "failed", "exit_code": result.returncode, "finished_at": datetime.now(timezone.utc).isoformat(), "report_path": report_path, "report": report, "diagnosis": diagnose(report, result.returncode), "logs": {"client": result.stdout[-4000:], "error": result.stderr[-4000:]}})

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
