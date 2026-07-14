"""文件读写工具（Day4：read / write）。"""
from __future__ import annotations
from pathlib import Path

from .base import Tool
from .security import wrap_external


def _read(path: str, max_bytes: int = 100_000, start_line: int = 1,
          max_lines: int | None = None) -> str:
    """分页读取文本，返回保留原文件行号的内容。"""
    p = Path(path)
    if start_line < 1:
        return "错误：start_line 必须大于等于 1"
    if max_lines is not None and max_lines < 1:
        return "错误：max_lines 必须大于 0"
    if max_bytes < 1:
        return "错误：max_bytes 必须大于 0"
    try:
        if not p.exists():
            return f"错误：文件不存在：{path}"
        if p.is_dir():
            return f"错误：路径是目录，不是文件：{path}"

        data = p.read_bytes()
    except Exception as e:  # noqa: BLE001
        return f"错误：读取失败：{path}: {e}"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    if text == "":
        body = "[空文件]"
    else:
        all_lines = text.splitlines()
        start_index = min(start_line - 1, len(all_lines))
        end_index = len(all_lines) if max_lines is None else min(
            start_index + max_lines, len(all_lines)
        )

        selected: list[tuple[int, str]] = []
        used_bytes = 0
        for index in range(start_index, end_index):
            line = all_lines[index]
            line_bytes = len((line + "\n").encode("utf-8"))
            if selected and used_bytes + line_bytes > max_bytes:
                break
            selected.append((index + 1, line))
            used_bytes += line_bytes

        next_line = selected[-1][0] + 1 if selected else start_line
        has_more = next_line <= len(all_lines)
        range_end = selected[-1][0] if selected else start_line - 1
        navigation = (
            f"[分页：第 {start_line}-{range_end} 行，共 {len(all_lines)} 行"
            + (f"；继续读取请设置 start_line={next_line}]" if has_more else "；已到文件末尾]")
        )
        rendered = "\n".join(f"{number}\t{line}" for number, line in selected)
        body = navigation + ("\n" + rendered if rendered else "\n[指定范围无内容]")
    return wrap_external(body, path)


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
    description=("分页读取指定文本文件并返回原始行号。长论文不要一次读全文；"
                 "先定位章节，再用 start_line 和 max_lines 分段读取，并按返回的下一行继续。"),
    parameters={"type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"},
                               "max_bytes": {"type": "integer", "description": "本页最多读取的原文 UTF-8 字节数，默认 100000"},
                               "start_line": {"type": "integer", "description": "起始行号（从 1 开始），默认 1"},
                               "max_lines": {"type": "integer", "description": "本页最多读取行数；长论文建议 80-150 行"}},
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
