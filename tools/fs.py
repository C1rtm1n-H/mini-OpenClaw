"""文件读写工具（Day4：read / write）。"""
from __future__ import annotations
from pathlib import Path

from .base import Tool


def _read(path: str, max_bytes: int = 100_000) -> str:
    """读取文本文件，返回带行号的内容。"""
    p = Path(path)
    try:
        if not p.exists():
            return f"错误：文件不存在：{path}"
        if p.is_dir():
            return f"错误：路径是目录，不是文件：{path}"

        data = p.read_bytes()
    except Exception as e:  # noqa: BLE001
        return f"错误：读取失败：{path}: {e}"

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    if text == "":
        body = "[空文件]"
    else:
        lines = text.splitlines()
        if text.endswith("\n"):
            # splitlines() 会丢掉最后一个空行；文件以换行结束时不额外显示空行。
            pass
        body = "\n".join(f"{i}\t{line}" for i, line in enumerate(lines, 1))

    if truncated:
        body += f"\n...[已截断，读取前 {max_bytes} 字节，共 {p.stat().st_size} 字节]"
    return body


def _write(path: str, content: str) -> str:
    """覆盖写入文本文件。"""
    p = Path(path)
    try:
        if p.exists() and p.is_dir():
            return f"错误：路径是目录，不能写入文件：{path}"
        p.write_text(content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"错误：写入失败：{path}: {e}"
    return f"已写入 {len(content.encode('utf-8'))} 字节到 {path}"


read_tool = Tool(
    name="read",
    description="读取指定路径的文本文件内容，返回带行号的文本；适合在编辑前查看文件。",
    parameters={"type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"},
                               "max_bytes": {"type": "integer", "description": "最多读取的字节数，默认 100000"}},
                "required": ["path"]},
    run=_read,
)

write_tool = Tool(
    name="write",
    description="把内容写入指定路径（覆盖）。适合创建新文件或完整重写文件。",
    parameters={"type": "object",
                "properties": {"path": {"type": "string"},
                               "content": {"type": "string"}},
                "required": ["path", "content"]},
    run=_write,
)
