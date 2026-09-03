import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from severtest.workflow import WorkflowError, WorkflowStore


def sample_case():
    return {
        "id": "case_one",
        "name": "第一条用例",
        "module": "活动系统",
        "feature": "团队活动",
        "preconditions": [],
        "steps": [{"action": "load_actor"}],
        "assertions": [{"name": "Actor存在", "metric": "after.actor_version", "op": "gt", "expected": 0}],
    }


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 9, 3, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class WorkflowStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = MutableClock()
        self.store = WorkflowStore(Path(self.temp.name), self.clock)
        self.record = self.store.create("需求.md", "/tmp/需求.md", 10)

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, event, payload=None):
        return self.store.apply(self.record["id"], event, payload)

    def understand(self):
        return self.apply("requirement_understood", {"analysis": {"summary": "需求摘要"}})

    def test_tracks_active_and_completed_stage_duration(self):
        self.apply("start_analysis")
        self.clock.advance(1.25)
        self.assertEqual(self.store.get(self.record["id"])["current_stage_duration_ms"], 1250)
        result = self.understand()
        self.assertEqual(result["stages"][0]["duration_ms"], 1250)
        self.assertEqual(result["status"], "reviewing_requirement")

    def test_rejects_skipping_workflow_stage(self):
        with self.assertRaises(WorkflowError):
            self.apply("draft_generated", {"cases": [sample_case()]})

    def test_requires_every_review_answer(self):
        self.apply("start_analysis")
        self.understand()
        self.apply("review_completed", {"questions": [{"id": "q1", "question": "活动何时开启？"}]})
        with self.assertRaises(WorkflowError):
            self.apply("answers_submitted", {"answers": {}})

    def test_can_request_review_regeneration(self):
        self.apply("start_analysis")
        self.understand()
        self.apply("review_completed", {"conclusion": "需要确认", "questions": [{"id": "q1", "question": "活动何时开启？"}]})
        regenerated = self.apply("review_regeneration_requested")
        self.assertEqual(regenerated["status"], "reviewing_requirement")
        self.assertEqual(regenerated["review_questions"], [])
        self.assertIsNone(regenerated["review_conclusion"])

    def test_full_flow_and_manual_edit_invalidates_automation(self):
        self.apply("start_analysis")
        self.understand()
        self.apply("review_completed", {"questions": [{"id": "q1", "question": "活动何时开启？"}]})
        self.apply("answers_submitted", {"answers": {"q1": "开服第二天"}})
        self.apply("draft_generated", {"cases": [sample_case()]})
        self.apply("supplements_submitted", {"supplements": ["补充重复领奖"]})
        self.apply("final_generated", {"cases": [sample_case()]})
        self.apply("final_approved")
        ready = self.apply("automation_generated", {"case_files": ["case-one.json"]})
        self.assertEqual(ready["status"], "ready_for_execution")
        edited_case = sample_case()
        edited_case["name"] = "修改后的用例"
        edited = self.apply("final_case_edited", {"cases": [edited_case]})
        self.assertEqual(edited["status"], "waiting_final_approval")
        self.assertEqual(edited["automation"]["status"], "outdated")


if __name__ == "__main__":
    unittest.main()
