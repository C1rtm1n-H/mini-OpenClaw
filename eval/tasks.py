"""Day 3 · 评测任务集：定义任务 + 成功判据（程序化优先）。

每条任务 = 名字 + 指令 + check(trajectory) -> bool。
check 尽量不依赖人的主观判断（讲义 §9.1）；实在开放式的留给 LLM-as-judge（步骤 3）。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

# 一条"轨迹记录"：D4 起由真 agent 产出，今天用样本轨迹代替。
#   {"task": "任务名", "steps": [ {tool_calls, raw, prompt_tokens, completion_tokens}, ... ],
#    "final": "agent 的最终自然语言答复"}
Trajectory = dict


@dataclass
class Task:
    name: str
    instruction: str                       # 给 agent 的指令
    check: Callable[[Trajectory], bool]    # 成功判据：吃一条轨迹，判成败


# ---- 成功判据（程序化优先）----

def _check_read_config(traj: Trajectory) -> bool:
    """成功 = 期间调用过 read 且最终答复里报出了 timeout 的值。"""
    used_read = any(
        tc["name"] == "read"
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )
    return used_read and "30" in traj.get("final", "")


def _check_list_dir(traj: Trajectory) -> bool:
    """成功 = 期间调用过 bash 且命令里含 ls。"""
    return any(
        tc["name"] == "bash" and "ls" in str(tc.get("arguments", {}))
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )


# TODO[Day3] 你组领域任务判据
def _check_domain(traj: Trajectory) -> bool:
    """领域任务判据（软件工程/代码分析方向）。

    成功 = agent 调用了 grep 或 read 工具扫描代码，且最终答复里包含
    至少一条 TODO 项的描述（以 "- " 或 "* " 开头的列表项）。
    """
    used_scan = any(
        tc["name"] in ("grep", "read", "glob")
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )
    final = traj.get("final", "")
    has_todo_items = any(
        line.strip().startswith(("- ", "* ")) and "TODO" in line
        for line in final.splitlines()
    )
    return used_scan and (has_todo_items or "TODO" in final)


def _check_domain_2(traj: Trajectory) -> bool:
    """成功 = 期间调用过 bash。"""
    return any(
        tc["name"] == "bash"
        for s in traj["steps"] for tc in s.get("tool_calls", [])
    )


SAMPLE_TASKS: list[Task] = [
    Task("read-config", "读取 config.json，告诉我 timeout 是多少", _check_read_config),
    Task("list-dir", "列出当前目录下的文件", _check_list_dir),
    Task("domain-scan-todos", "扫描项目中的所有 TODO 注释，列出至少 3 条待办事项", _check_domain),
    # 额外一条：运行 bash 脚本
    Task("run-bash-script", "帮我运行 scripts/setup.sh 这个 bash 脚本", _check_domain_2),
]
