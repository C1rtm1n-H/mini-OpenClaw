"""受控 shell 执行（Day4：bash；Day8：加沙箱与权限）。"""
from __future__ import annotations
import os
import shutil
import subprocess

from .base import Tool

# 命令黑名单不可枚举穷尽（讲义 §2）；仅作 bwrap 缺失时的兜底防线。
_DENY = ("rm -rf /", "rm -rf ~", "rm -rf *", ":(){", "mkfs", "dd if=", "> /dev/sd", "curl", "wget")


def is_denylisted(command: str) -> bool:
    """纯字符串判定，不执行命令；供红队测试等场景探测黑名单命中面。"""
    return any(bad in command for bad in _DENY)


def _build_command(command: str) -> list[str]:
    if os.name == "nt":
        # 继承启动 mini-OpenClaw 的 PowerShell/Conda PATH，避免误入 WSL bash
        # 后找不到当前环境中的 python、py 等 Windows 可执行文件。
        shell = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
        return [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    if shutil.which("bwrap"):
        # 只读挂载系统根、可写仅工作目录、禁网：即使命令本身失控也限制破坏面。
        return ["bwrap", "--ro-bind", "/", "/", "--bind", ".", ".",
                "--unshare-net", "--dev", "/dev", "bash", "-c", command]
    return ["bash", "-c", command]


def _bash(command: str, timeout: int = 30) -> str:
    """在沙箱中执行一条 shell 命令，返回 stdout/stderr/returncode。"""
    if is_denylisted(command):
        return f"[沙箱] 拒绝执行高危命令：{command}"

    try:
        proc = subprocess.run(
            _build_command(command),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
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
    description="执行一条受控 shell 命令并返回 stdout、stderr 和退出码；Windows 使用 PowerShell 并继承当前 Python/Conda 环境，其他平台使用 bash。适合毫秒级验证，不执行训练或下载。",
    parameters={"type": "object",
                "properties": {"command": {"type": "string"},
                               "timeout": {"type": "integer", "description": "超时时间（秒），默认 30"}},
                "required": ["command"]},
    run=_bash,
)
