from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from eval.metrics import (
    aggregate_summary,
    hybrid_success_rate,
    json_valid_rate,
    success_rate,
    tool_success_rate,
    main,
)
from eval.tasks import SAMPLE_TASKS, get_task


class EvalMetricsTest(unittest.TestCase):
    def test_cli_requires_real_records_or_explicit_demo(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            main([])
        self.assertEqual(raised.exception.code, 2)

    def test_cli_demo_must_be_explicit(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--demo"]), 0)

    def test_structured_tool_parse_failure_counts_against_json_rate(self):
        records = [{
            "task": "list-dir",
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
        task = get_task("audit-bad-experiment")
        assert task is not None
        record = {
            "run_id": "r1",
            "task": "audit-bad-experiment",
            "steps": [{"tool_calls": [
                {"name": "glob", "arguments": {"pattern": "*.py", "path": "eval_sample/bad_experiment"}},
                {"name": "grep", "arguments": {"pattern": "seed|/home/", "path": "eval_sample/bad_experiment"}},
                {"name": "read", "arguments": {"path": "eval_sample/bad_experiment/train.py"}},
            ], "tool_results": [
                {"name": "glob", "observation": "train.py\nevaluate.py"},
                {"name": "grep", "observation": "train.py:31:/home/user/data\ntrain.py:85:random.seed"},
                {"name": "read", "observation": "DEVICE = 'cuda:0'"},
            ]}],
            "final": "train.py:85 缺少随机种子 seed，建议添加 torch.manual_seed。train.py:31 硬编码路径 /home/user/data/，应改为命令行参数。",
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
