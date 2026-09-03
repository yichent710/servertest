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
        if len(self.prompts) == 2:
            return {
                "conclusion": "需要回答奖励幂等规则",
                "questions": [{"id": "q1", "severity": "P1", "location": "奖励规则", "question": "是否允许重复领取？", "impact": "影响奖励幂等", "confirmation_needed": "确认重复请求结果"}],
            }
        return {"cases": [{"id": "gve_reward", "name": "领取奖励", "module": "活动系统", "feature": "团队活动", "scenario": "个人奖励", "objective": "验证领奖", "source_refs": ["review:q1"], "preconditions": ["达到积分"], "steps": ["领取奖励"], "expected_results": ["奖励到账"], "assertions": [], "automation": {"status": "needs_action", "reason": "待生成 action"}, "data_impact": "增加奖励", "cleanup": "专用账号", "server_evidence": {"protocols": [], "code_symbols": [], "actor_fields": [], "config_keys": [], "log_keywords": []}, "change_note": "初版"}]}


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

        self.store.apply(self.record["id"], "answers_submitted", {"answers": {"q1": "不允许重复领取"}})
        draft = worker.process(self.record["id"])
        self.assertEqual(draft["status"], "waiting_case_supplements")
        self.assertEqual(draft["draft_cases"][0]["module"], "活动系统")
        self.assertEqual(len(runner.prompts), 3)

    def test_records_worker_failure(self):
        worker = RequirementAIWorker(self.store, FailingRunner(), self.root, self.root / "sunnyisland")
        worker._run_guarded(self.record["id"])
        result = self.store.get(self.record["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("model unavailable", result["error"])


if __name__ == "__main__":
    unittest.main()
