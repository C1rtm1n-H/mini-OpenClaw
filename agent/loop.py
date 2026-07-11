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
from typing import Any

from agent.context import maybe_compact, truncate_observation
from tools.base import ToolRegistry


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry, system_prompt: str,
                 max_turns: int = 20):
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns          # 防死循环：硬上限

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
                tool = self.registry.get(name)
                if tool is None:
                    obs = f"错误：未知工具 {name}"
                else:
                    try:
                        arguments = call.get("arguments") or {}
                        if not isinstance(arguments, dict):
                            arguments = {}
                        obs = tool.run(**arguments)
                    except Exception as e:  # noqa: BLE001
                        obs = f"错误：工具 {name} 执行失败：{type(e).__name__}: {e}"
                messages.append({"role": "tool", "name": name,
                                 "tool_call_id": call.get("id") or name,
                                 "content": truncate_observation(str(obs))})

        return "[达到最大轮数上限，未完成任务]"
