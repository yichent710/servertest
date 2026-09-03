from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class WorkflowError(ValueError):
    """Raised when a requirement workflow receives an invalid event."""


STATUS_LABELS = {
    "uploaded": "需求文档已上传",
    "understanding_requirement": "理解需求文档中",
    "reviewing_requirement": "评审需求中",
    "waiting_review_answers": "等待测试人员回答评审问题",
    "generating_draft_cases": "生成初版用例中",
    "waiting_case_supplements": "等待测试人员补充用例点",
    "generating_final_cases": "生成终版用例中",
    "waiting_final_approval": "等待测试人员确认终版用例",
    "generating_automation": "生成测试代码和断言中",
    "ready_for_execution": "可以执行",
    "failed": "处理失败",
}

EVENT_RULES = {
    "start_analysis": ({"uploaded", "failed"}, "understanding_requirement"),
    "requirement_understood": ({"understanding_requirement"}, "reviewing_requirement"),
    "review_completed": ({"reviewing_requirement"}, "waiting_review_answers"),
    "review_regeneration_requested": ({"waiting_review_answers"}, "reviewing_requirement"),
    "answers_submitted": ({"waiting_review_answers"}, "generating_draft_cases"),
    "draft_generated": ({"generating_draft_cases"}, "waiting_case_supplements"),
    "supplements_submitted": ({"waiting_case_supplements"}, "generating_final_cases"),
    "final_generated": ({"generating_final_cases"}, "waiting_final_approval"),
    "final_approved": ({"waiting_final_approval"}, "generating_automation"),
    "automation_generated": ({"generating_automation"}, "ready_for_execution"),
    "final_case_edited": ({"waiting_final_approval", "ready_for_execution"}, "waiting_final_approval"),
    "failed": (set(STATUS_LABELS) - {"ready_for_execution"}, "failed"),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowStore:
    def __init__(self, root: Path, clock: Callable[[], datetime] = utc_now):
        self.root = root
        self.clock = clock
        self._lock = threading.RLock()

    def _path(self, workflow_id: str) -> Path:
        if not workflow_id or any(character not in "0123456789abcdef" for character in workflow_id):
            raise WorkflowError("invalid workflow id")
        return self.root / workflow_id / "workflow.json"

    def _write(self, record: dict[str, Any]) -> None:
        path = self._path(record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def create(self, filename: str, source_path: str, size: int) -> dict[str, Any]:
        now = self.clock().isoformat()
        record = {
            "id": uuid.uuid4().hex,
            "filename": filename,
            "source_path": source_path,
            "size": size,
            "status": "uploaded",
            "status_label": STATUS_LABELS["uploaded"],
            "stage_started_at": None,
            "created_at": now,
            "updated_at": now,
            "stages": [],
            "analysis": None,
            "review_conclusion": None,
            "review_questions": [],
            "draft_cases": [],
            "supplements": [],
            "final_cases": [],
            "automation": {"status": "not_generated", "case_files": []},
            "error": None,
        }
        with self._lock:
            self._write(record)
        return record

    def get(self, workflow_id: str) -> dict[str, Any]:
        record = self._load(workflow_id)
        record["current_stage_duration_ms"] = self._current_duration(record)
        return record

    def _load(self, workflow_id: str) -> dict[str, Any]:
        try:
            return json.loads(self._path(workflow_id).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorkflowError("requirement workflow not found") from exc

    def list(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        records = []
        for path in self.root.glob("*/workflow.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                record["current_stage_duration_ms"] = self._current_duration(record)
                records.append(record)
            except (OSError, ValueError):
                continue
        return sorted(records, key=lambda item: item["created_at"], reverse=True)

    def apply(self, workflow_id: str, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        if event not in EVENT_RULES:
            raise WorkflowError(f"unknown workflow event: {event}")
        with self._lock:
            record = self._load(workflow_id)
            allowed, target = EVENT_RULES[event]
            if record["status"] not in allowed:
                raise WorkflowError(f"event {event} is not allowed while status is {record['status']}")
            now = self.clock()
            self._finish_active_stage(record, now)
            self._apply_payload(record, event, payload)
            record["status"] = target
            record["status_label"] = STATUS_LABELS[target]
            record["updated_at"] = now.isoformat()
            record["stage_started_at"] = now.isoformat() if target in {
                "understanding_requirement",
                "reviewing_requirement",
                "generating_draft_cases",
                "generating_final_cases",
                "generating_automation",
            } else None
            if record["stage_started_at"]:
                record["stages"].append({"status": target, "label": STATUS_LABELS[target], "started_at": record["stage_started_at"], "finished_at": None, "duration_ms": None})
            self._write(record)
            return self.get(workflow_id)

    def _current_duration(self, record: dict[str, Any]) -> int | None:
        started_at = record.get("stage_started_at")
        if not started_at:
            return None
        started = datetime.fromisoformat(started_at)
        return max(0, int((self.clock() - started).total_seconds() * 1000))

    def _finish_active_stage(self, record: dict[str, Any], now: datetime) -> None:
        if not record.get("stage_started_at") or not record.get("stages"):
            return
        stage = record["stages"][-1]
        if stage.get("finished_at"):
            return
        started = datetime.fromisoformat(stage["started_at"])
        stage["finished_at"] = now.isoformat()
        stage["duration_ms"] = max(0, int((now - started).total_seconds() * 1000))

    def _apply_payload(self, record: dict[str, Any], event: str, payload: dict[str, Any]) -> None:
        if event == "requirement_understood":
            analysis = payload.get("analysis")
            if not isinstance(analysis, dict):
                raise WorkflowError("requirement_understood requires analysis")
            record["analysis"] = analysis
        elif event == "review_completed":
            questions = payload.get("questions")
            if not isinstance(questions, list):
                raise WorkflowError("review_completed requires questions")
            record["review_questions"] = [
                {
                    "id": str(item.get("id", index + 1)),
                    "severity": str(item.get("severity", "P2")),
                    "location": str(item.get("location", "需求文档")),
                    "question": str(item["question"]),
                    "impact": str(item.get("impact", "")),
                    "confirmation_needed": str(item.get("confirmation_needed", "")),
                    "answer": None,
                }
                for index, item in enumerate(questions)
            ]
            record["review_conclusion"] = str(payload.get("conclusion", ""))
        elif event == "review_regeneration_requested":
            record["review_questions"] = []
            record["review_conclusion"] = None
        elif event == "answers_submitted":
            answers = payload.get("answers")
            if not isinstance(answers, dict):
                raise WorkflowError("answers_submitted requires answers")
            for question in record["review_questions"]:
                answer = str(answers.get(question["id"], "")).strip()
                if not answer:
                    raise WorkflowError(f"answer is required for question {question['id']}")
                question["answer"] = answer
        elif event == "draft_generated":
            record["draft_cases"] = self._require_cases(payload, "draft_generated")
        elif event == "supplements_submitted":
            supplements = payload.get("supplements")
            if not isinstance(supplements, list):
                raise WorkflowError("supplements_submitted requires supplements")
            record["supplements"] = [str(item).strip() for item in supplements if str(item).strip()]
        elif event in {"final_generated", "final_case_edited"}:
            record["final_cases"] = self._require_cases(payload, event)
            record["automation"] = {"status": "outdated" if event == "final_case_edited" else "not_generated", "case_files": []}
        elif event == "final_approved":
            record["automation"]["status"] = "generating"
        elif event == "automation_generated":
            files = payload.get("case_files")
            if not isinstance(files, list) or not files:
                raise WorkflowError("automation_generated requires case_files")
            record["automation"] = {"status": "ready", "case_files": [str(item) for item in files], "generated_at": self.clock().isoformat()}
        elif event == "failed":
            record["error"] = str(payload.get("error", "unknown workflow error"))
        if event != "failed":
            record["error"] = None

    @staticmethod
    def _require_cases(payload: dict[str, Any], event: str) -> list[dict[str, Any]]:
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise WorkflowError(f"{event} requires cases")
        required = {"id", "name", "module", "feature", "preconditions", "steps", "assertions"}
        for case in cases:
            if not isinstance(case, dict) or not required.issubset(case):
                raise WorkflowError(f"{event} contains an incomplete case")
        return cases
