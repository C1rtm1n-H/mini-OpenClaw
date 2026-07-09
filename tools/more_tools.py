"""完整工具集：edit / grep / glob（Day4，→ v1）+ web_fetch / task_list（Day5）。

每个工具上午讲设计权衡，下午实现。这里只给签名与 TODO，便于你拆到独立文件。
建议最终拆成 edit.py / search.py / web.py / todo.py，再在 base.build_default_registry 注册。
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from markdownify import markdownify as md

from agent.context import truncate_observation
from .base import Tool


# --- edit：三种策略权衡（整文件重写 / unified diff / search-replace）---
def _edit(path: str, old: str = "", new: str = "") -> str:
    """最稳的 search-replace：old 在文件中唯一时替换为 new。"""
    p = Path(path)
    try:
        if not p.exists():
            return f"错误：文件不存在：{path}"
        if p.is_dir():
            return f"错误：路径是目录，不是文件：{path}"
        text = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"错误：读取失败：{path}: {e}"

    if old == "":
        return "错误：old 不能为空；请提供要被替换的原文。"
    count = text.count(old)
    if count == 0:
        return "错误：old 文本在文件中未找到，未修改。"
    if count > 1:
        return f"错误：old 文本出现 {count} 次，不唯一；为避免误改，未修改。"

    try:
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"错误：写入失败：{path}: {e}"
    return f"已修改 {path}：替换 1 处。"


# --- grep：基于 ripgrep ---
def _grep(pattern: str, path: str = ".") -> str:
    """调用系统 rg，返回匹配行（带文件名+行号）。"""
    cmd = ["rg", "--line-number", "--no-heading", pattern, path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return _grep_python(pattern, path)
    except subprocess.TimeoutExpired:
        return f"错误：grep 超时：pattern={pattern!r}, path={path!r}"
    except Exception as e:  # noqa: BLE001
        return f"错误：grep 执行失败：{e}"

    if proc.returncode == 1:
        return "[无匹配]"
    if proc.returncode != 0:
        err = proc.stderr.strip() or "未知错误"
        return f"错误：rg 失败（returncode={proc.returncode}）：{err}"

    output = proc.stdout.strip()
    if not output:
        return "[无匹配]"
    return truncate_observation(output, 8000)


def _grep_python(pattern: str, path: str = ".") -> str:
    """rg 不存在时的 Python fallback。"""
    root = Path(path)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"错误：正则表达式无效：{e}"

    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    matches: list[str] = []
    for file in files:
        try:
            for lineno, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    matches.append(f"{file}:{lineno}:{line}")
                    if len(matches) >= 500:
                        return truncate_observation("\n".join(matches) + "\n...[结果过多，已截断]", 8000)
        except Exception:
            continue
    return "\n".join(matches) if matches else "[无匹配]"


# --- glob：按文件名模式找文件 ---
def _glob(pattern: str) -> str:
    """用 pathlib.Path().rglob 找文件路径。"""
    try:
        paths = sorted(str(p) for p in Path(".").rglob(pattern) if p.is_file())
    except Exception as e:  # noqa: BLE001
        return f"错误：glob 失败：{e}"
    if not paths:
        return "[无匹配]"
    output = "\n".join(paths[:500])
    if len(paths) > 500:
        output += f"\n...[结果过多，已截断；共 {len(paths)} 个文件]"
    return truncate_observation(output, 8000)


# --- web_fetch：URL -> markdown，控 token 预算 ---
def _web_fetch(url: str, max_tokens: int = 2000) -> str:
    """抓取 URL，HTML 转 markdown，并按预算截断。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "错误：web_fetch 仅支持 http/https URL。"

    try:
        resp = httpx.get(url, follow_redirects=True, timeout=15.0, headers={"User-Agent": "mini-OpenClaw/0.1"})
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"错误：抓取失败：{url}: {e}"

    content_type = resp.headers.get("content-type", "")
    text = resp.text
    if "html" in content_type.lower() or "<html" in text[:500].lower():
        text = md(text, heading_style="ATX")

    header = f"URL: {resp.url}\nStatus: {resp.status_code}\n\n"
    max_chars = max(1000, int(max_tokens) * 4)
    return truncate_observation(header + text.strip(), max_chars)


# --- task_list（TodoWrite）：自维护待办，提升长任务成功率 ---
_TASKS: list[str] = []


def _task_list(action: str, items: list | None = None) -> str:
    """维护一个极简内存待办。默认工具集暂不注册它。"""
    global _TASKS
    items = items or []
    if action == "add":
        _TASKS.extend(str(x) for x in items)
    elif action == "set":
        _TASKS = [str(x) for x in items]
    elif action == "clear":
        _TASKS = []
    elif action == "complete":
        done = {str(x) for x in items}
        _TASKS = [x for x in _TASKS if x not in done]
    elif action != "list":
        return "错误：action 必须是 add/set/clear/complete/list 之一。"
    return "\n".join(f"- {x}" for x in _TASKS) if _TASKS else "[待办为空]"


edit_tool = Tool("edit", "编辑文件：把 old 文本替换为 new；仅当 old 在文件中恰好出现一次时才会写入。",
                 {"type": "object", "properties": {"path": {"type": "string"},
                  "old": {"type": "string"}, "new": {"type": "string"}},
                  "required": ["path", "old", "new"]}, _edit)
grep_tool = Tool("grep", "在文件内容中搜索匹配 pattern 的行（优先使用 ripgrep），返回 文件:行号:内容。适合先定位再 read。",
                 {"type": "object", "properties": {"pattern": {"type": "string"},
                  "path": {"type": "string"}}, "required": ["pattern"]}, _grep)
glob_tool = Tool("glob", "按通配模式递归查找文件路径，例如 '*.py'。适合先发现候选文件。",
                 {"type": "object", "properties": {"pattern": {"type": "string"}},
                  "required": ["pattern"]}, _glob)
web_fetch_tool = Tool("web_fetch", "抓取 http/https URL 并转为 markdown（受 token 预算限制）。适合读取用户给出的网页链接。",
                      {"type": "object", "properties": {"url": {"type": "string"},
                       "max_tokens": {"type": "integer", "description": "返回内容预算，粗略 token 数，默认 2000"}},
                       "required": ["url"]}, _web_fetch)
task_list_tool = Tool("task_list", "维护任务待办清单（add/update/complete）。",
                      {"type": "object", "properties": {"action": {"type": "string"},
                       "items": {"type": "array"}}, "required": ["action"]}, _task_list)
