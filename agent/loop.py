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
from typing import Any

from agent.context import maybe_compact, truncate_observation
from agent import permissions
from tools.base import ToolRegistry


def dispatch_tool_call(name: str, arguments: dict[str, Any], registry: ToolRegistry,
                        workdir: Path, auto_approve: bool) -> str:
    """权限判定 + 执行单次工具调用，返回 observation 文本。

    单独抽出来是为了让红队测试（security/redteam.py）能直接调用生产代码路径，
    而不是自己抄一份可能跑偏的判定逻辑。
    """
    verdict = permissions.check(name, arguments, workdir)
    if verdict == "deny":
        return "[权限层] 拒绝：越界写入 / 危险操作"
    if verdict == "confirm" and not auto_approve:
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
                 max_turns: int = 20, workdir: str | Path = ".", auto_approve: bool = False):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：硬上限
        self.workdir = Path(workdir)
        self.auto_approve = auto_approve    # True 时放行 confirm 级判定

    def run(self, user_task: str | list[dict[str, Any]]) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_task},
        ]
        for turn in range(self.max_turns):
            messages = maybe_compact(messages)
            try:
                assistant = self.backend.chat(messages, tools=self.registry.schemas())
            except Exception as e:  # noqa: BLE001
                return f"错误：后端调用失败：{e}"

            messages.append({"role": "assistant",
                             "content": assistant.get("content", ""),
                             "tool_calls": assistant.get("tool_calls", [])})

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                return assistant.get("content", "")

            for call in tool_calls:
                name = call.get("name", "")
                arguments = call.get("arguments") or {}
                if not isinstance(arguments, dict):
                    arguments = {}

                obs = dispatch_tool_call(name, arguments, self.registry, self.workdir, self.auto_approve)
                messages.append({"role": "tool", "name": name,
                                 "tool_call_id": call.get("id") or name,
                                 "content": truncate_observation(str(obs))})

        return "[达到最大轮数上限，未完成任务]"
