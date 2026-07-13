"""受控 shell 执行（Day4：bash；Day8：加沙箱与权限）。"""
from __future__ import annotations
import shutil
import subprocess
import re

from .base import Tool

# 命令黑名单不可枚举穷尽（讲义 §2）；仅作 bwrap 缺失时的兜底防线。
_DENY = (":(){", "mkfs", "dd if=", "> /dev/sd", "curl", "wget")
_DANGEROUS_RE = re.compile(
    r"(?:"
    r"\brm\s+-[^\n]*r[^\n]*f|"
    r"\bRemove-Item\b[^\n]*(?:-Recurse|-Force)|"
    r"\b(?:rmdir|rd)\s+/s\b|"
    r"\bshutil\.rmtree\b|"
    r"\b(?:python(?:3)?\s+[^\n]*(?:train|finetune|fine_tune)\.py\b)|"
    r"\b(?:torchrun|deepspeed)\b|"
    r"\baccelerate\s+launch\b|"
    r"\b(?:bash|sh)\s+[^\n]*(?:train|finetune)[^\n]*\.sh\b|"
    r"\b(?:pip|conda|mamba)\s+install\b|"
    r"\bgit\s+clone\b"
    r")",
    re.I,
)


def is_denylisted(command: str) -> bool:
    """纯字符串判定，不执行命令；供红队测试等场景探测黑名单命中面。"""
    return any(bad in command for bad in _DENY) or bool(_DANGEROUS_RE.search(command))


def _build_command(command: str) -> list[str]:
    if shutil.which("bwrap"):
        # 只读挂载系统根、可写仅工作目录、禁网：即使命令本身失控也限制破坏面。
        return ["bwrap", "--ro-bind", "/", "/", "--bind", ".", ".",
                "--unshare-net", "--dev", "/dev", "bash", "-c", command]
    return ["bash", "-c", command]


def _bash(command: str, timeout: int = 30) -> str:
    """在沙箱中执行一条 shell 命令，返回 stdout/stderr/returncode。"""
    if is_denylisted(command):
        return f"[沙箱] 拒绝执行破坏性、训练、下载或安装命令：{command}"

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
    description="执行受控的短时 shell 命令；拒绝递归删除、完整训练、数据/代码下载和依赖安装。审计任务不使用此工具。",
    parameters={"type": "object",
                "properties": {"command": {"type": "string"},
                               "timeout": {"type": "integer", "description": "超时时间（秒），默认 30"}},
                "required": ["command"]},
    run=_bash,
)
