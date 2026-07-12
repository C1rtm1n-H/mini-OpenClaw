"""remember / forget 工具 — 让模型自己管理持久记忆（Day10 · 步骤 3-4）。

- remember：检测 key: value 模式自动写入 KVMemory（可覆盖更新）；
  普通文本则追加到 Memory（纯文本列表）。
- forget：按 key 删除一条 KV 记忆。
"""
from __future__ import annotations
import re
from agent.memory import Memory, KVMemory

from .base import Tool


def _remember(note: str) -> str:
    """智能写入：key: value 走 KV，否则走纯文本追加。"""
    # 匹配 "key: value" 或 "key：value"（中文冒号）
    m = re.match(r"^(.+?)[:：]\s*(.+)", note.strip())
    if m:
        key, value = m.group(1).strip(), m.group(2).strip()
        return KVMemory("memory.json").remember(key, value)
    return Memory("MEMORY.md").write(note) or f"已记住：{note.strip()}"


def _forget(key: str) -> str:
    """删除一条 KV 记忆。"""
    return KVMemory("memory.json").forget(key)


remember_tool = Tool(
    name="remember",
    description="当用户告诉你一条应长期记住的项目约定 / 偏好 / 关键决策时，调用它写入持久记忆。下次会话会自动召回。支持 'key: value' 格式（可覆盖更新）。",
    parameters={
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "要记住的事实。普通文本追加到列表；'键: 值' / 'key: value' 格式则按 key 覆盖更新到 KV 记忆。",
            },
        },
        "required": ["note"],
    },
    run=lambda note: _remember(note),
)

forget_tool = Tool(
    name="forget",
    description="当用户要求忘记/撤销某条记忆时，按 key 删除一条 KV 记忆。",
    parameters={
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "要遗忘的记忆的 key（如 '时间戳格式'、'包管理器'）。",
            },
        },
        "required": ["key"],
    },
    run=lambda key: _forget(key),
)
