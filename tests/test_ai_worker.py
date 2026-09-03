import tempfile
import unittest
from pathlib import Path

from severtest.ai_worker import RequirementAIWorker
from severtest.workflow import WorkflowStore


class FakeRunner:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt, schema):
        self.prompts.append((prompt, schema))
        if len(self.prompts) == 1:
            return {
                "summary": "团队活动需求",
                "coverage_scope": {"read": ["需求.md"], "missing": []},
                "business_rules": [],
                "server_flow": [],
                "risks": [],
                "unknowns": [],
            }
        return {
            "conclusion": "需要回答奖励幂等规则",
            "questions": [{"id": "q1", "severity": "P1", "location": "奖励规则", "question": "是否允许重复领取？", "impact": "影响奖励幂等", "confirmation_needed": "确认重复请求结果"}],
        }


class FailingRunner:
    def generate(self, prompt, schema):
        raise RuntimeError("model unavailable")


class RequirementAIWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = WorkflowStore(root / "workflows")
        source = root / "需求.md"
        source.write_text("团队活动", encoding="utf-8")
        self.record = self.store.create(source.name, str(source), source.stat().st_size)
        self.root = root

    def tearDown(self):
        self.temp.cleanup()

    def test_processes_analysis_and_review(self):
        runner = FakeRunner()
        worker = RequirementAIWorker(self.store, runner, self.root, self.root / "sunnyisland")
        result = worker.process(self.record["id"])
        self.assertEqual(result["status"], "waiting_review_answers")
        self.assertEqual(result["analysis"]["summary"], "团队活动需求")
        self.assertEqual(result["review_conclusion"], "需要回答奖励幂等规则")
        self.assertEqual(result["review_questions"][0]["severity"], "P1")
        self.assertEqual(len(runner.prompts), 2)

    def test_records_worker_failure(self):
        worker = RequirementAIWorker(self.store, FailingRunner(), self.root, self.root / "sunnyisland")
        worker._run_guarded(self.record["id"])
        result = self.store.get(self.record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("model unavailable", result["error"])


if __name__ == "__main__":
    unittest.main()
