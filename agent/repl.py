"""交互式 REPL：Claude Code 式多轮对话界面。

常驻进程，循环读用户输入 → agent.send() 跑一整轮 ReAct → 打印最终答复；
借 AgentLoop 的 on_event/confirm_hook 回调把中间的工具调用过程实时渲染出来，
而不是像一次性任务模式那样只看到最后一段文字。
"""
from __future__ import annotations
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent.loop import AgentLoop

_HELP = """可用命令：
  /help   显示这条帮助
  /clear  清空对话历史（重新开始）
  /tools  列出当前可用工具
  /exit、/quit  退出
其它输入都会作为任务发给 agent。

长论文等复杂任务可在启动时自定义预算：
  python -m agent.cli --max-turns 100 --max-steps 160
其中 max-turns 是模型调用轮数，max-steps 是规划步数，且 max-steps 不能小于 max-turns。"""

_MAX_PREVIEW = 200


def _preview(text: str, limit: int = _MAX_PREVIEW) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...（共 {len(text)} 字符，已截断）"


class ReplUI:
    def __init__(self, console: Console):
        self.console = console

    def on_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "assistant_text":
            self.console.print(Text(event["content"], style="dim italic"))
        elif etype == "tool_call":
            args = ", ".join(f"{k}={v!r}" for k, v in event["arguments"].items())
            self.console.print(f"[bold cyan]●[/] [bold]{event['name']}[/]({args})")
        elif etype == "tool_result":
            self.console.print(f"  [dim]└[/] {_preview(event['observation'])}")

    def confirm(self, name: str, arguments: dict[str, Any]) -> bool:
        args = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
        self.console.print(f"[bold yellow]⚠ 需要确认[/]：{name}({args})")
        try:
            answer = self.console.input("  是否放行？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer == "y"


def run_repl(agent: AgentLoop) -> None:
    console = Console()
    ui = ReplUI(console)
    agent.on_event = ui.on_event
    agent.confirm_hook = ui.confirm

    console.print("[bold green]mini-OpenClaw[/] 交互模式（/exit 退出，/help 查看帮助）")
    console.print(
        "[dim]长任务可自定义轮次：python -m agent.cli "
        "--max-turns 100 --max-steps 160[/]"
    )

    while True:
        try:
            user_input = console.input("[bold cyan]>[/] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        stripped = user_input.strip()
        if not stripped:
            continue
        if stripped in ("/exit", "/quit"):
            break
        if stripped == "/help":
            console.print(_HELP)
            continue
        if stripped == "/clear":
            agent.reset()
            console.print("[dim]已清空对话历史。[/]")
            continue
        if stripped == "/tools":
            console.print("当前可用工具：" + ", ".join(agent.registry.names()))
            continue

        answer = agent.send(user_input)
        console.print(Panel(answer or "[无输出]", title="mini-OpenClaw", border_style="green"))
