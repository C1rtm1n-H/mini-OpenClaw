from __future__ import annotations

import unittest

from agent.loop import AgentLoop
from eval.trajectory import TrajectoryRecorder, record_to_judge_digest
from tools.base import Tool, ToolRegistry


class ToolBackend:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "glob", "arguments": {"pattern": "*"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return {
            "content": "当前目录有：README.md、agent、eval。",
            "tool_calls": [],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
        }


class FailingToolBackend:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {"content": "", "tool_calls": [{"id": "bad", "name": "read", "arguments": {}}]}
        return {"content": "读取失败，停止。", "tool_calls": []}


class TaskLike:
    name = "audit-bad-experiment"
    instruction = "审计 eval_sample/bad_experiment/ 目录下的实验代码可复现性"


class EvalTrajectoryTest(unittest.TestCase):
    def test_agent_loop_sink_records_final_usage_and_full_tool_result(self):
        registry = ToolRegistry()
        long_output = "x" * 900
        registry.register(Tool("glob", "list files", {"type": "object", "properties": {}},
                               lambda pattern: f"README.md\nagent\neval\n{long_output}"))
        recorder = TrajectoryRecorder(TaskLike(), agent_meta={"backend": "ToolBackend"})
        loop = AgentLoop(
            ToolBackend(),
            registry,
            "system",
            auto_approve=True,
            max_turns=3,
            max_steps=5,
            trajectory_sink=recorder.sink,
        )

        final = loop.run(TaskLike.instruction)
        record = recorder.finish(final=final, spans=loop.tracer.spans)

        self.assertEqual(record["final"], "当前目录有：README.md、agent、eval。")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["summary"]["tokens"], 41)
        self.assertEqual(record["steps"][0]["tool_calls"][0]["name"], "glob")
        observation = record["steps"][0]["tool_results"][0]["observation"]
        self.assertIn("README.md", observation)
        self.assertGreater(len(observation), 900)
        digest = record_to_judge_digest(record)
        self.assertIn("agent", digest)
        self.assertIn("tool_call", digest)

    def test_failed_tool_observation_marks_record_and_span_failed(self):
        registry = ToolRegistry()
        registry.register(Tool("read", "read", {"type": "object"},
                               lambda path: "never"))
        recorder = TrajectoryRecorder(TaskLike())
        loop = AgentLoop(
            FailingToolBackend(), registry, "system", auto_approve=True,
            max_turns=3, max_steps=5, trajectory_sink=recorder.sink,
        )
        final = loop.run(TaskLike.instruction)
        record = recorder.finish(final=final, spans=loop.tracer.spans)

        self.assertFalse(record["steps"][0]["tool_results"][0]["ok"])
        tool_span = next(span for span in record["spans"] if span["kind"] == "tool")
        self.assertFalse(tool_span["ok"])


if __name__ == "__main__":
    unittest.main()
