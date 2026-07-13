"""规划层：TodoList（分解 + 状态机）+ 反思 + 错误恢复 + 无进展检测。

Day 8 下午：为 agent 加一层审议式规划——让它把长任务拆成清单、逐条推进、
出错能恢复、知道何时停。

设计边界（讲义 §2）：
  - 不改主循环本身（那是执行引擎），只在其上加一层规划。
  - 不做多智能体——这是单 agent 的规划层。
"""

from __future__ import annotations
import time
from typing import Any


# ---------------------------------------------------------------------------
# 步骤 1 · TodoList：分解 + 状态机
# ---------------------------------------------------------------------------

class TodoList:
    """治迷失的核心（讲义 §4）：把大目标拆成有序、可跟踪的子任务，清单常驻上下文。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def write(self, texts: list[str]) -> None:
        """一次性写下分解后的清单，全部初始为 pending。"""
        self.items = [
            {"id": i + 1, "text": t, "status": "pending"}
            for i, t in enumerate(texts)
        ]

    def update(self, id: int, status: str) -> None:
        """更新指定子任务状态：pending / in_progress / completed / blocked。"""
        for it in self.items:
            if it["id"] == id:
                it["status"] = status
                return

    def insert(self, text: str) -> None:
        """重规划时插入新子任务（追加到清单末尾）。"""
        new_id = max((it["id"] for it in self.items), default=0) + 1
        self.items.append({"id": new_id, "text": text, "status": "pending"})

    def render(self) -> str:
        """注入上下文的样子（模型每轮都看得见）。"""
        mark = {
            "pending": "[ ]",
            "in_progress": "[~]",
            "completed": "[x]",
            "blocked": "[!]",
        }
        if not self.items:
            return "[任务清单为空]"
        return "\n".join(
            f"{mark.get(it['status'], '[?]')} {it['id']} {it['text']}"
            for it in self.items
        )

    def all_done(self) -> bool:
        """所有子任务都是 completed？"""
        if not self.items:
            return False
        return all(it["status"] == "completed" for it in self.items)

    def current_in_progress(self) -> dict[str, Any] | None:
        """返回当前第一个 in_progress 子任务，没有则返回 None。"""
        for it in self.items:
            if it["status"] == "in_progress":
                return it
        return None

    def next_pending(self) -> dict[str, Any] | None:
        """返回第一个 pending 子任务，没有则返回 None。"""
        for it in self.items:
            if it["status"] == "pending":
                return it
        return None

    def progress_summary(self) -> str:
        """以简短字符串概括当前进度。"""
        total = len(self.items)
        done = sum(1 for it in self.items if it["status"] == "completed")
        blocked = sum(1 for it in self.items if it["status"] == "blocked")
        return f"{done}/{total} 已完成" + (f"，{blocked} 个阻塞" if blocked else "")


# ---------------------------------------------------------------------------
# 单会话内的规划状态（模块级全局，供 tools 和 loop 共用）
# ---------------------------------------------------------------------------

TODO = TodoList()


# ---------------------------------------------------------------------------
# 步骤 4 · 错误恢复：瞬时重试 + 指数退避
# ---------------------------------------------------------------------------

class TransientError(Exception):
    """瞬时错误：可重试（如网络抖动、临时锁）。"""


class PermanentError(Exception):
    """永久错误：不应重试（如语法错误、权限不足）。"""


def with_retry(fn, max_tries: int = 3, base: float = 0.5):
    """用指数退避重试瞬时错误；超限返回 None，交由 blocked 逻辑处理。

    用法：
        result = with_retry(lambda: fragile_call(), max_tries=3)
        if result is None:
            TODO.update(task_id, "blocked")
    """
    for k in range(max_tries):
        try:
            return fn()
        except TransientError:
            if k < max_tries - 1:
                time.sleep(base * (2 ** k))
        except PermanentError:
            # 永久失败不重试，直接返回 None
            return None
    return None


# ---------------------------------------------------------------------------
# 步骤 4 · 反思：子任务完成后 / 失败后插入自我审视
# ---------------------------------------------------------------------------

class ReflectionTracker:
    """跟踪每个子任务的反思次数，防止无限反思套娃。

    规则：同一子任务最多反思 N 次（默认 2），超限后标记 blocked 或跳过。
    """

    def __init__(self, max_reflections_per_item: int = 2) -> None:
        self._counts: dict[int, int] = {}
        self._max = max_reflections_per_item

    def can_reflect(self, todo_id: int) -> bool:
        return self._counts.get(todo_id, 0) < self._max

    def record_reflection(self, todo_id: int) -> None:
        self._counts[todo_id] = self._counts.get(todo_id, 0) + 1

    def is_exhausted(self, todo_id: int) -> bool:
        return not self.can_reflect(todo_id)

    def reset(self) -> None:
        self._counts.clear()


# ---------------------------------------------------------------------------
# 步骤 5 · 无进展检测
# ---------------------------------------------------------------------------

class ProgressTracker:
    """追踪最近 N 步动作，检测是否原地打转或长时间无推进。

    规则：
      - 连续 MAX_NO_PROGRESS 步没有 todo 状态变更 → 触发重规划 / 求助。
      - 同一 (工具名 + 参数签名) 连续出现 MIN_REPEAT 次 → 卡死检测。
    """

    def __init__(self, max_no_progress: int = 5, min_repeat: int = 3) -> None:
        self._max_no_progress = max_no_progress
        self._min_repeat = min_repeat
        self._recent_actions: list[str] = []
        self._steps_since_progress = 0

    def record_action(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        """记录一步动作（工具调用）。"""
        args = arguments or {}
        # 用「工具名 + 排序后的参数键值对」作为简化签名
        sig_parts = [tool_name] + sorted(f"{k}={args[k]}" for k in args)
        sig = "|".join(sig_parts)
        self._recent_actions.append(sig)
        # 只保留最近一段窗口
        if len(self._recent_actions) > self._max_no_progress * 2:
            self._recent_actions = self._recent_actions[-self._max_no_progress * 2:]

    def mark_progress(self) -> None:
        """当 todo 有推进时调用，重置无进展计数。"""
        self._steps_since_progress = 0

    def mark_step_without_progress(self) -> None:
        self._steps_since_progress += 1

    def is_stuck(self) -> bool:
        """连续无进展步数超限？"""
        return self._steps_since_progress >= self._max_no_progress

    def is_looping(self) -> bool:
        """最近动作中同一签名反复出现？"""
        if len(self._recent_actions) < self._min_repeat * 2:
            return False
        # 检查最后 min_repeat 个动作是否完全相同
        recent = self._recent_actions[-self._min_repeat:]
        return len(set(recent)) == 1

    def stuck_reason(self) -> str:
        if self.is_looping():
            return f"检测到重复动作循环（最近 {self._min_repeat} 步相同），可能卡死。"
        if self.is_stuck():
            return f"连续 {self._max_no_progress} 步无 todo 推进，可能需要重规划。"
        return ""

    def reset(self) -> None:
        self._recent_actions.clear()
        self._steps_since_progress = 0


# ---------------------------------------------------------------------------
# 步骤 5 · 完成判据 + 预算
# ---------------------------------------------------------------------------

def verify_passed() -> bool:
    """验证任务是否真正完成的钩子。

    当前为占位实现：默认真实完成（因为模型有时会偷懒标记 completed）。
    可在后续日扩展为：运行测试套件 / 检查产物文件是否存在 / 调用 eval judge。
    """
    # 基础检查：至少有一个子任务被标记为 completed
    if not TODO.items:
        return False
    return TODO.all_done()


def stop_reason(max_steps: int, current_step: int) -> str | None:
    """超过步数上限或全部完成时返回终止原因，否则返回 None。"""
    if current_step >= max_steps:
        return f"已达步数上限（{max_steps} 步），当前进度：\n{TODO.render()}"
    if TODO.all_done() and verify_passed():
        return "任务完成。"
    return None
