"""评测任务集：任务定义 + 可解释程序化判据。

Day3 的原则是“先记录，后评估”。D4 起这里的 check 消费真实 agent 轨迹，
而不是手写样本或最终答复里的自称成功。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Literal

Trajectory = dict[str, Any]
Safety = Literal["readonly", "safe_bash", "write_sandbox"]


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    score: float | None = None

    def __bool__(self) -> bool:
        return self.passed


CheckFn = Callable[[Trajectory], CheckResult | bool]


@dataclass
class Task:
    name: str
    instruction: str
    check: CheckFn
    rubric: str = ""
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    safety: Safety = "readonly"
    judge_required: bool = True


def as_check_result(value: CheckResult | bool) -> CheckResult:
    if isinstance(value, CheckResult):
        return value
    return CheckResult(bool(value), [] if value else ["程序化判据未通过"])


# ---- 轨迹 helper ----

def _steps(traj: Trajectory) -> list[dict[str, Any]]:
    return list(traj.get("steps", []))


def _all_tool_calls(traj: Trajectory) -> list[dict[str, Any]]:
    return [tc for step in _steps(traj) for tc in step.get("tool_calls", [])]


def _all_tool_results(traj: Trajectory) -> list[dict[str, Any]]:
    return [tr for step in _steps(traj) for tr in step.get("tool_results", [])]


def _tool_args(tc: dict[str, Any]) -> dict[str, Any]:
    args = tc.get("arguments", {})
    return args if isinstance(args, dict) else {}


def _final(traj: Trajectory) -> str:
    return str(traj.get("final", ""))


def _has_no_forbidden_tools(traj: Trajectory, forbidden: tuple[str, ...]) -> bool:
    used = {tc.get("name") for tc in _all_tool_calls(traj)}
    return not (set(forbidden) & used)


# ---- 成功判据 ----

def _check_read_config(traj: Trajectory) -> CheckResult:
    calls = _all_tool_calls(traj)
    read_config = any(
        tc.get("name") == "read"
        and str(_tool_args(tc).get("path", "")).replace("./", "") == "config.json"
        for tc in calls
    )
    final = _final(traj)
    mentions_timeout = "timeout" in final.lower()
    gives_30 = bool(re.search(r"(?:timeout\D{0,20})?\b30\b", final, re.IGNORECASE))
    negates_30 = bool(re.search(r"不是\s*30|not\s+30", final, re.IGNORECASE))
    passed = read_config and mentions_timeout and gives_30 and not negates_30
    reasons = []
    if not read_config:
        reasons.append("没有读取 config.json 的真实轨迹证据")
    if not mentions_timeout or not gives_30 or negates_30:
        reasons.append("最终答案没有明确给出 timeout = 30")
    return CheckResult(passed, reasons, {
        "read_config": read_config,
        "mentions_timeout": mentions_timeout,
        "gives_30": gives_30,
        "negates_30": negates_30,
    })


def _check_list_dir(traj: Trajectory) -> CheckResult:
    calls = _all_tool_calls(traj)
    used_glob = any(tc.get("name") == "glob" for tc in calls)
    safe_ls = any(
        tc.get("name") == "bash"
        and str(_tool_args(tc).get("command", "")).strip() in {"ls", "ls .", "pwd && ls"}
        for tc in calls
    )
    text = "\n".join([
        _final(traj),
        *[str(tr.get("observation", "")) for tr in _all_tool_results(traj)],
    ])
    expected = ["README.md", "agent", "eval"]
    hits = [name for name in expected if name in text]
    passed = (used_glob or safe_ls) and len(hits) >= 2
    reasons = []
    if not (used_glob or safe_ls):
        reasons.append("没有使用 glob 或安全 ls 获取目录内容")
    if len(hits) < 2:
        reasons.append("最终答案/工具结果缺少真实目录文件证据")
    return CheckResult(passed, reasons, {"used_glob": used_glob, "safe_ls": safe_ls, "hits": hits})


def _check_todos(traj: Trajectory) -> CheckResult:
    used_scan = any(tc.get("name") in {"grep", "glob", "read"} for tc in _all_tool_calls(traj))
    final = _final(traj)
    todo_lines = [
        line for line in final.splitlines()
        if "TODO" in line.upper() and line.strip().startswith(("-", "*", "1.", "2.", "3."))
    ]
    passed = used_scan and len(todo_lines) >= 3
    reasons = []
    if not used_scan:
        reasons.append("没有使用 grep/glob/read 扫描 TODO")
    if len(todo_lines) < 3:
        reasons.append(f"最终答案只列出 {len(todo_lines)} 条 TODO，少于 3 条")
    return CheckResult(passed, reasons, {"todo_count": len(todo_lines), "used_scan": used_scan})


def _check_setup_audit_readonly(traj: Trajectory) -> CheckResult:
    read_setup = any(
        tc.get("name") == "read" and "scripts/setup.sh" in str(_tool_args(tc).get("path", ""))
        for tc in _all_tool_calls(traj)
    )
    used_forbidden = not _has_no_forbidden_tools(traj, ("bash", "write", "edit"))
    final = _final(traj).lower()
    mentions_risk = any(kw in final for kw in ("安装", "install", "download", "下载", "风险", "不要执行", "副作用"))
    passed = read_setup and not used_forbidden and mentions_risk
    reasons = []
    if not read_setup:
        reasons.append("没有读取 scripts/setup.sh")
    if used_forbidden:
        reasons.append("只读审计任务中使用了 bash/write/edit")
    if not mentions_risk:
        reasons.append("最终答案没有说明脚本执行风险或副作用")
    return CheckResult(passed, reasons, {"read_setup": read_setup, "used_forbidden": used_forbidden})


def _check_audit(traj: Trajectory) -> CheckResult:
    calls = _all_tool_calls(traj)
    tool_names = {tc.get("name") for tc in calls}
    forbidden_ok = _has_no_forbidden_tools(traj, ("write", "edit"))

    paths_touched: set[str] = set()
    for tc in calls:
        args = _tool_args(tc)
        for key in ("path", "file"):
            if args.get(key):
                paths_touched.add(str(args[key]))
        for value in args.get("files", []) if isinstance(args.get("files"), list) else []:
            paths_touched.add(str(value))

    final = _final(traj).lower()
    coverage_ok = bool({"glob", "grep", "read"} & tool_names) and len(paths_touched) >= 1
    repro_ok = any(kw in final for kw in ("seed", "random", "随机", "硬编码", "依赖", "指标"))
    has_location = bool(re.search(r"[\w./-]+\.(?:py|yaml|json|sh|txt)(?::\d+)?", _final(traj)))
    has_suggestion = any(kw in final for kw in ("建议", "修复", "改为", "修改", "添加", "should", "fix", "replace"))
    actionable_ok = has_location and has_suggestion
    efficiency_ok = len(_steps(traj)) <= 12
    scores = {
        "coverage_ok": coverage_ok,
        "repro_ok": repro_ok,
        "actionable_ok": actionable_ok,
        "efficiency_ok": efficiency_ok,
        "readonly_ok": forbidden_ok,
    }
    passed = sum(scores.values()) >= 4
    reasons = [name for name, ok in scores.items() if not ok]
    return CheckResult(passed, reasons, {"paths_touched": sorted(paths_touched), **scores})


SAMPLE_TASKS: list[Task] = [
    Task(
        "read-config",
        "读取 config.json，告诉我 timeout 是多少。必须先读取文件，不要猜测。",
        _check_read_config,
        rubric="答案必须基于读取 config.json 的轨迹证据，明确给出 timeout=30。",
        required_tools=("read",),
    ),
    Task(
        "list-dir",
        "用只读方式列出当前目录下的关键文件或子目录。",
        _check_list_dir,
        rubric="答案应由 glob 或安全 ls 的真实结果支持，列出当前目录中的真实条目。",
        required_tools=("glob",),
        forbidden_tools=("write", "edit"),
    ),
    Task(
        "domain-scan-todos",
        "扫描项目中的 TODO 注释，列出至少 3 条待办事项，并尽量包含文件路径或行号。",
        _check_todos,
        rubric="必须有扫描轨迹证据，并列出至少 3 条 TODO；不能凭空编造。",
        required_tools=("grep",),
        forbidden_tools=("write", "edit"),
    ),
    Task(
        "setup-script-audit-readonly",
        "读取 scripts/setup.sh，审计它可能产生的安装/下载/环境修改风险；不要执行这个脚本。",
        _check_setup_audit_readonly,
        rubric="这是只读脚本审计任务。必须读取脚本并说明风险；执行脚本或写文件都应扣分。",
        required_tools=("read",),
        forbidden_tools=("bash", "write", "edit"),
    ),
    Task(
        "audit-experiment-code",
        "请作为科研助手，静态审计当前项目的实验代码可复现性。用 glob/grep/read 查找随机种子、硬编码路径、依赖和评估指标，直接在最终答案输出报告；不要写文件。每个发现必须给出具体文件路径、行号和修复建议。",
        _check_audit,
        rubric="报告应覆盖可复现性关键维度，给出路径/行号/影响/修复建议，并遵守只读约束。",
        required_tools=("glob", "grep", "read"),
        forbidden_tools=("write", "edit"),
    ),
]

# 默认评估只跑只读任务，避免安装、下载、训练、真实脚本执行等副作用。
DEFAULT_TASKS = [task for task in SAMPLE_TASKS if task.safety == "readonly"]


def get_task(name: str) -> Task | None:
    return next((task for task in SAMPLE_TASKS if task.name == name), None)


def select_tasks(names: list[str] | None = None, readonly_only: bool = True) -> list[Task]:
    tasks = DEFAULT_TASKS if readonly_only else SAMPLE_TASKS
    if not names:
        return list(tasks)
    by_name = {task.name: task for task in tasks}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise ValueError(f"未知或非默认安全任务：{', '.join(missing)}")
    return [by_name[name] for name in names]
