"""受控 shell 执行（Day4：bash；Day8：加沙箱与权限）。"""
from __future__ import annotations
import subprocess

from .base import Tool


def _bash(command: str, timeout: int = 30) -> str:
    """执行一条 shell 命令，返回 stdout/stderr/returncode。"""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        output = []
        if e.stdout:
            output.append(f"[stdout]\n{e.stdout}")
        if e.stderr:
            output.append(f"[stderr]\n{e.stderr}")
        output.append(f"错误：命令超时（>{timeout}s）：{command}")
        return "\n".join(output)
    except Exception as e:  # noqa: BLE001
        return f"错误：命令执行失败：{e}"

    parts: list[str] = []
    if proc.stdout:
        parts.append(f"[stdout]\n{proc.stdout.rstrip()}")
    if proc.stderr:
        parts.append(f"[stderr]\n{proc.stderr.rstrip()}")
    if proc.returncode != 0:
        parts.append(f"[returncode={proc.returncode}]")
    if not parts:
        return "[命令执行成功，无输出]"
    return "\n".join(parts)


bash_tool = Tool(
    name="bash",
    description="在工作目录中执行一条 shell 命令并返回 stdout、stderr 和退出码。适合运行测试、查看环境、执行项目命令。",
    parameters={"type": "object",
                "properties": {"command": {"type": "string"},
                               "timeout": {"type": "integer", "description": "超时时间（秒），默认 30"}},
                "required": ["command"]},
    run=_bash,
)
