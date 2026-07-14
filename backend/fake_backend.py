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

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None) -> dict[str, Any]:
        tools = tools or []
        tool_names = [t["function"]["name"] for t in tools]
        user_task = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        last = messages[-1]["content"] if messages else ""

        if messages and messages[-1].get("role") == "tool":
            last_tool = messages[-1].get("name", "")
            if last_tool == "grep" and "report.md" in str(user_task) and "write" in tool_names:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "fake_write_report",
                        "name": "write",
                        "arguments": {
                            "path": "report.md",
                            "content": "# TODO 汇总\n\n" + str(last),
                        },
                    }],
                }
            return {"role": "assistant", "content": f"[FakeBackend] 已根据工具结果完成：{str(last)[:120]}", "tool_calls": []}

        task = str(user_task)
        if ("记住" in task or "remember" in task.lower()) and "remember" in tool_names:
            note = task.strip()
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "fake_remember", "name": "remember", "arguments": {"note": note}}]}

        if ("忘记" in task or "遗忘" in task or "forget" in task.lower()) and "forget" in tool_names:
            key = task.strip()
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "fake_forget", "name": "forget", "arguments": {"key": key}}]}

        if "echo" in task.lower() or "原样返回" in task:
            echo_tool = "mcp__echo" if "mcp__echo" in tool_names else ("echo" if "echo" in tool_names else None)
            if echo_tool:
                text = _extract_quoted(task) or task
                return {"role": "assistant", "content": "", "tool_calls": [{"id": "fake_echo", "name": echo_tool, "arguments": {"text": text}}]}

        if ("TODO" in task or "todo" in task.lower()) and "report.md" in task and "grep" in tool_names:
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "fake_grep_todo", "name": "grep", "arguments": {"pattern": "TODO|FIXME", "path": "."}}]}

        if "add" in task.lower() and "mcp__add" in tool_names:
            nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", task)]
            a, b = (nums + [0, 0])[:2]
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "fake_add", "name": "mcp__add", "arguments": {"a": a, "b": b}}]}

        if tools and any(k in task for k in ("文件", "运行", "file", "run", "hello")):
            name = tools[0]["function"]["name"]
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "fake_default", "name": name, "arguments": {}}],
            }
        return {"role": "assistant", "content": "[FakeBackend] 你好，我是离线占位后端。配好 DEEPSEEK_API_KEY 即用真模型。", "tool_calls": []}


def _extract_quoted(text: str) -> str | None:
    for quote in ("'", '"', "“", "‘"):
        if quote in text:
            close = {"'": "'", '"': '"', "“": "”", "‘": "’"}[quote]
            start = text.find(quote)
            end = text.find(close, start + 1)
            if end > start:
                return text[start + 1:end]
    return None
