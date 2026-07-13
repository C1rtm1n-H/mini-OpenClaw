"""ReAct 主循环（Agent 的心脏）。

  while 没到最终答复:
      assistant = backend.chat(messages, tools)      # 模型这一步：思考 or 调工具
      if assistant 有 tool_calls:
          for call in tool_calls:
              obs = registry.get(call.name).run(**call.arguments)   # 执行工具
              messages.append(tool_result(obs))                     # 注入 observation
      else:
          return assistant.content                                 # 最终答复

Day4 你要把下面的 run() 真正实现出来（随工具集扩展逐步完善）。骨架已给出结构与防呆上限。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from agent.context import maybe_compact, truncate_observation
from agent import permissions
from tools.base import ToolRegistry


def dispatch_tool_call(name: str, arguments: dict[str, Any], registry: ToolRegistry,
                        workdir: Path, auto_approve: bool,
                        confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None) -> str:
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
    try:
        return tool.run(**arguments)
    except Exception as e:  # noqa: BLE001
        return f"错误：工具 {name} 执行失败：{type(e).__name__}: {e}"


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry, system_prompt: str,
                 max_turns: int = 20, workdir: str | Path = ".", auto_approve: bool = False,
                 on_event: Callable[[dict[str, Any]], None] | None = None,
                 confirm_hook: Callable[[str, dict[str, Any]], bool] | None = None):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：硬上限
        self.workdir = Path(workdir)
        self.auto_approve = auto_approve    # True 时放行 confirm 级判定
        self.on_event = on_event            # 交互界面渲染工具调用过程用；None 时零行为变化
        self.confirm_hook = confirm_hook    # 交互界面真实询问用户 y/N；None 时 confirm 级一律拦截
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    def reset(self) -> None:
        """清空对话历史，只留系统提示词；供 REPL 的 /clear 用。"""
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def send(self, user_input: str | list[dict[str, Any]]) -> str:
        """追加一轮用户输入，跑 ReAct 直到给出最终答复；self.messages 跨调用累积，支持多轮对话。"""
        self.messages.append({"role": "user", "content": user_input})

        for turn in range(self.max_turns):
            self.messages = maybe_compact(self.messages)
            try:
                assistant = self.backend.chat(self.messages, tools=self.registry.schemas())
            except Exception as e:  # noqa: BLE001
                return f"错误：后端调用失败：{e}"

            self.messages.append({"role": "assistant",
                                  "content": assistant.get("content", ""),
                                  "tool_calls": assistant.get("tool_calls", [])})

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return assistant.get("content", "")

            if assistant.get("content"):
                self._emit({"type": "assistant_text", "content": assistant["content"]})

            for call in tool_calls:
                name = call.get("name", "")
                arguments = call.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}

                self._emit({"type": "tool_call", "name": name, "arguments": arguments})
                obs = dispatch_tool_call(name, arguments, self.registry, self.workdir,
                                          self.auto_approve, self.confirm_hook)
                self._emit({"type": "tool_result", "name": name, "observation": str(obs)})
                self.messages.append({"role": "tool", "name": name,
                                      "tool_call_id": call.get("id") or name,
                                      "content": truncate_observation(str(obs))})

        return "[达到最大轮数上限，未完成任务]"

    def run(self, user_task: str | list[dict[str, Any]]) -> str:
        """单次任务的薄封装，等价于 send()；供一次性 CLI 调用和 eval/redteam 脚本使用。"""
        return self.send(user_task)
