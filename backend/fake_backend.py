"""一个"假后端"，用于未配 DeepSeek key 时离线跑通骨架。

它实现和真后端 backend/client.py（DeepSeekBackend）一样的最小接口：
  chat(messages, tools) -> {"role": "assistant", "content": ..., "tool_calls": [...] }

行为：用极简规则模拟一个会调用工具的模型，让 selfcheck / 主循环骨架能跑。
配好 DEEPSEEK_API_KEY 后，agent/cli.py 会自动改用真模型（DeepSeekBackend）。
"""
from __future__ import annotations
import re
from typing import Any


class FakeBackend:
    """规则驱动的假模型：只为打通管道，不要当真。"""

    def _result(self, content: str, tool_calls: list | None = None) -> dict[str, Any]:
        """构造归一化返回，自动附加模拟 usage。"""
        tool_calls = tool_calls or []
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
            "usage": self._fake_usage(content, tool_calls),
        }

    @staticmethod
    def _fake_usage(content: str, tool_calls: list) -> dict:
        """生成模拟 usage，让 Tracer 在离线模式也能工作。"""
        prompt_tokens = 200
        completion_tokens = len(content) // 4 + sum(
            len(str(c.get("arguments", ""))) // 4 for c in tool_calls
        )
        return {"prompt_tokens": prompt_tokens, "completion_tokens": max(completion_tokens, 10),
                "total_tokens": prompt_tokens + max(completion_tokens, 10)}

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None) -> dict[str, Any]:
        tools = tools or []
        tool_names = [t["function"]["name"] for t in tools]
        user_task = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        last = messages[-1]["content"] if messages else ""

        if messages and messages[-1].get("role") == "tool":
            last_tool = messages[-1].get("name", "")
            if last_tool == "grep" and "report.md" in str(user_task) and "write" in tool_names:
                return self._result("", [{
                    "id": "fake_write_report", "name": "write",
                    "arguments": {"path": "report.md", "content": "# TODO 汇总\n\n" + str(last)},
                }])
            return self._result(f"[FakeBackend] 已根据工具结果完成：{str(last)[:120]}")

        task = str(user_task)
        if ("记住" in task or "remember" in task.lower()) and "remember" in tool_names:
            return self._result("", [{"id": "fake_remember", "name": "remember", "arguments": {"note": task.strip()}}])

        if ("忘记" in task or "遗忘" in task or "forget" in task.lower()) and "forget" in tool_names:
            return self._result("", [{"id": "fake_forget", "name": "forget", "arguments": {"key": task.strip()}}])

        if "echo" in task.lower() or "原样返回" in task:
            echo_tool = "mcp__echo" if "mcp__echo" in tool_names else ("echo" if "echo" in tool_names else None)
            if echo_tool:
                text = _extract_quoted(task) or task
                return self._result("", [{"id": "fake_echo", "name": echo_tool, "arguments": {"text": text}}])

        if ("TODO" in task or "todo" in task.lower()) and "report.md" in task and "grep" in tool_names:
            return self._result("", [{"id": "fake_grep_todo", "name": "grep", "arguments": {"pattern": "TODO|FIXME", "path": "."}}])

        if "add" in task.lower() and "mcp__add" in tool_names:
            nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", task)]
            a, b = (nums + [0, 0])[:2]
            return self._result("", [{"id": "fake_add", "name": "mcp__add", "arguments": {"a": a, "b": b}}])

        if tools and any(k in task for k in ("文件", "运行", "file", "run", "hello")):
            return self._result("", [{"id": "fake_default", "name": tools[0]["function"]["name"], "arguments": {}}])

        return self._result("[FakeBackend] 你好，我是离线占位后端。配好 DEEPSEEK_API_KEY 即用真模型。")


def _extract_quoted(text: str) -> str | None:
    for quote in ("'", '"', "“", "‘"):
        if quote in text:
            close = {"'": "'", '"': '"', "“": "”", "‘": "’"}[quote]
            start = text.find(quote)
            end = text.find(close, start + 1)
            if end > start:
                return text[start + 1:end]
    return None
