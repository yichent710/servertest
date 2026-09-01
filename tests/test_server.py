import unittest

from severtest.server import RUNS, diagnose, run_summary, validate_requirement_name


class DiagnosisTest(unittest.TestCase):
    def test_reports_connection_failure(self):
        report = {"events": [{"step": "run", "status": "FAILED", "details": {"error": "websocket.Dial bad status"}}]}
        self.assertEqual(diagnose(report, 1)["stage"], "建立连接")

    def test_reports_actor_load_failure(self):
        report = {"events": [{"step": "run", "status": "FAILED", "details": {"error": "load initial actor: timeout"}}]}
        self.assertEqual(diagnose(report, 1)["title"], "Actor 加载失败")

    def test_prioritizes_failed_assertions(self):
        report = {"assertions": [{"name": "分数增加", "passed": False}], "events": []}
        self.assertIn("分数增加", diagnose(report, 1)["cause"])

    def test_reports_success(self):
        self.assertEqual(diagnose({"events": [], "assertions": []}, 0)["title"], "测试通过")

    def test_summarizes_run_statuses(self):
        RUNS.clear()

    def test_accepts_supported_requirement_name(self):
        self.assertEqual(validate_requirement_name("团队活动需求文档.docx"), "团队活动需求文档.docx")

    def test_rejects_requirement_path(self):
        with self.assertRaises(ValueError):
            validate_requirement_name("../需求文档.md")

    def test_rejects_unsupported_requirement_type(self):
        with self.assertRaises(ValueError):
            validate_requirement_name("需求文档.exe")
        RUNS.update({"one": {"status": "passed"}, "two": {"status": "failed"}, "three": {"status": "running"}})
        self.assertEqual(run_summary(), {"total": 3, "queued": 0, "running": 1, "passed": 1, "failed": 1})
        RUNS.clear()


if __name__ == "__main__":
    unittest.main()
