import unittest

from severtest.server import diagnose


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


if __name__ == "__main__":
    unittest.main()
