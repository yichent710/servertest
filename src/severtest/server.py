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
from urllib.parse import unquote

from .ai_worker import CodexStructuredRunner, RequirementAIWorker
from .workflow import WorkflowError, WorkflowStore

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "cases"
REPORTS = ROOT / "reports"
WEB_INDEX = ROOT / "web" / "index.html"
WEB_ASSETS = {"/styles.css": (ROOT / "web" / "styles.css", "text/css; charset=utf-8"), "/app.js": (ROOT / "web" / "app.js", "text/javascript; charset=utf-8")}
REQUIREMENTS = ROOT / "requirements"
WORKFLOWS = WorkflowStore(REQUIREMENTS / ".workflows")
AI_ENABLED = os.getenv("SEVERTEST_AI_ENABLED", "1") == "1"
AI_WORKER = RequirementAIWorker(WORKFLOWS, CodexStructuredRunner(ROOT), ROOT, ROOT.parent / "sunnyisland")
MAX_REQUIREMENT_SIZE = 20 * 1024 * 1024
ALLOWED_REQUIREMENT_SUFFIXES = {".md", ".txt", ".pdf", ".doc", ".docx"}
RUNS: dict[str, dict[str, Any]] = {}
RUN_ENV_KEYS = (
    "UID_VALUE",
    "GATE_HOST",
    "GATE_PORT",
    "NETWORK",
    "REDIS_CONTAINER",
    "GARDEN_CONTAINER",
    "BUILD",
    "PREPARE_SID",
)


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


def load_cases() -> list[dict[str, Any]]:
    cases = []
    for path in sorted(CASES.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        review = data.get("review", {})
        cases.append(
            {
                "id": data.get("id", path.stem),
                "name": data.get("name", path.stem),
                "module": data.get("module", "未分类模块"),
                "feature": data.get("feature", "未分类功能"),
                "file": path.name,
                "activity_id": data.get("activity_id"),
                "review_status": review.get("status", "draft"),
                "review_iteration": review.get("iteration", 0),
                "step_count": len(data.get("steps", [])),
                "assertion_count": len(data.get("assertions", [])),
            }
        )
    return cases


def run_summary() -> dict[str, int]:
    totals = {"total": len(RUNS), "queued": 0, "running": 0, "passed": 0, "failed": 0}
    for run in RUNS.values():
        status = run.get("status")
        if status in totals:
            totals[status] += 1
    return totals


def validate_requirement_name(name: str) -> str:
    normalized = Path(name).name.strip()
    if not normalized or normalized in {".", ".."} or normalized != name.strip():
        raise ValueError("invalid requirement filename")
    if Path(normalized).suffix.lower() not in ALLOWED_REQUIREMENT_SUFFIXES:
        raise ValueError("requirement must be md, txt, pdf, doc, or docx")
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("invalid requirement filename")
    return normalized


def list_requirements() -> list[dict[str, Any]]:
    documents = [
        {
            "id": item["id"],
            "name": item["filename"],
            "size": item["size"],
            "uploaded_at": item["created_at"],
            "status": item["status"],
            "status_label": item["status_label"],
            "stage_started_at": item["stage_started_at"],
            "current_stage_duration_ms": item["current_stage_duration_ms"],
        }
        for item in WORKFLOWS.list()
    ]
    managed_paths = {item["source_path"] for item in WORKFLOWS.list()}
    if not REQUIREMENTS.exists():
        return documents
    for path in REQUIREMENTS.iterdir():
        if not path.is_file() or path.name.startswith(".") or str(path) in managed_paths:
            continue
        stat = path.stat()
        documents.append({"id": None, "name": path.name, "size": stat.st_size, "uploaded_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "status": "uploaded", "status_label": "需求文档已上传", "stage_started_at": None, "current_stage_duration_ms": None})
    return sorted(documents, key=lambda item: item["uploaded_at"], reverse=True)


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
    def send_file(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Filename")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            try:
                return self.send_file(200, WEB_INDEX.read_bytes(), "text/html; charset=utf-8")
            except OSError:
                return self.send_file(500, b"SeverTest web console is unavailable", "text/plain; charset=utf-8")
        if self.path in WEB_ASSETS:
            path, content_type = WEB_ASSETS[self.path]
            try:
                return self.send_file(200, path.read_bytes(), content_type)
            except OSError:
                return self.send_json(404, {"error": "asset not found"})
        if self.path == "/health":
            return self.send_json(200, {"status": "ok", "ai_worker_enabled": AI_ENABLED})
        if self.path == "/summary":
            cases = load_cases()
            return self.send_json(200, {"requirements": {"total": len(list_requirements())}, "cases": {"total": len(cases), "approved": sum(item["review_status"] == "approved" for item in cases), "pending_review": sum(item["review_status"] != "approved" for item in cases)}, "runs": run_summary()})
        if self.path == "/requirements":
            return self.send_json(200, {"requirements": list_requirements()})
        if self.path.startswith("/requirements/"):
            workflow_id = self.path.removeprefix("/requirements/")
            try:
                return self.send_json(200, WORKFLOWS.get(workflow_id))
            except WorkflowError as exc:
                return self.send_json(404, {"error": str(exc)})
        if self.path == "/cases":
            return self.send_json(200, {"cases": load_cases()})
        if self.path.startswith("/cases/"):
            name = self.path.removeprefix("/cases/")
            path = CASES / name
            if Path(name).name != name or not path.is_file():
                return self.send_json(404, {"error": "case not found"})
            try:
                return self.send_json(200, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return self.send_json(500, {"error": "case cannot be read"})
        if self.path == "/runs":
            runs = sorted(RUNS.values(), key=lambda item: item["created_at"], reverse=True)
            return self.send_json(200, {"runs": runs[:50]})
        if self.path.startswith("/runs/"):
            run = RUNS.get(self.path.removeprefix("/runs/"))
            return self.send_json(200 if run else 404, run or {"error": "run not found"})
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/requirements":
            try:
                name = validate_requirement_name(unquote(self.headers.get("X-Filename", "")))
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    raise ValueError("requirement file is empty")
                if length > MAX_REQUIREMENT_SIZE:
                    raise ValueError("requirement file exceeds 20 MB")
                content = self.rfile.read(length)
                if len(content) != length:
                    raise ValueError("requirement upload is incomplete")
                REQUIREMENTS.mkdir(parents=True, exist_ok=True)
                target = REQUIREMENTS / name
                if target.exists():
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    target = target.with_name(f"{target.stem}-{stamp}{target.suffix}")
                target.write_bytes(content)
                workflow = WORKFLOWS.create(target.name, str(target), len(content))
                if AI_ENABLED:
                    AI_WORKER.start(workflow["id"])
                return self.send_json(201, workflow)
            except (OSError, ValueError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if self.path.startswith("/requirements/") and self.path.endswith("/analyze"):
            workflow_id = self.path.removeprefix("/requirements/").removesuffix("/analyze").rstrip("/")
            try:
                WORKFLOWS.get(workflow_id)
                started = AI_WORKER.start(workflow_id)
                return self.send_json(202, {"id": workflow_id, "started": started})
            except WorkflowError as exc:
                return self.send_json(404, {"error": str(exc)})
        if self.path.startswith("/requirements/") and self.path.endswith("/events"):
            workflow_id = self.path.removeprefix("/requirements/").removesuffix("/events").rstrip("/")
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                event = str(payload.pop("event"))
                workflow = WORKFLOWS.apply(workflow_id, event, payload)
                if AI_ENABLED and workflow["status"] in {"reviewing_requirement", "generating_draft_cases"}:
                    AI_WORKER.start(workflow_id)
                return self.send_json(200, workflow)
            except (KeyError, WorkflowError, ValueError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})
        if self.path != "/runs":
            return self.send_json(404, {"error": "not found"})
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            env = {key: str(payload[key]) for key in RUN_ENV_KEYS if key in payload}
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
                case_data = json.loads((CASES / case).read_text(encoding="utf-8"))
                if case_data.get("review", {}).get("status", "draft") != "approved":
                    raise ValueError(f"case is not approved: {case}")
                run_ids.append(start_run(case, env))
            return self.send_json(202, {"run_ids": run_ids})
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})


def main() -> None:
    port = int(os.getenv("SEVERTEST_API_PORT", "8088"))
    print(f"severtest API listening on http://127.0.0.1:{port}")
    if AI_ENABLED:
        for workflow in WORKFLOWS.list():
            if workflow["status"] in {"understanding_requirement", "reviewing_requirement", "generating_draft_cases"}:
                AI_WORKER.start(workflow["id"])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
