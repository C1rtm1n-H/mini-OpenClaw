"""真实轨迹消融：固定任务集，只改变 system prompt variant。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from eval.runner import run_suite
from eval.tasks import select_tasks
from eval.trajectory import write_json


DEFAULT_ABLATION_TASKS = "audit-bad-experiment,detect-prompt-injection"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="基于真实 AgentLoop 轨迹做 system prompt 消融")
    parser.add_argument("--backend", choices=["auto", "real", "fake"], default="auto")
    parser.add_argument("--tasks", default=DEFAULT_ABLATION_TASKS,
                        help="逗号分隔任务名；默认选两个只读任务做最小消融")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--out", help="输出根目录；默认 eval/runs/<timestamp>-ablation")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model")
    args = parser.parse_args(argv)

    names = [part.strip() for part in args.tasks.split(",") if part.strip()]
    tasks = select_tasks(names, readonly_only=True)
    root = Path(args.out) if args.out else Path("eval/runs") / f"{time.strftime('%Y%m%d-%H%M%S')}-ablation"
    root.mkdir(parents=True, exist_ok=True)

    variants = {
        "default": root / "default-system",
        "minimal": root / "minimal-system",
    }
    results = {}
    for variant, out_dir in variants.items():
        results[variant] = run_suite(
            tasks,
            out_dir=out_dir,
            backend_kind=args.backend,
            system_variant=variant,
            workdir=Path(args.workdir),
            max_turns=args.max_turns,
            max_steps=args.max_steps,
            repeat=args.repeat,
            run_judge=args.judge,
            judge_model=args.judge_model,
        )["summary"]

    comparison = {
        "variable": "system_prompt",
        "fixed": {
            "tasks": [task.name for task in tasks],
            "backend": args.backend,
            "repeat": args.repeat,
            "max_turns": args.max_turns,
            "max_steps": args.max_steps,
            "workdir": str(Path(args.workdir).resolve()),
        },
        "variants": results,
        "deltas": _deltas(results.get("default", {}), results.get("minimal", {})),
        "limitations": [
            "小样本消融只能验证 harness 与趋势，不能当作稳健模型能力结论。",
            "LLM-as-judge 有方差和偏差，正式报告需要人工抽查校准。",
            "默认 runner 只启用 read/grep/glob，结论限定于只读任务。",
        ],
    }
    write_json(root / "comparison.json", comparison)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print(f"输出目录：{root}")
    return 0


def _deltas(default: dict, minimal: dict) -> dict:
    keys = ["programmatic_success_rate", "judge_pass_rate", "hybrid_success_rate", "avg_tokens", "tool_success_rate"]
    out = {}
    for key in keys:
        if isinstance(default.get(key), (int, float)) and isinstance(minimal.get(key), (int, float)):
            out[key] = default[key] - minimal[key]
    return out


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
