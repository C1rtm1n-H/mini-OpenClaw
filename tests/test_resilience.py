from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.loop import AgentLoop, _is_transient_backend_error
from tools.base import Tool, ToolRegistry


class FlakyBackend:
    def __init__(self, failures: int, error: Exception | None = None):
        self.failures = failures
        self.error = error or OSError("connection reset")
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return {"content": "recovered", "tool_calls": [], "usage": {"total_tokens": 12}}


class BrokenToolBackend:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {"content": "", "tool_calls": [{"id": "c1", "name": "broken", "arguments": {}}]}
        tool_results = [m for m in messages if m.get("role") == "tool"]
        assert tool_results and "执行失败" in tool_results[-1]["content"]
        return {"content": "recovered from tool error", "tool_calls": []}


class ResilienceTest(unittest.TestCase):
    @patch("agent.loop.time.sleep", return_value=None)
    def test_transient_backend_failure_recovers(self, _sleep):
        backend = FlakyBackend(failures=2)
        loop = AgentLoop(backend, ToolRegistry(), "system", max_turns=3, max_steps=5)
        self.assertEqual(loop.send("test"), "recovered")
        self.assertEqual(backend.calls, 3)
        self.assertEqual([s["attempt"] for s in loop.tracer.spans], [1, 2, 3])
        self.assertEqual([s["ok"] for s in loop.tracer.spans], [False, False, True])

    @patch("agent.loop.time.sleep", return_value=None)
    def test_http_400_is_not_retried(self, _sleep):
        backend = FlakyBackend(10, RuntimeError("后端 HTTP 400：invalid messages"))
        loop = AgentLoop(backend, ToolRegistry(), "system")
        result = loop.send("test")
        self.assertIn("永久错误，不重试", result)
        self.assertEqual(backend.calls, 1)

    @patch("agent.loop.time.sleep", return_value=None)
    def test_retry_exhaustion_is_clear_and_next_task_can_continue(self, _sleep):
        backend = FlakyBackend(3)
        loop = AgentLoop(backend, ToolRegistry(), "system")
        first = loop.send("first")
        self.assertIn("重试 3 次后仍失败", first)
        self.assertEqual(loop.send("second"), "recovered")

    def test_tool_error_becomes_observation(self):
        registry = ToolRegistry()
        registry.register(Tool("broken", "fails", {"type": "object", "properties": {}},
                               lambda: (_ for _ in ()).throw(ValueError("boom"))))
        loop = AgentLoop(BrokenToolBackend(), registry, "system", auto_approve=True)
        self.assertEqual(loop.send("test"), "recovered from tool error")

    def test_error_classification(self):
        self.assertTrue(_is_transient_backend_error(RuntimeError("HTTP 429 rate limit")))
        self.assertTrue(_is_transient_backend_error(RuntimeError("HTTP 503 unavailable")))
        self.assertTrue(_is_transient_backend_error(RuntimeError("server disconnected")))
        self.assertFalse(_is_transient_backend_error(RuntimeError("HTTP 401 invalid key")))
        self.assertFalse(_is_transient_backend_error(TypeError("bad payload")))


if __name__ == "__main__":
    unittest.main()
