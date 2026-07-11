"""上下文管理（Day5）：token 预算、滑动窗口、自动摘要 / compaction。

模型上下文窗口有限。长任务里 messages 会越堆越长，迟早超预算。
策略：
  - 估算当前 messages 的 token 数；
  - 超过阈值时触发 compaction：把较早的对话摘要成一条 system 备忘，
    保留最近 K 轮原文 + 关键工具结果；
  - tool result 过长时先截断/摘要再注入。
"""
from __future__ import annotations
from typing import Any


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    # 粗估即可（字符数/4）。
    return sum(len(str(m.get("content", ""))) for m in messages) // 4


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

    old = body[:-keep_recent]
    recent = body[-keep_recent:]
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
