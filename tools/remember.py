"""remember / forget 工具：管理带去重、TTL 和容量限制的持久记忆。"""
from __future__ import annotations
import re
from agent.memory import Memory, KVMemory

from .base import Tool


def _remember(note: str, ttl_seconds: float | None = None,
              replace: str = "") -> str:
    """key: value 走 KV；普通文本可新增或按 ID/原文更新。"""
    # 匹配 "key: value" 或 "key：value"（中文冒号）
    m = re.match(r"^(.+?)[:：]\s*(.+)", note.strip())
    if m:
        key, value = m.group(1).strip(), m.group(2).strip()
        return KVMemory("memory.json").remember(key, value, ttl_seconds)
    memory = Memory("MEMORY.md")
    if replace.strip():
        return memory.update(replace, note, ttl_seconds)
    return memory.write(note, ttl_seconds)


def _forget(key: str = "", text: str = "") -> str:
    """按 key 删除 KV，或按 ID/完整原文删除纯文本记忆。"""
    if key.strip():
        return KVMemory("memory.json").forget(key)
    if text.strip():
        return Memory("MEMORY.md").delete(text)
    raise ValueError("key 和 text 至少提供一个")


remember_tool = Tool(
    name="remember",
    description="写入或更新持久记忆。自动去重并受容量限制；'key: value' 按 key 更新且报告冲突；普通文本可用 replace 指定 ID/完整原文更新；可设置 TTL。",
    parameters={
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "要记住的事实。普通文本追加到列表；'键: 值' / 'key: value' 格式则按 key 覆盖更新到 KV 记忆。",
            },
            "ttl_seconds": {
                "type": "number",
                "description": "可选有效期（秒），必须大于 0；不传表示永久。",
            },
            "replace": {
                "type": "string",
                "description": "可选。更新普通文本记忆时，填写旧记忆 ID 或完整原文。",
            },
        },
        "required": ["note"],
    },
    run=_remember,
)

forget_tool = Tool(
    name="forget",
    description="删除单条持久记忆。key 用于 KV 记忆；text 用于纯文本记忆 ID 或完整原文；二选一。",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "可选，要删除的 KV 记忆 key。",
            },
            "text": {
                "type": "string",
                "description": "可选，要删除的纯文本记忆 ID 或完整原文。",
            },
        },
        "required": [],
    },
    run=_forget,
)
