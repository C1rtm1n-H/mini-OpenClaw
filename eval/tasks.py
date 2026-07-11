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


def _check_audit(traj: Trajectory) -> bool:
    """实验代码审计任务判据：四维度综合评估。

    成功 = 覆盖度 + 可复现性 + 可操作性 + 效率，至少 3/4 通过。
    不做精确 LLM 验证，用关键词和工具调用模式近似判断。
    """
    steps = traj.get("steps", [])
    final = traj.get("final", "").lower()
    tool_names = {tc["name"] for s in steps for tc in s.get("tool_calls", [])}
    all_tool_calls = [
        tc for s in steps for tc in s.get("tool_calls", [])
    ]

    # 维度 1：覆盖度——使用了扫描工具（glob/grep/read）
    used_scan = bool({"glob", "grep", "read"} & tool_names)
    # 在 grep 或 read 中访问了至少 2 个不同的文件/path
    paths_touched = set()
    for tc in all_tool_calls:
        args = tc.get("arguments", {})
        for key in ("path", "pattern"):
            if key in args:
                paths_touched.add(str(args[key]))
    touched_multiple = len(paths_touched) >= 2
    coverage_ok = used_scan and touched_multiple

    # 维度 2：可复现性——检查了随机种子或数据划分
    has_repro_check = (
        "seed" in final or "随机" in final or "random" in final
        or any("seed" in str(tc.get("arguments", {})) for tc in all_tool_calls)
    )
    repro_ok = has_repro_check

    # 维度 3：可操作性——至少一处给出了"位置 + 建议"，而非仅描述问题
    # 位置标记：包含文件路径 + 行号，或 "文件:行号" 模式
    has_location = (
        ".py:" in final or ".yaml:" in final or ".json:" in final
        or any(line.strip() for line in traj.get("final", "").splitlines()
               if ":" in line and any(ext in line for ext in [".py", ".yaml", ".json", ".sh"]))
    )
    # 建议标记：包含修复意图的关键词
    has_suggestion = any(
        kw in final for kw in (
            "建议", "修复", "改为", "替换为", "修改", "添加",
            "suggest", "fix", "change", "replace", "should be",
            "推荐", "可以", "应当"
        )
    )
    actionable_ok = has_location and has_suggestion

    # 维度 4：效率——步数合理（审查类任务应在 12 步内完成核心分析）
    step_count = len(steps)
    efficiency_ok = step_count <= 12

    # 综合：至少 3/4 通过
    scores = [coverage_ok, repro_ok, actionable_ok, efficiency_ok]
    return sum(scores) >= 3


SAMPLE_TASKS: list[Task] = [
    Task("read-config", "读取 config.json，告诉我 timeout 是多少", _check_read_config),
    Task("list-dir", "列出当前目录下的文件", _check_list_dir),
    Task("domain-scan-todos", "扫描项目中的所有 TODO 注释，列出至少 3 条待办事项", _check_domain),
    # 额外一条：运行 bash 脚本
    Task("run-bash-script", "帮我运行 scripts/setup.sh 这个 bash 脚本", _check_domain_2),
    # 领域任务：实验代码审计
    Task("audit-experiment-code",
         "请作为科研助手，审计当前项目的实验代码可复现性。"
         "用 glob 发现 Python 文件，用 grep 搜索随机种子和硬编码路径，"
         "用 read 检查关键配置，最后用 write 输出审计报告 experiment-audit.md。"
         "每个发现必须给出具体文件路径、行号和修复建议。",
         _check_audit),
]
