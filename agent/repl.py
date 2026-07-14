"""交互式 REPL：Claude Code 式多轮对话界面。

常驻进程，循环读用户输入 → agent.send() 跑一整轮 ReAct → 打印最终答复；
借 AgentLoop 的 on_event/confirm_hook 回调把中间的工具调用过程实时渲染出来，
而不是像一次性任务模式那样只看到最后一段文字。
"""
from __future__ import annotations
import sys
import platform
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent.loop import AgentLoop

_IS_WINDOWS = platform.system() == "Windows"

_COMMANDS: dict[str, str] = {
    "/skills":   "列出所有 skill 及编号，用 /skill <编号> 切换启用/禁用",
    "/skill":    "/skill <编号> ... — 切换对应 skill 的启用/禁用（支持多个编号空格分隔）",
    "/tools":    "列出当前可用工具",
    "/clear":    "清空对话历史（重新开始）",
    "/exit":     "退出（同 /quit）",
    "/quit":     "退出（同 /exit）",
}

_MAX_PREVIEW = 200


# ---------------------------------------------------------------------------
# 单键读取（仅用于确认放行 Enter / 拒绝 Esc）
# ---------------------------------------------------------------------------

def _read_single_key() -> str:
    """跨平台读取单个按键，返回 'ENTER' / 'ESC' / 'CTRL_C' / 其它字符。"""
    if _IS_WINDOWS:
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\r", b"\n"):
            return "ENTER"
        if ch == b"\x1b":
            return "ESC"
        if ch == b"\x03":
            raise KeyboardInterrupt
        return ch.decode("utf-8", errors="replace")
    else:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                return "ENTER"
            if ch == "\x1b":
                return "ESC"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
        self.console.print(
            f"  [bold]Enter[/]=放行  [bold]N[/]=拒绝"
        )
        while True:
            try:
                key = _read_single_key()
            except (EOFError, KeyboardInterrupt):
                return False
            if key == "ENTER":
                return True
            if key.lower() == "n":
                return False


# ---------------------------------------------------------------------------
# 命令提示
# ---------------------------------------------------------------------------

def _show_command_hint(console: Console, user_input: str) -> None:
    """输入 / 开头但不匹配命令时展示可用命令。"""
    console.print(f"[yellow]未知命令：{user_input}[/]")
    console.print("[dim]可用命令：[/]")
    for cmd, desc in _COMMANDS.items():
        console.print(f"  [bold]{cmd:<10}[/] {desc}")


# ---------------------------------------------------------------------------
# Skill 管理（编号切换）
# ---------------------------------------------------------------------------

def _cmd_skills(console: Console) -> None:
    """列出所有 skill 及编号。"""
    from skills.loader import load_all_skills

    skills = load_all_skills()
    if not skills:
        console.print("[dim]未发现任何 skill。[/]")
        return

    table = Table(title="Skills 列表")
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("状态")
    table.add_column("名称", style="bold")
    table.add_column("描述")

    for i, s in enumerate(skills, 1):
        status = "[green]✓ 启用[/]" if s.enabled else "[red]✗ 禁用[/]"
        table.add_row(str(i), status, s.name, s.description[:60])

    console.print(table)
    console.print("[dim]使用 /skill <编号> 切换启用/禁用（如 /skill 3）。[/]")


def _cmd_skill_toggle(console: Console, arg: str) -> None:
    """按编号切换 skill 启用/禁用。支持多个编号空格分隔（如 /skill 2 3 5）。"""
    from skills.loader import load_all_skills, toggle_skill

    if not arg.strip():
        console.print("[red]用法：/skill <编号> ...（如 /skill 2 3 5）。先用 /skills 查看编号。[/]")
        return

    ids: list[int] = []
    for part in arg.strip().split():
        try:
            ids.append(int(part))
        except ValueError:
            console.print(f"[red]无效编号：{part}，已跳过。[/]")

    if not ids:
        console.print("[red]未提供有效编号。[/]")
        return

    skills = load_all_skills()
    for idx in ids:
        if idx < 1 or idx > len(skills):
            console.print(f"[red]编号 {idx} 超出范围（共 {len(skills)} 个），已跳过。[/]")
            continue
        s = skills[idx - 1]
        new_enabled, _ = toggle_skill(s.name)
        status = "[green]✓ 启用[/]" if new_enabled else "[red]✗ 禁用[/]"
        console.print(f"{status} [bold]{s.name}[/]")


# ---------------------------------------------------------------------------
# REPL 主循环
# ---------------------------------------------------------------------------

def run_repl(agent: AgentLoop) -> None:
    # 修复 Windows GBK 编码下 Rich 退格删除中文光标错位的问题
    console = Console(force_terminal=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    ui = ReplUI(console)
    agent.on_event = ui.on_event
    agent.confirm_hook = ui.confirm

    console.print("[bold green]mini-OpenClaw[/] 交互模式")
    console.print("[dim]输入 / 查看可用命令")
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

        # ── 命令分发 ──
        if stripped in ("/exit", "/quit"):
            break

        if stripped == "/clear":
            agent.reset()
            console.print("[dim]已清空对话历史。[/]")
            continue

        if stripped == "/tools":
            console.print("当前可用工具：" + ", ".join(agent.registry.names()))
            continue

        if stripped == "/skills":
            _cmd_skills(console)
            continue

        if stripped.startswith("/skill"):
            arg = stripped[len("/skill"):].strip()
            _cmd_skill_toggle(console, arg)
            continue

        # 以 / 开头但不匹配任何命令 → 展示可用命令
        if stripped.startswith("/"):
            _show_command_hint(console, stripped)
            continue

        # ── 正常任务 ──
        answer = agent.send(user_input)
        console.print(Panel(answer or "[无输出]", title="mini-OpenClaw", border_style="green"))
