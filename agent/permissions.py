from pathlib import Path
import os
import re

READONLY = {"read", "grep", "glob"}
WRITE    = {"write", "edit"}
EXEC     = {"bash", "web_fetch"}
META     = {"remember", "forget", "todo_write", "update_todo", "invoke_skill"}
# META 只操作项目记忆、进程内待办或 skill 加载，不执行外部命令，也不改用户代码。

# 安全数据根：允许 agent 访问工作目录以外的用户数据目录（如 Docker 部署的 /data）
# 可通过 OPENCLAW_DATA_ROOTS 环境变量扩展，冒号分隔
_SAFE_ROOTS: tuple[Path, ...] = tuple(
    Path(p).resolve()
    for p in os.environ.get("OPENCLAW_DATA_ROOTS", "/data").split(":")
    if p.strip()
)


def _in_safe_root(path: str, workdir: Path) -> bool:
    """路径是否落在某个安全数据根内（非系统目录，用户显式指定的数据区）。"""
    if not path:
        return False
    target = _resolve_path(path, workdir)
    for root in _SAFE_ROOTS:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def check(tool: str, args: dict, workdir: Path,
          task_scopes: tuple[Path, ...] = (),
          readonly_downgrade: bool = False) -> str:
    """返回 'allow' / 'confirm' / 'deny'。"""
    if tool in READONLY:
        path = args.get("path", ".")
        if (
            _escapes_workdir(path, workdir)
            and not (task_scopes and _within_task_scope(path, workdir, task_scopes))
            and not _in_safe_root(path, workdir)
        ):
            return "deny"
        if task_scopes and not _within_task_scope(path, workdir, task_scopes):
            if tool == "read" and _is_skill_instruction(path, workdir):
                return "allow"
            if _in_safe_root(path, workdir):
                return "allow"
            return "deny"
        return "allow"
    if tool in META:
        return "allow"            # remember 等元操作只写项目约定文件，安全可控
    if tool == "pdf_extract":
        source = args.get("path", "")
        output = args.get("output_path", "")
        source_allowed = not _escapes_workdir(source, workdir) or (
            task_scopes and _within_task_scope(source, workdir, task_scopes)
        ) or _in_safe_root(source, workdir)
        output_allowed = not output or not _escapes_workdir(output, workdir) or (
            task_scopes and _within_task_scope(output, workdir, task_scopes)
        ) or _in_safe_root(output, workdir)
        if not source_allowed or not output_allowed:
            return "deny"
        if task_scopes and (
            not _within_task_scope(source, workdir, task_scopes)
            or (output and not _within_task_scope(output, workdir, task_scopes))
        ):
            if not _in_safe_root(source, workdir) and not (output and _in_safe_root(output, workdir)):
                return "deny"
        # 已有缓存且未请求覆盖时，pdf_extract 只检查并复用，不发生写入。
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = workdir / source_path
        target = Path(output) if output else source_path.with_suffix(".txt")
        if output and not target.is_absolute():
            target = workdir / target
        if target.exists() and not args.get("overwrite", False):
            return "allow"
        return "confirm"
    if tool in WRITE:
        path = args.get("path", "")
        if (
            _escapes_workdir(path, workdir)
            and not (task_scopes and _within_task_scope(path, workdir, task_scopes))
            and not _in_safe_root(path, workdir)
        ):
            return "deny"
        if (
            task_scopes
            and not _within_task_scope(path, workdir, task_scopes)
            and not _is_safe_report_output(path, workdir)
            and not _in_safe_root(path, workdir)
        ):
            return "deny"
        return "confirm"
    if tool in EXEC:
        if tool == "bash":
            command = str(args.get("command", ""))
            if readonly_downgrade and not _is_safe_diagnostic_command(command):
                return "deny"
            if _is_forbidden_experiment_command(command):
                return "deny"
        return "confirm"          # 执行/外传一律先确认（沙箱在步骤 2）
    return "confirm"              # 未知工具：保守，先问


def _escapes_workdir(path: str, workdir: Path) -> bool:
    """路径（展开 ~ 后）解析是否落在 workdir 之外。"""
    if not path:
        return False
    p = Path(path).expanduser()
    root = workdir.resolve()
    target = p.resolve() if p.is_absolute() else (root / p).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return True
    return False


def _resolve_path(path: str, workdir: Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (workdir / candidate).resolve()


def _within_task_scope(path: str, workdir: Path, scopes: tuple[Path, ...]) -> bool:
    if not path:
        return False
    target = _resolve_path(path, workdir)
    for scope in scopes:
        scope = scope.resolve()
        if scope.is_file():
            # 单文件任务只允许目标本身；PDF 额外允许同名提取文本缓存。
            allowed = {scope}
            if scope.suffix.lower() == ".pdf":
                allowed.add(scope.with_suffix(".txt"))
            if target in allowed:
                return True
            continue
        try:
            target.relative_to(scope)
            return True
        except ValueError:
            continue
    return False


def _is_skill_instruction(path: str, workdir: Path) -> bool:
    target = _resolve_path(path, workdir)
    skills_root = (workdir / "skills").resolve()
    try:
        target.relative_to(skills_root)
    except ValueError:
        return False
    return target.name == "SKILL.md" and target.is_file()


def _is_safe_report_output(path: str, workdir: Path) -> bool:
    """允许把明确命名的 Markdown 报告写到 Agent 当前工作目录。"""
    if not path:
        return False
    target = _resolve_path(path, workdir)
    if target.parent != workdir.resolve() or target.suffix.lower() != ".md":
        return False
    name = target.stem.lower()
    return any(marker in name for marker in ("report", "audit", "reproduction", "plan"))


def _is_forbidden_experiment_command(command: str) -> bool:
    """硬拦训练、评估、安装和下载，仅给毫秒级诊断命令留出口。"""
    normalized = " ".join(command.lower().split())
    if not normalized:
        return False

    if _is_safe_diagnostic_command(command):
        return False

    forbidden_patterns = (
        r"\b(?:wget|curl|aria2c)\b",
        r"\b(?:pip|conda|mamba|poetry|uv)\s+(?:install|create|update|upgrade|sync)\b",
        r"\b(?:torchrun|deepspeed)\b",
        r"\baccelerate\s+launch\b",
        r"\b(?:bash|sh|powershell)\s+[^\s]*(?:train|download|evaluate|eval|infer|predict)[^\s]*",
        r"\b(?:python|py)(?:\.exe)?\s+[^\r\n]*(?:train|finetune|fine_tune|evaluate|eval|infer|predict)[^\s]*\.py\b",
        r"\b(?:python|py)(?:\.exe)?\s+[^\r\n]*\.py\s+[^\r\n]*(?:--epochs|--steps|--do_train)\b",
        r"\b(?:make|just)\s+(?:train|download|evaluate|eval|infer|predict)\b",
    )
    return any(re.search(pattern, normalized) for pattern in forbidden_patterns)


def _is_safe_diagnostic_command(command: str) -> bool:
    normalized = " ".join(command.lower().split())
    if any(operator in command for operator in (";", "&&", "||", "|", "\n", "\r")):
        return False
    return bool(
        "--help" in normalized
        or bool(re.search(r"\b(?:python|py)(?:\.exe)?\s+--version\b", normalized))
        or bool(re.search(r"\bpip\s+(?:list|show|freeze)\b", normalized))
        or bool(re.search(r"\bpython\s+-m\s+(?:py_compile|compileall)\b", normalized))
        or bool(re.search(r"\bpython\s+-c\s+[\"'][\s\\n]*import\s+[a-z_][\w.]*", normalized))
        or bool(re.search(r"\bast\s*\.\s*parse\b", normalized))
        or bool(re.search(r"\bpy_compile\b", normalized))
    )
