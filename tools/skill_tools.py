"""invoke_skill 工具 — 让模型按需加载 skill 正文，而非手动 read SKILL.md。

用法：模型调用 invoke_skill(name="experiment-audit")，
系统自动查找对应 SKILL.md 并将正文注入 observation。
"""
from __future__ import annotations

from skills.loader import load_skill_body
from .base import Tool


def _invoke_skill(name: str) -> str:
    """按名称加载 skill 正文并返回。"""
    if not name or not name.strip():
        return "错误：请提供要加载的 skill 名称（如 invoke_skill(name=\"experiment-audit\")）。"

    body = load_skill_body(name.strip())
    if body is None:
        return (
            f"错误：未找到启用的 skill '{name}'。"
            f"请检查名称拼写，或确认该 skill 未被禁用。"
        )
    return body


invoke_skill_tool = Tool(
    name="invoke_skill",
    description=(
        "当任务匹配某个 skill 时，调用此工具按名称加载 skill 的完整操作流程。"
        "加载后严格按正文中的步骤、检查项和输出格式执行。"
        "不需要先用 read 读取 SKILL.md 文件——直接调用本工具即可获取正文。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "要加载的 skill 名称（如 experiment-audit、paper-digest、dependency-environment-audit 等）",
            },
        },
        "required": ["name"],
    },
    run=_invoke_skill,
)
