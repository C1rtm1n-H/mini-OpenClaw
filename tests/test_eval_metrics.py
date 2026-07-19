from __future__ import annotations

import unittest

from eval.metrics import (
    aggregate_summary,
    hybrid_success_rate,
    json_valid_rate,
    success_rate,
    tool_success_rate,
)
from eval.tasks import SAMPLE_TASKS, get_task


class EvalMetricsTest(unittest.TestCase):
    def test_structured_tool_parse_failure_counts_against_json_rate(self):
        records = [{
            "task": "read-config",
            "steps": [{"tool_calls": [
                {"name": "read", "arguments": {}, "arguments_parse_ok": False},
                {"name": "glob", "arguments": {"pattern": "*"}, "arguments_parse_ok": True},
            ]}],
            "final": "",
        }]
        self.assertEqual(json_valid_rate(records), 0.5)

    def test_tool_success_detects_returncode_failure(self):
        records = [{
            "task": "setup-script-audit-readonly",
            "steps": [{"tool_results": [
                {"name": "bash", "observation": "[stderr]\nboom\n[returncode=2]", "returncode": 2}
            ]}],
            "final": "失败",
        }]
        self.assertEqual(tool_success_rate(records), 0.0)

    def test_hybrid_requires_programmatic_and_judge_success(self):
        task = get_task("read-config")
        assert task is not None
        record = {
            "run_id": "r1",
            "task": "read-config",
            "steps": [{"tool_calls": [{"name": "read", "arguments": {"path": "config.json"}}]}],
            "final": "timeout = 30 秒。",
        }
        self.assertEqual(success_rate(SAMPLE_TASKS, [record]), 1.0)
        self.assertEqual(hybrid_success_rate(SAMPLE_TASKS, [record], [{"run_id": "r1", "passed": False}]), 0.0)
        self.assertEqual(hybrid_success_rate(SAMPLE_TASKS, [record], [{"run_id": "r1", "passed": True}]), 1.0)

    def test_aggregate_summary_reports_multiple_dimensions(self):
        summary = aggregate_summary(SAMPLE_TASKS, [], [])
        self.assertIn("programmatic_success_rate", summary)
        self.assertIn("avg_tokens", summary)
        self.assertIn("tool_success_rate", summary)


if __name__ == "__main__":
    unittest.main()
