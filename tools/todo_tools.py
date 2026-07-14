"""Day 8 下午 · todo 工具：让模型自己列清单、勾进度。

把 TodoList 暴露成工具——模型开始复杂任务时先 todo_write、每步 update_todo。
对应 Claude Code 的 TodoWrite / update_todo 工具。
"""

from __future__ import annotations
from agent.planning import TODO
from .base import Tool


# ---------------------------------------------------------------------------
# todo_write：把大目标分解为有序子任务
# ---------------------------------------------------------------------------

def _todo_write(items: list[str], replace: bool = False) -> str:
    """创建单层主清单；仅显式故障重规划时允许替换。"""
    if not items:
        return "错误：items 不能为空；请提供至少一个子任务。"
    if TODO.items and not replace:
        return (
            "[规划层] 当前任务已经有主清单，拒绝创建嵌套/子清单，也未修改原清单。"
            "请直接执行当前项，并用 update_todo 更新原主清单；"
            "只有当前方案确实不可行、需要整体重规划时才可设置 replace=true。\n"
            "当前主清单：\n" + TODO.render()
        )
    TODO.write(items)
    action = "已重建" if replace else "已创建"
    return f"任务主清单{action}：\n" + TODO.render()


todo_write_tool = Tool(
    name="todo_write",
    description=(
        "每个用户任务最多创建一次单层主清单。仅在当前没有清单时调用；"
        "处理主清单中的某一项时禁止再次调用、禁止创建子清单，直接执行并 update_todo。"
        "每个子任务应具体、可验证、有明确终点（如「读取 config.py」而非「处理配置」）。"
        "只有当前方案确实不可行、需要整体重规划时才设置 replace=true。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "有序子任务文本列表，例如 ['读取 main.py', '修改数据库连接', '运行测试']",
            },
            "replace": {
                "type": "boolean",
                "description": "是否整体替换现有主清单，默认 false；仅用于故障后的整体重规划",
            },
        },
        "required": ["items"],
    },
    run=_todo_write,
)


# ---------------------------------------------------------------------------
# update_todo：完成或开始某条子任务时更新状态
# ---------------------------------------------------------------------------

def _update_todo(id: int, status: str) -> str:  # noqa: A002
    """更新子任务状态。"""
    # 如果模型要开始一个新任务，先把上一个 in_progress 的自动标记为 completed
    if status == "in_progress":
        current = TODO.current_in_progress()
        if current is not None and current["id"] != id:
            TODO.update(current["id"], "completed")

    TODO.update(id, status)

    label = {
        "pending": "待处理",
        "in_progress": "进行中",
        "completed": "已完成",
        "blocked": "已阻塞",
    }
    return f"子任务 {id} 已标记为「{label.get(status, status)}」。\n当前清单：\n{TODO.render()}"


update_todo_tool = Tool(
    name="update_todo",
    description=(
        "完成或开始某条子任务时更新其状态。开始一条任务时标 in_progress，"
        "完成后标 completed，遇到无法解决的外部阻碍时标 blocked。"
        "每完成一条子任务后应调用此工具标记进度。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "id": {
                "type": "integer",
                "description": "要更新的子任务 ID（对应清单中的数字）",
            },
            "status": {
                "type": "string",
                "enum": ["in_progress", "completed", "blocked"],
                "description": "新状态：in_progress=进行中, completed=已完成, blocked=阻塞",
            },
        },
        "required": ["id", "status"],
    },
    run=_update_todo,
)
