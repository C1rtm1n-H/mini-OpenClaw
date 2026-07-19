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
                "tool_calls": [{"id": "c1", "name": "read", "arguments": {"path": "config.json"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return {
            "content": "timeout = 30 秒。",
            "tool_calls": [],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
        }


class TaskLike:
    name = "read-config"
    instruction = "读取 config.json，告诉我 timeout 是多少"


class EvalTrajectoryTest(unittest.TestCase):
    def test_agent_loop_sink_records_final_usage_and_full_tool_result(self):
        registry = ToolRegistry()
        registry.register(Tool("read", "read file", {"type": "object", "properties": {}},
                               lambda path: '{"timeout": 30, "long": "' + "x" * 900 + '"}'))
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

        self.assertEqual(record["final"], "timeout = 30 秒。")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["summary"]["tokens"], 41)
        self.assertEqual(record["steps"][0]["tool_calls"][0]["name"], "read")
        observation = record["steps"][0]["tool_results"][0]["observation"]
        self.assertIn('"timeout": 30', observation)
        self.assertGreater(len(observation), 900)
        digest = record_to_judge_digest(record)
        self.assertIn("timeout = 30", digest)
        self.assertIn("tool_call", digest)


if __name__ == "__main__":
    unittest.main()
