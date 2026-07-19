"""ReAct 主循环（Agent 的心脏）+ Day 8 规划层集成 + Day 9 可观测性。

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

Day 9 新增（可观测性）：
  - Tracer 把每次 LLM/工具调用记成 span，可回放。
  - token 用量从 backend 返回的 usage 自动采集。
"""
from __future__ import annotations
from pathlib import Path
import re
import time
from typing import Any, Callable

from agent.context import maybe_compact, truncate_observation
from agent import permissions
from agent.planning import (
    TODO, ProgressTracker, ReflectionTracker,
    stop_reason, TransientError, PermanentError, with_retry,
)
from agent.tracer import Tracer
from tools.base import ToolRegistry


def _is_transient_backend_error(error: Exception) -> bool:
    """判断后端错误是否值得重试，避免对 400/鉴权/代码错误重复烧请求。"""
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True

    class_name = type(error).__name__.lower()
    if any(marker in class_name for marker in (
        "timeout", "connecterror", "networkerror", "protocolerror",
        "readerror", "writeerror", "transporterror",
    )):
        return True

    message = str(error).lower()
    status_match = re.search(r"(?:http\s*)?(\d{3})", message)
    if status_match:
        status = int(status_match.group(1))
        return status == 408 or status == 429 or 500 <= status <= 599

    transient_markers = (
        "timed out", "timeout", "connection reset", "connection refused",
        "temporarily unavailable", "remote host", "server disconnected",
        "远程主机", "连接", "网络",
    )
    return any(marker in message for marker in transient_markers)


def dispatch_tool_call(name: str, arguments: dict[str, Any], registry: ToolRegistry,
                       workdir: Path, auto_approve: bool,
                       confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None,
                       task_scopes: tuple[Path, ...] = (),
                       readonly_downgrade: bool = False,
                       ) -> str:
    """权限判定 + 执行单次工具调用，返回 observation 文本。

    单独抽出来是为了让红队测试（security/redteam.py）能直接调用生产代码路径，
    而不是自己抄一份可能跑偏的判定逻辑。

    confirm_hook：verdict=="confirm" 且未 auto_approve 时，交互场景（agent/repl.py）
    可以传一个"问用户 y/N"的回调；不传时行为和以前一样——直接拦截。
    """
    verdict = permissions.check(
        name, arguments, workdir, task_scopes, readonly_downgrade
    )
    if verdict == "deny":
        return "[权限层] 拒绝：路径超出当前用户任务作用域，或操作不安全"
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
                 confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None,
                 tracer: Tracer | None = None,
                 trajectory_sink: Callable[[dict[str, Any]], None] | None = None):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：模型调用次数硬上限
        self.max_steps = max_steps           # Day 8：步数预算上限（>= max_turns）
        self.workdir = Path(workdir)
        self.auto_approve = auto_approve    # True 时放行 confirm 级判定
        self.on_event = on_event            # 交互界面渲染工具调用过程用；None 时零行为变化
        self.trajectory_sink = trajectory_sink  # eval harness 收集完整轨迹用；None 时零行为变化
        self.confirm_hook = confirm_hook    # 交互界面真实询问用户 y/N；None 时 confirm 级一律拦截
        self.tracer = tracer or Tracer()    # Day 9：可观测性（无 session 时用内存版）
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        self.task_scopes: tuple[Path, ...] = ()
        self.readonly_downgrade = False

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
        self.task_scopes = ()
        self.readonly_downgrade = False

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _trace_eval(self, event: dict[str, Any]) -> None:
        """把完整运行事件交给 eval harness；默认关闭，不影响正常 CLI/REPL。"""
        if self.trajectory_sink is not None:
            self.trajectory_sink(event)

    def _chat_with_retry(self, messages: list[dict[str, Any]], max_tries: int = 3) -> dict[str, Any]:
        """调用模型；只对网络、超时、429 和 5xx 做有限指数退避重试。"""
        last_error: Exception | None = None
        for attempt in range(1, max_tries + 1):
            try:
                return self.tracer.span(
                    "llm", "decide",
                    lambda: self.backend.chat(messages, tools=self.registry.schemas()),
                    attempt=attempt,
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
                transient = _is_transient_backend_error(error)
                if not transient:
                    raise RuntimeError(f"后端永久错误，不重试：{error}") from error
                if attempt >= max_tries:
                    break
                delay = 0.5 * (2 ** (attempt - 1))
                self._emit({
                    "type": "assistant_text",
                    "content": f"[后端恢复] 第 {attempt} 次调用失败，{delay:.1f}s 后重试：{error}",
                })
                time.sleep(delay)
        raise RuntimeError(
            f"后端瞬时错误重试 {max_tries} 次后仍失败：{last_error}。"
            "本轮已安全结束；网络恢复后可在交互模式直接重试原指令。"
        ) from last_error

    def _detect_task_scopes(self, user_input: str | list[dict[str, Any]]) -> tuple[Path, ...]:
        """从用户输入提取明确存在的 Windows 绝对路径作为授权根。"""
        if not isinstance(user_input, str):
            return ()
        quoted = re.findall(r'["\']([A-Za-z]:[\\/][^"\']+)["\']', user_input)
        unquoted = re.findall(r'([A-Za-z]:[\\/][^\s"\'<>|?*]+)', user_input)
        roots: list[Path] = []
        for raw in quoted + unquoted:
            raw = raw.rstrip(",，。；;:：)]}）】")
            candidate = Path(raw).resolve()
            if not candidate.exists():
                continue
            root = candidate
            if root not in roots:
                roots.append(root)
        return tuple(roots)

    def _inject_scope(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.task_scopes:
            return messages
        roots = "\n".join(f"- {scope}" for scope in self.task_scopes)
        result = list(messages)
        result.insert(1, {
            "role": "system",
            "content": (
                "# 当前任务硬作用域\n"
                f"仅允许读取、搜索和写入以下目标路径：\n{roots}\n"
                "若目标是单个 PDF，仅额外允许其同名 TXT 缓存。\n"
                "不得读取或审计外层 mini-OpenClaw 宿主工程。"
            ),
        })
        return result

    @staticmethod
    def _requests_full_experiment(user_input: str | list[dict[str, Any]]) -> bool:
        if not isinstance(user_input, str):
            return False
        text = user_input.lower()
        markers = (
            "完整跑", "跑一遍", "完整复现", "复现论文里的结果", "复现实验结果",
            "开始训练", "执行训练", "下载数据集", "full training", "run the experiment",
            "reproduce the results", "download the dataset",
        )
        return any(marker in text for marker in markers)

    def _inject_execution_policy(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.readonly_downgrade:
            return messages
        result = list(messages)
        result.insert(1, {
            "role": "system",
            "content": (
                "# 强制只读降级策略\n"
                "用户请求了完整训练、评估或数据下载。必须主动拒绝执行高成本步骤，"
                "并降级为静态审计、配置检查、--help/版本/语法等毫秒级验证和复现计划。\n"
                "最终答复开头必须明确写：『已拒绝执行完整训练和大型数据下载；"
                "本次已按安全策略降级为静态分析与轻量验证。』\n"
                "不要声称已复现论文结果；只能说明已完成审计或复现计划。"
            ),
        })
        return result

    # ------------------------------------------------------------------
    # Day 8 步骤 3 · 每轮注入 todo 状态
    # ------------------------------------------------------------------

    def _inject_todo(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """防漂移的根本手段（讲义 §8.3）：每轮把当前 todo 状态拼进上下文。

        模型每步都知道"整体到哪了、下一条做什么"，避免重复已完成项、遗漏未完成项。

        Day 9 优化（前缀缓存友好排序，讲义 §7.1）：
        把 todo 状态追加到上下文**末尾**（role="user"），而不是插入到 system prompt
        后面。这样稳定的 system prompt 永远是完整可缓存的前缀，而每轮变化的 todo
        只影响最后一条消息——前缀缓存命中率最大化。
        """
        if not TODO.items:
            return messages

        todo_prompt = (
            "# 当前单层主清单（推进它，别跑偏）\n"
            + TODO.render()
            + f"\n\n进度：{TODO.progress_summary()}。"
            + "\n已有主清单，禁止为当前子任务再次调用 todo_write 创建小清单；"
              "直接执行并用 update_todo 更新这里的原任务 ID。"
        )

        next_pending = TODO.next_pending()
        if next_pending:
            todo_prompt += f"\n下一项待处理：{next_pending['id']} {next_pending['text']}"

        current = TODO.current_in_progress()
        if current:
            todo_prompt += f"\n当前进行中：{current['id']} {current['text']}"

        # Day 9：追加到末尾而不是插入到 system 后面 → 前缀缓存友好
        result = list(messages)
        result.append({"role": "user", "content": todo_prompt})
        return result

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
                "请检查是否需要整体重规划（必要时用 todo_write(replace=true) 重写一次主清单），"
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
        # 每次用户输入都是一个新的执行任务。保留对话历史用于追问，但不能沿用
        # 上一任务已经完成的 TODO/卡死计数，否则会在调用模型前直接返回“任务完成”。
        TODO.items.clear()
        self.progress_tracker.reset()
        self.reflection_tracker.reset()
        self.task_scopes = self._detect_task_scopes(user_input)
        self.readonly_downgrade = self._requests_full_experiment(user_input)
        self.messages.append({"role": "user", "content": user_input})
        self._trace_eval({
            "type": "task_start",
            "input": user_input,
            "max_turns": self.max_turns,
            "max_steps": self.max_steps,
            "readonly_downgrade": self.readonly_downgrade,
        })

        # 如果上一轮任务已全部完成，清空遗留的 TODO，避免 stop_reason()
        # 在新一轮对话的第一轮迭代就误判为"任务完成"。
        if TODO.items and TODO.all_done():
            TODO.items.clear()

        step_count = 0  # Day 8：步数计数器

        for turn in range(self.max_turns):
            step_count += 1

            # --- Day 8 步骤 5：步数预算检查 ---
            reason = stop_reason(self.max_steps, step_count)
            if reason:
                self._trace_eval({"type": "final", "status": "max_steps", "content": reason, "turn": turn})
                return reason

            # --- Day 8 步骤 5：卡死检测 ---
            stuck_msg = self._check_stuck()
            if stuck_msg:
                # 注入干预消息，尝试唤醒模型
                self.messages.append({"role": "user", "content": stuck_msg})

            # --- Day 8 步骤 3：每轮注入 todo 状态 ---
            ctx_messages = self._inject_todo(self.messages)
            ctx_messages = self._inject_scope(ctx_messages)
            ctx_messages = self._inject_execution_policy(ctx_messages)

            # --- 上下文压缩 ---
            self.messages = maybe_compact(self.messages)
            ctx_messages = maybe_compact(ctx_messages)

            # --- 调用后端（瞬时故障有限重试；每次尝试均写入 trace）---
            try:
                assistant = self._chat_with_retry(ctx_messages)
                # 从后端返回提取 usage，记入 LLM span
                usage = assistant.get("usage", {})
                if usage:
                    self.tracer.update_last(
                        "llm",
                        tokens=usage.get("total_tokens"),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                    )
            except Exception as e:  # noqa: BLE001
                error_msg = f"错误：后端调用失败：{e}"
                self._trace_eval({"type": "final", "status": "backend_error", "content": error_msg, "turn": turn, "error": str(e)})
                return error_msg

            self._trace_eval({
                "type": "llm",
                "turn": turn,
                "content": assistant.get("content", ""),
                "tool_calls": assistant.get("tool_calls", []),
                "usage": usage,
            })

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
                        final_text = (assistant.get("content", "") or "") + reminder
                        self._trace_eval({"type": "final", "status": "completed_with_reminder", "content": final_text, "turn": turn})
                        return final_text
                final_text = assistant.get("content", "")
                self._trace_eval({"type": "final", "status": "completed", "content": final_text, "turn": turn})
                return final_text

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
                self._trace_eval({
                    "type": "tool_call",
                    "turn": turn,
                    "tool_call_id": call.get("id") or name,
                    "name": name,
                    "arguments": arguments,
                })

                # Day 8 步骤 5：记录动作供卡死检测
                self.progress_tracker.record_action(name, arguments)

                # Day 9：用 Tracer 包裹工具执行
                obs = self.tracer.span(
                    "tool", name,
                    lambda n=name, a=arguments: dispatch_tool_call(
                        n, a, self.registry, self.workdir,
                        self.auto_approve, self.confirm_hook,
                        self.task_scopes,
                        self.readonly_downgrade,
                    ),
                )

                # Day 8 步骤 4：工具结果中注入反思提示
                reflection = self._maybe_reflection_prompt(name, str(obs))
                if reflection:
                    obs = str(obs) + "\n\n" + reflection

                observation = str(obs)
                self._emit({"type": "tool_result", "name": name, "observation": observation})
                returncode_match = re.search(r"\[returncode=(\d+)\]", observation)
                self._trace_eval({
                    "type": "tool_result",
                    "turn": turn,
                    "tool_call_id": call.get("id") or name,
                    "name": name,
                    "observation": observation,
                    "ok": not observation.startswith("错误：") and "[权限层]" not in observation and "[沙箱] 拒绝" not in observation,
                    "permission_blocked": "[权限层]" in observation,
                    "returncode": int(returncode_match.group(1)) if returncode_match else (0 if name == "bash" else None),
                })

                # 只有实际创建/更新成功才算推进；被拒绝的嵌套 todo_write 不能
                # 重置卡死计数，否则模型可反复建小清单直到耗尽轮次。
                if (
                    (name == "todo_write" and str(obs).startswith("任务主清单"))
                    or (name == "update_todo" and "已标记为" in str(obs))
                ):
                    had_todo_progress = True

                self.messages.append({"role": "tool", "name": name,
                                      "tool_call_id": call.get("id") or name,
                                      "content": truncate_observation(str(obs))})

            # Day 8 步骤 5：更新推进状态
            if had_todo_progress:
                self.progress_tracker.mark_progress()
            else:
                self.progress_tracker.mark_step_without_progress()

        final_text = "[达到最大轮数上限，未完成任务]"
        self._trace_eval({"type": "final", "status": "max_turns", "content": final_text, "turn": self.max_turns})
        return final_text

    def run(self, user_task: str | list[dict[str, Any]]) -> str:
        """单次任务的薄封装，等价于 send()；供一次性 CLI 调用和 eval/redteam 脚本使用。"""
        return self.send(user_task)
