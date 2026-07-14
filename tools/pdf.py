"""PDF text extraction tool."""
from __future__ import annotations

from pathlib import Path

from .base import Tool


def _pdf_extract(
    path: str,
    output_path: str = "",
    start_page: int = 1,
    end_page: int | None = None,
    overwrite: bool = False,
) -> str:
    """Extract a 1-based inclusive page range from a PDF into a UTF-8 text file."""
    source = Path(path)
    if not source.exists():
        return f"错误：PDF 文件不存在：{path}"
    if not source.is_file():
        return f"错误：路径不是文件：{path}"
    if source.suffix.lower() != ".pdf":
        return f"错误：仅支持 .pdf 文件：{path}"
    if start_page < 1:
        return "错误：start_page 必须大于等于 1。"

    target = Path(output_path) if output_path else source.with_suffix(".txt")
    if target.suffix.lower() != ".txt":
        return f"错误：输出文件必须使用 .txt 后缀：{target}"
    if source.resolve() == target.resolve():
        return "错误：输出路径不能与 PDF 路径相同。"
    if target.exists() and not overwrite:
        try:
            source_mtime = source.stat().st_mtime_ns
            target_mtime = target.stat().st_mtime_ns
        except OSError as exc:
            return f"错误：无法检查 PDF 文本缓存状态：{exc}"

        if target_mtime >= source_mtime:
            return (
                f"已复用现有 PDF 文本缓存：{target}（{target.stat().st_size} 字节）；"
                "未重复转换。后续请直接用 read 或 grep 分段分析该文本。"
            )
        return (
            f"PDF 文本缓存已过期：源文件 {source} 比 {target} 更新；"
            "为避免覆盖可能经过人工编辑的文本，本次未转换。"
            "确认需要刷新后请设置 overwrite=true。"
        )

    try:
        from PyPDF2 import PdfReader
    except ModuleNotFoundError:
        return "错误：缺少 PyPDF2，请先安装 requirements.txt。"

    try:
        reader = PdfReader(str(source))
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                return f"错误：PDF 已加密且无法使用空密码解密：{path}"

        total_pages = len(reader.pages)
        last_page = total_pages if end_page is None else end_page
        if last_page < start_page:
            return "错误：end_page 必须大于等于 start_page。"
        if start_page > total_pages or last_page > total_pages:
            return (
                f"错误：页码超出范围；PDF 共 {total_pages} 页，"
                f"请求提取第 {start_page}-{last_page} 页。"
            )

        sections: list[str] = []
        empty_pages: list[int] = []
        for page_number in range(start_page, last_page + 1):
            text = reader.pages[page_number - 1].extract_text() or ""
            text = text.strip()
            if not text:
                empty_pages.append(page_number)
                text = "[本页未提取到文本，可能是扫描页或空白页]"
            sections.append(f"=== Page {page_number} ===\n{text}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"错误：PDF 文本提取失败：{type(exc).__name__}: {exc}"

    empty_note = (
        "；未提取到文本的页：" + ", ".join(map(str, empty_pages))
        if empty_pages
        else ""
    )
    return (
        f"已将 {source} 第 {start_page}-{last_page} 页提取到 {target}，"
        f"共 {last_page - start_page + 1} 页，UTF-8 文本 {target.stat().st_size} 字节"
        f"{empty_note}。后续请用 read 或 grep 分段分析该文本。"
    )


pdf_extract_tool = Tool(
    name="pdf_extract",
    description=(
        "幂等地把 PDF 的指定页码范围提取为 UTF-8 .txt 文件。默认输出存在且不旧时"
        "直接复用，不重复转换；输出比 PDF 旧时提示缓存过期且不自动覆盖。"
        "仅在用户明确要求刷新过期缓存时设置 overwrite=true。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "输入 PDF 路径"},
            "output_path": {
                "type": "string",
                "description": "输出 .txt 路径；默认与 PDF 同名",
            },
            "start_page": {
                "type": "integer",
                "description": "起始页，1-based，默认 1",
            },
            "end_page": {
                "type": "integer",
                "description": "结束页，包含该页；默认最后一页",
            },
            "overwrite": {
                "type": "boolean",
                "description": "是否强制覆盖已有输出，默认 false；仅用于明确刷新过期缓存",
            },
        },
        "required": ["path"],
    },
    run=_pdf_extract,
)
