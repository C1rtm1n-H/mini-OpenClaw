"""上下文管理（Day5）：token 预算、滑动窗口、自动摘要 / compaction。

模型上下文窗口有限。长任务里 messages 会越堆越长，迟早超预算。
策略：
  - 估算当前 messages 的 token 数；
  - 超过阈值时触发 compaction：把较早的对话摘要成一条 system 备忘，
    保留最近 K 轮原文 + 关键工具结果；
  - tool result 过长时先截断/摘要再注入。
"""
from __future__ import annotations
import json
from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    # 把 tool_calls/arguments 也计入；只统计 content 会低估工具密集型任务。
    serialized = json.dumps(messages, ensure_ascii=False, default=str)
    return len(serialized) // 4


def _safe_recent_start(body: list[dict[str, Any]], proposed: int) -> int:
    """把窗口切点移到合法消息边界，绝不拆散 tool-call 事务。

    OpenAI 协议要求每条 role=tool 消息都紧跟在声明对应 tool_calls 的
    assistant 消息之后。滑动窗口如果从 tool 消息开始，就会得到 HTTP 400。
    """
    start = max(0, min(proposed, len(body)))
    if start >= len(body) or body[start].get("role") != "tool":
        return start

    # 向前越过同一轮的所有 tool results，并保留发起调用的 assistant。
    first_tool = start
    while start > 0 and body[start].get("role") == "tool":
        start -= 1
    if body[start].get("role") == "assistant" and body[start].get("tool_calls"):
        return start

    # 历史本身若已不完整，至少不要把孤立 tool 消息发给后端。
    start = first_tool
    while start < len(body) and body[start].get("role") == "tool":
        start += 1
    return start


def maybe_compact(messages: list[dict[str, Any]], budget: int = 6000) -> list[dict[str, Any]]:
    """超预算则压缩历史，返回新的 messages。"""
    if estimate_tokens(messages) <= budget:
        return messages
    if len(messages) <= 6:
        return messages

    system = messages[0] if messages and messages[0].get("role") == "system" else None
    body = messages[1:] if system else messages[:]

    keep_recent = 8
    if len(body) <= keep_recent:
        return messages

    recent_start = _safe_recent_start(body, len(body) - keep_recent)
    old = body[:recent_start]
    recent = body[recent_start:]
    summary = _summarize_messages(old)
    compact_msg = {
        "role": "system",
        "content": (
            "[历史上下文压缩备忘]\n"
            "以下是较早对话的压缩摘要，用于延续当前任务；最近消息仍保留原文。\n"
            f"{summary}"
        ),
    }
    return ([system] if system else []) + [compact_msg] + recent


def _summarize_messages(messages: list[dict[str, Any]], max_items: int = 24) -> str:
    lines: list[str] = []
    for m in messages[-max_items:]:
        role = m.get("role", "?")
        name = m.get("name")
        content = str(m.get("content", "")).replace("\n", " ").strip()
        if len(content) > 220:
            content = content[:220] + "..."
        label = f"{role}({name})" if name else str(role)
        lines.append(f"- {label}: {content}")
    omitted = len(messages) - len(lines)
    prefix = f"已省略更早的 {omitted} 条消息。\n" if omitted > 0 else ""
    return prefix + "\n".join(lines)


def truncate_observation(text: str, max_chars: int = 4000) -> str:
    """工具结果过长时截断并提示。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[已截断，共 {len(text)} 字符]"
