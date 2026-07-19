from __future__ import annotations

import unittest

from eval.judge import parse_judge_json


class EvalJudgeTest(unittest.TestCase):
    def test_parse_plain_json(self):
        parsed = parse_judge_json('{"score": 4, "passed": true, "reason": "ok"}')
        self.assertEqual(parsed["score"], 4)
        self.assertTrue(parsed["passed"])

    def test_parse_fenced_json(self):
        parsed = parse_judge_json('```json\n{"score": 2, "passed": false}\n```')
        self.assertEqual(parsed["score"], 2)
        self.assertFalse(parsed["passed"])

    def test_reject_non_json(self):
        with self.assertRaises(ValueError):
            parse_judge_json("分数: 5")


if __name__ == "__main__":
    unittest.main()
