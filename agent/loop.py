"""ReAct 主循环（Agent 的心脏）+ Day 8 规划层集成。

  while 没到最终答复:
      assistant = backend.chat(messages, tools)      # 模型这一步：思考 or 调工具
      if assistant 有 tool_calls:
          for call in tool_calls:
              obs = registry.get(call.name).run(**call.arguments)   # 执行工具
              messages.append(tool_result(obs))                     # 注入 observation
      else:
          return assistant.content                                 # 最终答复

Day 8 新增（规划层）：
  - 每轮注入 TodoList 状态，让模型始终知道"整体到哪了"。
  - 无进展检测 + 循环检测，防止原地打转烧 token。
  - 完成判据 + 步数预算，任务能正常终止。
  - 反思/重试接入点（通过工具结果反馈触发）。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from agent.context import maybe_compact, truncate_observation
from agent import permissions
from agent.planning import (
    TODO, ProgressTracker, ReflectionTracker,
    stop_reason, TransientError, PermanentError, with_retry,
)
from tools.base import ToolRegistry


def dispatch_tool_call(name: str, arguments: dict[str, Any], registry: ToolRegistry,
                       workdir: Path, auto_approve: bool,
                       confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None,
                       ) -> str:
    """权限判定 + 执行单次工具调用，返回 observation 文本。

    单独抽出来是为了让红队测试（security/redteam.py）能直接调用生产代码路径，
    而不是自己抄一份可能跑偏的判定逻辑。

    confirm_hook：verdict=="confirm" 且未 auto_approve 时，交互场景（agent/repl.py）
    可以传一个"问用户 y/N"的回调；不传时行为和以前一样——直接拦截。
    """
    verdict = permissions.check(name, arguments, workdir)
    if verdict == "deny":
        return "[权限层] 拒绝：越界写入 / 危险操作"
    if verdict == "confirm" and not auto_approve:
        if confirm_hook is None or not confirm_hook(name, arguments):
            return f"[权限层] 需确认：{name}({arguments}) —— 已拦截（演示：默认不放行）"

    tool = registry.get(name)
    if tool is None:
        return f"错误：未知工具 {name}"

    def _execute() -> str:
        return tool.run(**arguments)

    try:
        return _execute()
    except TransientError as e:
        # 瞬时错误：用指数退避重试
        result = with_retry(_execute, max_tries=3, base=0.5)
        if result is not None:
            return result
        return f"错误：工具 {name} 瞬时错误重试 3 次后仍失败：{e}"
    except PermanentError as e:
        return f"错误：工具 {name} 永久失败，不会重试：{e}"
    except Exception as e:  # noqa: BLE001
        return f"错误：工具 {name} 执行失败：{type(e).__name__}: {e}"


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry, system_prompt: str,
                 max_turns: int = 20, max_steps: int = 40,
                 workdir: str | Path = ".", auto_approve: bool = False,
                 on_event: Callable[[dict[str, Any]], None] | None = None,
                 confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：模型调用次数硬上限
        self.max_steps = max_steps           # Day 8：步数预算上限（>= max_turns）
        self.workdir = Path(workdir)
        self.auto_approve = auto_approve    # True 时放行 confirm 级判定
        self.on_event = on_event            # 交互界面渲染工具调用过程用；None 时零行为变化
        self.confirm_hook = confirm_hook    # 交互界面真实询问用户 y/N；None 时 confirm 级一律拦截
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Day 8 规划层组件
        self.progress_tracker = ProgressTracker(max_no_progress=5, min_repeat=3)
        self.reflection_tracker = ReflectionTracker(max_reflections_per_item=2)

    def reset(self) -> None:
        """清空对话历史，只留系统提示词；供 REPL 的 /clear 用。"""
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.progress_tracker.reset()
        self.reflection_tracker.reset()
        # 清空 TodoList（新会话）
        TODO.items.clear()

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event)

    # ------------------------------------------------------------------
    # Day 8 步骤 3 · 每轮注入 todo 状态
    # ------------------------------------------------------------------

    def _inject_todo(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """防漂移的根本手段（讲义 §8.3）：每轮把当前 todo 状态拼进上下文。

        模型每步都知道"整体到哪了、下一条做什么"，避免重复已完成项、遗漏未完成项。
        """
        if not TODO.items:
            return messages

        todo_prompt = (
            "# 当前任务清单（推进它，别跑偏）\n"
            + TODO.render()
            + f"\n\n进度：{TODO.progress_summary()}。"
        )

        next_pending = TODO.next_pending()
        if next_pending:
            todo_prompt += f"\n下一项待处理：{next_pending['id']} {next_pending['text']}"

        current = TODO.current_in_progress()
        if current:
            todo_prompt += f"\n当前进行中：{current['id']} {current['text']}"

        # 注入：在 system prompt 和最近一轮 user 之间插入，作为系统级提醒
        # 找到 system 消息的位置，在它后面插入
        for i, m in enumerate(messages):
            if m.get("role") == "system" and "当前任务清单" not in str(m.get("content", "")):
                # 在最后一个 system 消息后面插入
                last_system_idx = max(
                    j for j, msg in enumerate(messages)
                    if msg.get("role") == "system"
                )
                result = list(messages)
                result.insert(last_system_idx + 1, {
                    "role": "system",
                    "content": todo_prompt,
                })
                return result
        return messages

    # ------------------------------------------------------------------
    # Day 8 步骤 5 · 无进展 / 卡死检测
    # ------------------------------------------------------------------

    def _check_stuck(self) -> str | None:
        """检测是否原地打转；如果是，返回干预消息，否则返回 None。"""
        if self.progress_tracker.is_looping():
            return (
                f"[规划层] {self.progress_tracker.stuck_reason()}\n"
                "请换一条路径尝试，或把当前子任务标为 blocked 并推进下一条。\n"
                f"当前清单：\n{TODO.render()}"
            )
        if self.progress_tracker.is_stuck():
            return (
                f"[规划层] {self.progress_tracker.stuck_reason()}\n"
                "请检查是否需要重新规划（用 todo_write 重写清单），"
                "或把卡住的子任务标为 blocked 先做别的。\n"
                f"当前清单：\n{TODO.render()}"
            )
        return None

    # ------------------------------------------------------------------
    # Day 8 步骤 4 · 工具结果注入反思提示
    # ------------------------------------------------------------------

    def _maybe_reflection_prompt(self, tool_name: str,
                                  observation: str) -> str | None:
        """在关键节点注入反思提示：工具失败时 / 子任务完成时。"""
        # 工具失败 → 建议反思
        if "错误" in observation or "失败" in observation:
            current = TODO.current_in_progress()
            if current:
                tid = current["id"]
                if self.reflection_tracker.can_reflect(tid):
                    self.reflection_tracker.record_reflection(tid)
                    return (
                        f"[反思提示] 子任务 {tid} 遇到错误，请审视："
                        f"错误原因是什么？能否换个方式完成？"
                        f"（剩余反思次数："
                        f"{self.reflection_tracker._max - self.reflection_tracker._counts.get(tid, 0)}）"
                    )
                else:
                    return (
                        f"[反思上限] 子任务 {tid} 已反思/重试超限，"
                        f"建议将其标为 blocked 并推进下一条。"
                    )

        # 子任务刚被标记为 completed → 快速自检
        if tool_name == "update_todo":
            args = {}  # 无法在这里拿到 arguments，但可以从 observation 推断
            if "已完成" in observation:
                current = TODO.current_in_progress()
                if current is None:
                    return "[反思提示] 子任务已标记完成。请确认产物确实符合预期后再推进下一条。"
        return None

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def send(self, user_input: str | list[dict[str, Any]]) -> str:
        """追加一轮用户输入，跑 ReAct 直到给出最终答复；self.messages 跨调用累积，支持多轮对话。"""
        self.messages.append({"role": "user", "content": user_input})

        step_count = 0  # Day 8：步数计数器

        for turn in range(self.max_turns):
            step_count += 1

            # --- Day 8 步骤 5：步数预算检查 ---
            reason = stop_reason(self.max_steps, step_count)
            if reason:
                return reason

            # --- Day 8 步骤 5：卡死检测 ---
            stuck_msg = self._check_stuck()
            if stuck_msg:
                # 注入干预消息，尝试唤醒模型
                self.messages.append({"role": "user", "content": stuck_msg})

            # --- Day 8 步骤 3：每轮注入 todo 状态 ---
            ctx_messages = self._inject_todo(self.messages)

            # --- 上下文压缩 ---
            self.messages = maybe_compact(self.messages)
            ctx_messages = maybe_compact(ctx_messages)

            # --- 调用后端 ---
            try:
                assistant = self.backend.chat(ctx_messages, tools=self.registry.schemas())
            except Exception as e:  # noqa: BLE001
                return f"错误：后端调用失败：{e}"

            self.messages.append({"role": "assistant",
                                  "content": assistant.get("content", ""),
                                  "tool_calls": assistant.get("tool_calls", [])})

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                # 没有工具调用 → 最终答复
                # Day 8：如果 todo 未全部完成，追加提醒
                if TODO.items and not TODO.all_done():
                    remaining = [it for it in TODO.items if it["status"] != "completed"]
                    if remaining:
                        reminder = (
                            f"\n\n[提醒] 任务清单尚有 {len(remaining)} 项未完成：\n"
                            + "\n".join(
                                f"  {it['id']} [{it['status']}] {it['text']}"
                                for it in remaining
                            )
                        )
                        return (assistant.get("content", "") or "") + reminder
                return assistant.get("content", "")

            if assistant.get("content"):
                self._emit({"type": "assistant_text", "content": assistant["content"]})

            # --- 执行工具调用 ---
            had_todo_progress = False  # 本轮是否有 todo 推进

            for call in tool_calls:
                name = call.get("name", "")
                arguments = call.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}

                self._emit({"type": "tool_call", "name": name, "arguments": arguments})

                # Day 8 步骤 5：记录动作供卡死检测
                self.progress_tracker.record_action(name, arguments)

                obs = dispatch_tool_call(name, arguments, self.registry, self.workdir,
                                          self.auto_approve, self.confirm_hook)

                # Day 8 步骤 4：工具结果中注入反思提示
                reflection = self._maybe_reflection_prompt(name, str(obs))
                if reflection:
                    obs = str(obs) + "\n\n" + reflection

                self._emit({"type": "tool_result", "name": name, "observation": str(obs)})

                # 检测 todo 推进（调用了 todo_write 或 update_todo）
                if name in ("todo_write", "update_todo"):
                    had_todo_progress = True

                self.messages.append({"role": "tool", "name": name,
                                      "tool_call_id": call.get("id") or name,
                                      "content": truncate_observation(str(obs))})

            # Day 8 步骤 5：更新推进状态
            if had_todo_progress:
                self.progress_tracker.mark_progress()
            else:
                self.progress_tracker.mark_step_without_progress()

        return "[达到最大轮数上限，未完成任务]"

    def run(self, user_task: str | list[dict[str, Any]]) -> str:
        """单次任务的薄封装，等价于 send()；供一次性 CLI 调用和 eval/redteam 脚本使用。"""
        return self.send(user_task)
