"""论文实验仓库的只读审计工具集。

审计模式不复用普通 read/grep/glob，避免模型通过绝对路径越过被审仓库；
所有路径都绑定到启动时确定的 audit_root，且不提供任何写入或执行能力。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .base import Tool, ToolRegistry
from .security import wrap_external


_TEXT_SUFFIXES = {
    ".py", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".md", ".rst", ".txt", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
}
_DANGER_PATTERNS = (
    ("递归强制删除", re.compile(r"\brm\s+-[^\n]*r[^\n]*f|\brm\s+-[^\n]*f[^\n]*r", re.I)),
    ("PowerShell 递归删除", re.compile(r"\bRemove-Item\b[^\n]*(?:-Recurse|-Force)", re.I)),
    ("Windows 递归删除", re.compile(r"\b(?:rmdir|rd)\s+/s\b|\bdel\s+/[sqf]", re.I)),
    ("Python 删除目录", re.compile(r"\b(?:shutil\.rmtree|os\.remove|os\.unlink|Path\([^\n]*\)\.unlink)\b")),
    ("覆盖重定向", re.compile(r"(?:^|[;&|]\s*)>\s*[^>&]", re.M)),
    ("下载命令", re.compile(r"\b(?:wget|curl)\b|requests\.(?:get|post)\s*\(|urlretrieve\s*\(", re.I)),
    ("安装依赖", re.compile(r"\b(?:pip|conda|mamba)\s+install\b", re.I)),
    ("外部命令执行", re.compile(r"\b(?:os\.system|subprocess\.(?:run|Popen|call)|shell=True)\b")),
)


def _resolve(root: Path, raw: str = ".") -> Path:
    candidate = Path(raw).expanduser()
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径越过被审仓库：{raw}") from exc
    return target


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _iter_text_files(root: Path, base: Path) -> Iterable[Path]:
    files = [base] if base.is_file() else base.rglob("*")
    for path in files:
        if path.is_file() and (path.suffix.lower() in _TEXT_SUFFIXES or path.name.lower().startswith("readme")):
            yield path


def build_audit_registry(audit_root: str | Path) -> ToolRegistry:
    """创建只绑定到 audit_root 的 read/grep/glob/audit_scan 工具。"""
    root = Path(audit_root).resolve()
    if not root.is_dir():
        raise ValueError(f"审计目标不是目录：{root}")

    def read(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        try:
            target = _resolve(root, path)
        except ValueError as exc:
            return f"错误：{exc}"
        if not target.is_file():
            return f"错误：文件不存在或不是普通文件：{path}"
        if target.stat().st_size > 1_000_000:
            return f"错误：审计模式拒绝读取超过 1MB 的文件：{path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, start_line)
        end = len(lines) if end_line is None else min(len(lines), end_line)
        body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
        return wrap_external(body or "[空文件]", _relative(root, target))

    def glob(pattern: str) -> str:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            return "错误：glob pattern 必须是仓库内的相对模式"
        matches = sorted(path for path in root.glob(pattern) if path.is_file())[:500]
        return "\n".join(_relative(root, path) for path in matches) or "[未找到匹配文件]"

    def grep(pattern: str, path: str = ".", max_results: int = 200) -> str:
        try:
            base = _resolve(root, path)
        except ValueError as exc:
            return f"错误：{exc}"
        try:
            regex = re.compile(pattern, re.I)
        except re.error as exc:
            return f"错误：正则表达式无效：{exc}"
        rows: list[str] = []
        for file in _iter_text_files(root, base):
            if file.stat().st_size > 1_000_000:
                continue
            for lineno, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    rows.append(f"{_relative(root, file)}:{lineno}:{line[:500]}")
                    if len(rows) >= max_results:
                        return wrap_external("\n".join(rows) + "\n...[结果已截断]", "audit-grep")
        return wrap_external("\n".join(rows) or "[未找到匹配内容]", "audit-grep")

    def audit_scan(path: str = ".") -> str:
        """静态扫描危险副作用；只读源码，绝不执行脚本。"""
        try:
            base = _resolve(root, path)
        except ValueError as exc:
            return f"错误：{exc}"
        rows: list[str] = []
        for file in _iter_text_files(root, base):
            if file.suffix.lower() not in {".py", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd"}:
                continue
            if file.stat().st_size > 1_000_000:
                continue
            for lineno, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for label, regex in _DANGER_PATTERNS:
                    if regex.search(line):
                        rows.append(f"[{label}] {_relative(root, file)}:{lineno}: {line.strip()[:500]}")
        body = "\n".join(rows) if rows else "[未发现已知危险副作用模式；这不等于脚本绝对安全]"
        return wrap_external(body, "audit-static-scan")

    reg = ToolRegistry()
    reg.register(Tool(
        "read", "只读查看被审仓库内的文本文件，可指定起止行；禁止越过审计根目录。",
        {"type": "object", "properties": {
            "path": {"type": "string"}, "start_line": {"type": "integer"},
            "end_line": {"type": "integer"}}, "required": ["path"]}, read,
    ))
    reg.register(Tool(
        "glob", "只读列出被审仓库中匹配相对 glob 模式的文件。",
        {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}, glob,
    ))
    reg.register(Tool(
        "grep", "只读搜索被审仓库文本，返回文件、行号和证据；pattern 是正则表达式。",
        {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"},
            "max_results": {"type": "integer"}}, "required": ["pattern"]}, grep,
    ))
    reg.register(Tool(
        "audit_scan", "只读静态扫描 Shell/Python 脚本中的删除、覆盖、下载、安装和外部命令副作用；绝不执行脚本。",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}, audit_scan,
    ))
    return reg
