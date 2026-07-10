"""Utilities for constructing multimodal user-message content blocks."""
from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any


def image_block(path: str | Path, media_type: str | None = None,
                max_edge: int = 1568) -> dict[str, Any]:
    """Encode an image as an Anthropic-style base64 content block."""
    image_path = Path(path)
    resolved_type = media_type or mimetypes.guess_type(image_path.name)[0] or "image/png"
    data = image_path.read_bytes()

    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError("图像输入需要 Pillow，请先安装 requirements.txt") from exc

    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge))
            output = io.BytesIO()
            output_format = image.format or _format_for_media_type(resolved_type)
            if output_format.upper() == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(output, format=output_format)
            data = output.getvalue()

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": resolved_type,
            "data": base64.b64encode(data).decode("ascii"),
        },
    }


def user_content(text: str, image_paths: list[str]) -> list[dict[str, Any]]:
    """Build mixed text and image content for one user message."""
    return [{"type": "text", "text": text}, *(image_block(path) for path in image_paths)]


def _format_for_media_type(media_type: str) -> str:
    return {"image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}.get(
        media_type, "PNG"
    )
