"""真实 eval runner：运行 AgentLoop，保存 records/judgments/summary。

默认只启用只读工具和只读任务，避免把评估变成安装、下载、训练或脚本执行。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from agent.loop import AgentLoop
from agent.prompts import SYSTEM_PROMPT
from agent.tracer import Tracer
from backend.fake_backend import FakeBackend
from eval.judge import JudgeConfig, judge_record
from eval.metrics import aggregate_summary
from eval.tasks import SAMPLE_TASKS, Task, select_tasks
from eval.trajectory import TrajectoryRecorder, append_jsonl, write_json
from tools.base import ToolRegistry
from tools.fs import read_tool
from tools.more_tools import glob_tool, grep_tool
from tools.pdf import pdf_extract_tool
from tools.shell import bash_tool
from tools.todo_tools import todo_write_tool, update_todo_tool
from tools.skill_tools import invoke_skill_tool


MINIMAL_SYSTEM_PROMPT = """你是 mini-OpenClaw 的评估对象。请严格完成用户任务。
需要证据时必须使用可用工具；不要猜测；默认只做只读分析。"""


def build_readonly_registry() -> ToolRegistry:
    """评估默认工具集：只读文件/搜索能力。"""
    registry = ToolRegistry()
    for tool in (read_tool, grep_tool, glob_tool, pdf_extract_tool, bash_tool,
                  todo_write_tool, update_todo_tool, invoke_skill_tool):
        registry.register(tool)
    return registry


def build_backend(kind: str) -> Any:
    if kind == "fake":
        return FakeBackend()
    if kind == "real":
        from backend.client import DeepSeekBackend
        return DeepSeekBackend()
    if os.environ.get("DEEPSEEK_API_KEY"):
        from backend.client import DeepSeekBackend
        return DeepSeekBackend()
    return FakeBackend()


def build_agent(backend: Any, recorder: TrajectoryRecorder, *, system_prompt: str,
                workdir: Path, max_turns: int, max_steps: int) -> AgentLoop:
    return AgentLoop(
        backend,
        build_readonly_registry(),
        system_prompt,
        workdir=workdir,
        max_turns=max_turns,
        max_steps=max_steps,
        auto_approve=True,  # eval only registers readonly tools; confirm level is safe
        tracer=Tracer(),
        trajectory_sink=recorder.sink,
    )


def run_task(task: Task, *, backend_kind: str, system_variant: str, workdir: Path,
             max_turns: int, max_steps: int, repeat_index: int) -> dict[str, Any]:
    backend = build_backend(backend_kind)
    system_prompt = MINIMAL_SYSTEM_PROMPT if system_variant == "minimal" else SYSTEM_PROMPT
    agent_meta = {
        "backend": type(backend).__name__,
        "model": getattr(backend, "model", "fake"),
        "max_turns": max_turns,
        "max_steps": max_steps,
        "workdir": str(workdir),
        "system_variant": system_variant,
        "repeat_index": repeat_index,
        "tool_registry": build_readonly_registry().names(),
    }
    recorder = TrajectoryRecorder(task, agent_meta=agent_meta)
    agent = build_agent(
        backend,
        recorder,
        system_prompt=system_prompt,
        workdir=workdir,
        max_turns=max_turns,
        max_steps=max_steps,
    )
    try:
        final = agent.run(task.instruction)
        return recorder.finish(final=final, spans=agent.tracer.spans)
    except Exception as error:  # noqa: BLE001
        recorder.sink({"type": "final", "status": "exception", "content": f"错误：{error}", "error": str(error)})
        return recorder.finish(final=f"错误：{error}", status="exception", spans=agent.tracer.spans)


def run_suite(tasks: list[Task], *, out_dir: Path, backend_kind: str = "auto",
              system_variant: str = "default", workdir: Path | None = None,
              max_turns: int = 8, max_steps: int = 20, repeat: int = 1,
              run_judge: bool = False, judge_model: str | None = None) -> dict[str, Any]:
    workdir = (workdir or Path.cwd()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.jsonl"
    judgments_path = out_dir / "judgments.jsonl"
    for path in (records_path, judgments_path):
        if path.exists():
            path.unlink()

    manifest = {
        "created_at": round(time.time(), 3),
        "backend": backend_kind,
        "system_variant": system_variant,
        "workdir": str(workdir),
        "max_turns": max_turns,
        "max_steps": max_steps,
        "repeat": repeat,
        "judge": run_judge,
        "tasks": [task.name for task in tasks],
        "note": "FakeBackend 只验证管线，不代表真实 agent 能力。runner 工具集：read/grep/glob/pdf_extract/bash（bash 受权限层限制，禁止训练/下载/危险命令）。",
    }
    write_json(out_dir / "manifest.json", manifest)

    records: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    for i in range(repeat):
        for task in tasks:
            record = run_task(
                task,
                backend_kind=backend_kind,
                system_variant=system_variant,
                workdir=workdir,
                max_turns=max_turns,
                max_steps=max_steps,
                repeat_index=i,
            )
            records.append(record)
            append_jsonl(records_path, record)
            if run_judge and task.judge_required:
                judgment = judge_record(task, record, JudgeConfig(model=judge_model))
                judgments.append(judgment)
                append_jsonl(judgments_path, judgment)

    summary = aggregate_summary(SAMPLE_TASKS, records, judgments)
    write_json(out_dir / "summary.json", summary)
    return {"out_dir": str(out_dir), "records": records, "judgments": judgments, "summary": summary}


def default_out_dir(root: Path | None = None, system_variant: str = "default") -> Path:
    root = root or Path("eval/runs")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return root / f"{stamp}-{system_variant}"


def parse_task_names(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行真实 agent eval 并保存轨迹")
    parser.add_argument("--backend", choices=["auto", "real", "fake"], default="auto")
    parser.add_argument("--tasks", help="逗号分隔任务名；默认跑只读 DEFAULT_TASKS")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--out", help="输出目录；默认 eval/runs/<timestamp>")
    parser.add_argument("--system-variant", choices=["default", "minimal"], default="default")
    parser.add_argument("--judge", action="store_true", help="运行 LLM-as-judge")
    parser.add_argument("--no-judge", action="store_true", help="显式跳过 judge")
    parser.add_argument("--judge-model")
    args = parser.parse_args(argv)

    task_names = parse_task_names(args.tasks)
    tasks = select_tasks(task_names, readonly_only=True)
    out_dir = Path(args.out) if args.out else default_out_dir(system_variant=args.system_variant)
    result = run_suite(
        tasks,
        out_dir=out_dir,
        backend_kind=args.backend,
        system_variant=args.system_variant,
        workdir=Path(args.workdir),
        max_turns=args.max_turns,
        max_steps=args.max_steps,
        repeat=args.repeat,
        run_judge=args.judge and not args.no_judge,
        judge_model=args.judge_model,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"输出目录：{result['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
