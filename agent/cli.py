"""命令行入口。

用法：
  python -m agent.cli --selfcheck          # Day1：自检骨架是否装好
  python -m agent.cli "创建 hello.py 并运行"  # Day5 起：真正跑任务（v1 在 Day6）
  python -m agent.cli                      # 无参数进入交互式多轮对话
"""
from __future__ import annotations
import argparse
import shlex
import sys

from tools.base import ToolRegistry, build_default_registry
from agent.prompts import SYSTEM_PROMPT
from skills.loader import load_skills, skills_catalog


def _start_mcp(reg: ToolRegistry, command: list[str]) -> object:
    from mcp.client import MCPClient, register_mcp_tools

    client = MCPClient(command)
    client.start()
    register_mcp_tools(reg, client)
    return client


def selfcheck(mcp_commands: list[str] | None = None) -> int:
    print("== mini-OpenClaw 自检 ==")
    ok = True
    clients = []
    try:
        reg = build_default_registry()
        print(f"[ok] 工具注册表加载成功，当前内置工具数：{len(reg)}")
        print("[ok] 内置工具：" + ", ".join(reg.names()))
    except Exception as e:  # noqa
        print(f"[FAIL] 工具注册表：{e}"); ok = False
        reg = None

    if reg is not None and mcp_commands:
        for raw in mcp_commands:
            try:
                client = _start_mcp(reg, shlex.split(raw))
                clients.append(client)
                print(f"[ok] MCP 已接入：{raw}")
            except Exception as e:  # noqa
                print(f"[FAIL] MCP {raw}：{e}"); ok = False
        if mcp_commands:
            print(f"[ok] 接入 MCP 后工具数：{len(reg)}")
            print("[ok] 当前工具：" + ", ".join(reg.names()))

    try:
        from backend.fake_backend import FakeBackend
        FakeBackend().chat([{"role": "user", "content": "hi"}], tools=[])
        print("[ok] FakeBackend 可用（未配 DEEPSEEK_API_KEY 时的离线占位后端）")
    except Exception as e:  # noqa
        print(f"[FAIL] FakeBackend：{e}"); ok = False

    try:
        from agent.loop import AgentLoop  # noqa
        print("[ok] 主循环模块可导入")
    except Exception as e:  # noqa
        print(f"[FAIL] 主循环：{e}"); ok = False

    for client in clients:
        close = getattr(client, "close", None)
        if close:
            close()

    print("== 自检", "通过" if ok else "未通过", "==")
    print("\n下一步：运行工具 smoke test 和端到端任务。")
    return 0 if ok else 1


def _build_agent(args: argparse.Namespace):
    """组装一次任务/一次会话都要用的 AgentLoop：选后端、接 MCP、加 Skills。

    一次性任务模式和 REPL 模式共用这段逻辑，避免两处各写一遍容易跑偏。
    返回 (AgentLoop 实例, mcp clients 列表)；调用方负责在结束时关闭 clients。
    """
    from agent.loop import AgentLoop

    reg = build_default_registry()
    clients = []

    # DAY4 默认接入 echo MCP，保证 mcp__echo 可用于实验验证。
    mcp_commands = [[sys.executable, "-m", "mcp.echo_server"]]
    mcp_commands.extend(shlex.split(raw) for raw in args.mcp_command)
    for command in mcp_commands:
        try:
            clients.append(_start_mcp(reg, command))
        except Exception as e:  # noqa
            print(f"[提示] MCP server 接入失败（{' '.join(command)}）：{e}")

    try:
        from backend.client import DeepSeekBackend, VisionBackend
        backend = VisionBackend() if args.image else DeepSeekBackend()
    except Exception as e:  # noqa
        if args.image:
            for client in clients:
                close = getattr(client, "close", None)
                if close:
                    close()
            raise
        from backend.fake_backend import FakeBackend
        print(f"[提示] 未启用真后端（{e}），回退 FakeBackend。配置 DEEPSEEK_API_KEY 后即用真模型。")
        backend = FakeBackend()

    skills = load_skills()
    skill_prompt = (
        "\n\n可用 Skills：\n" + skills_catalog(skills) +
        "\n任务匹配某个 Skill 时，调用 invoke_skill(name=\"xxx\") 加载其完整操作流程，"
        "再严格按正文执行。不要手动 read SKILL.md 文件。"
    )

    # 召回记忆并注入 system prompt
    from agent.memory import recall_all
    recalled = recall_all()
    system = SYSTEM_PROMPT + skill_prompt
    if recalled.strip():
        system += "\n\n# 关于本项目 / 用户的已知记忆（相关时遵循）\n" + recalled

    agent = AgentLoop(
        backend,
        reg,
        system,
        max_turns=args.max_turns,
        max_steps=args.max_steps,
    )
    return agent, clients


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="mini-openclaw",
        description=("命令行科研智能体；长论文等复杂任务可通过 "
                     "--max-turns 和 --max-steps 自定义执行预算。"),
    )
    p.add_argument("task", nargs="?", help="要让 agent 完成的任务（自然语言）；不给则进入交互模式")
    p.add_argument("--selfcheck", action="store_true", help="只做骨架自检")
    p.add_argument("--mcp-command", action="append", default=[],
                   help="额外接入一个 MCP stdio server 命令，例如：\"python -m mcp.calc_server\"")
    p.add_argument("--image", action="append", default=[],
                   help="随任务发送的图片路径；可重复指定")
    p.add_argument("--max-turns", type=int, default=60,
                   help="单次任务最多调用模型的轮数（默认 60）")
    p.add_argument("--max-steps", type=int, default=100,
                   help="单次任务的规划步数上限（默认 100，不能小于 max-turns）")
    args = p.parse_args(argv)

    if args.max_turns < 1 or args.max_steps < args.max_turns:
        p.error("--max-turns 必须大于 0，且 --max-steps 不能小于 --max-turns")

    if args.selfcheck:
        return selfcheck(args.mcp_command)

    if not args.task:
        try:
            agent, clients = _build_agent(args)
        except Exception as e:  # noqa
            print(f"错误：{e}")
            return 2
        try:
            from agent.repl import run_repl
            run_repl(agent)
        finally:
            for client in clients:
                close = getattr(client, "close", None)
                if close:
                    close()
        return 0

    # 一次性任务：优先用 DeepSeek API；没配 key 时回退到 FakeBackend（离线打通管道）
    try:
        agent, clients = _build_agent(args)
    except Exception as e:  # noqa
        print(f"错误：{e}")
        return 2

    try:
        user_task = args.task
        if args.image:
            from backend.multimodal import user_content
            user_task = user_content(args.task, args.image)
        print(agent.run(user_task))
    finally:
        for client in clients:
            close = getattr(client, "close", None)
            if close:
                close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
