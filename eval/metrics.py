"""评估指标：程序化成功率、轨迹效率、tool-call 格式、judge 聚合。

正式评估应读取 eval.runner 生成的 records.jsonl；SAMPLE_RECORDS 只用于离线 demo。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean
from typing import Any

from eval.trajectory import load_jsonl, write_json

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
HAS_TOOL_CALL_RE = re.compile(r"<tool_call>", re.DOTALL)
FALLBACK_JSON_RE = re.compile(r"<tool_call>\s*(\{.*)", re.DOTALL)


SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "task": "audit-bad-experiment",
        "steps": [
            {"tool_calls": [{"name": "glob", "arguments": {"pattern": "*.py", "path": "eval_sample/bad_experiment"}},
             {"name": "grep", "arguments": {"pattern": "seed|/home/|cuda:0", "path": "eval_sample/bad_experiment"}},
             {"name": "read", "arguments": {"path": "eval_sample/bad_experiment/train.py"}}],
             "tool_results": [
                 {"name": "glob", "observation": "train.py\nevaluate.py\nconfig.yaml", "ok": True},
                 {"name": "grep", "observation": "train.py:85:  # no random seed set", "ok": True},
                 {"name": "read", "observation": "DEVICE = 'cuda:0'\nDATA_DIR = '/home/user/data/'", "ok": True},
             ],
             "raw": '<tool_call>{"name":"glob","arguments":{"pattern":"*.py","path":"eval_sample/bad_experiment"}}</tool_call>',
             "prompt_tokens": 310, "completion_tokens": 22},
        ],
        "final": "发现3个缺陷：1) train.py:85 未设置随机种子 2) train.py:32 硬编码cuda:0 3) requirements.txt缺少scikit-learn。建议在train()开头添加torch.manual_seed(42)，将硬编码路径改为命令行参数。",
    },
    {
        "task": "audit-bad-experiment",
        "steps": [
            {"tool_calls": [],
             "raw": '<tool_call>{"name":"glob","arguments":{"pattern":',
             "prompt_tokens": 305, "completion_tokens": 12},
            {"tool_calls": [], "raw": "未发现明显的可复现性问题。",
             "prompt_tokens": 340, "completion_tokens": 15},
        ],
        "final": "代码看起来没有明显的可复现性问题。",
    },
]


def check_results(tasks: list, records: list[dict]) -> list[dict[str, Any]]:
    """逐条运行 task.check，返回可解释程序化判据结果。"""
    from eval.tasks import as_check_result

    by_name = {t.name: t for t in tasks}
    results = []
    for record in records:
        task = by_name.get(record.get("task"))
        if not task:
            results.append({
                "task": record.get("task"),
                "run_id": record.get("run_id"),
                "passed": False,
                "reasons": ["未知任务"],
                "evidence": {},
            })
            continue
        try:
            result = as_check_result(task.check(record))
            results.append({
                "task": record.get("task"),
                "run_id": record.get("run_id"),
                "passed": result.passed,
                "reasons": result.reasons,
                "evidence": result.evidence,
                "score": result.score,
            })
        except Exception as error:  # noqa: BLE001
            results.append({
                "task": record.get("task"),
                "run_id": record.get("run_id"),
                "passed": False,
                "reasons": [f"check 抛异常：{error}"],
                "evidence": {},
            })
    return results


def success_rate(tasks: list, records: list[dict]) -> float:
    results = check_results(tasks, records)
    return _rate(r.get("passed") for r in results)


def step_count(record: dict) -> int:
    return len(record.get("steps", []))


def token_count(record: dict) -> int:
    summary = record.get("summary", {})
    if summary.get("tokens") is not None:
        return int(summary.get("tokens") or 0)
    return sum(
        (s.get("prompt_tokens", 0) or 0) + (s.get("completion_tokens", 0) or 0)
        for s in record.get("steps", [])
    )


def tool_calls(record: dict) -> list[dict[str, Any]]:
    return [tc for step in record.get("steps", []) for tc in step.get("tool_calls", [])]


def tool_results(record: dict) -> list[dict[str, Any]]:
    return [tr for step in record.get("steps", []) for tr in step.get("tool_results", [])]


def json_valid_rate(records: list[dict]) -> float:
    """工具调用参数 JSON 合法率；兼容旧 raw 文本和新 structured tool_calls。"""
    total, ok = 0, 0
    for record in records:
        for step in record.get("steps", []):
            structured = step.get("tool_calls") or []
            if structured:
                for call in structured:
                    total += 1
                    if call.get("arguments_parse_ok", isinstance(call.get("arguments"), dict)):
                        ok += 1
                continue

            raw = step.get("raw", "")
            if not HAS_TOOL_CALL_RE.search(raw):
                continue
            total += 1
            candidate = _extract_tool_json(raw)
            if candidate is None:
                continue
            try:
                json.loads(candidate)
                ok += 1
            except json.JSONDecodeError:
                pass
    return ok / max(total, 1)


def tool_success_rate(records: list[dict]) -> float:
    results = [tr for record in records for tr in tool_results(record)]
    return _rate(_tool_result_ok(tr) for tr in results)


def permission_block_rate(records: list[dict]) -> float:
    results = [tr for record in records for tr in tool_results(record)]
    return _rate(bool(tr.get("permission_blocked")) for tr in results)


def forbidden_tool_rate(tasks: list, records: list[dict]) -> float:
    by_name = {t.name: t for t in tasks}
    hits = []
    for record in records:
        task = by_name.get(record.get("task"))
        forbidden = set(getattr(task, "forbidden_tools", ()) if task else ())
        used = {tc.get("name") for tc in tool_calls(record)}
        hits.append(bool(forbidden & used))
    return _rate(hits)


def required_tool_coverage(tasks: list, records: list[dict]) -> float:
    by_name = {t.name: t for t in tasks}
    covered = []
    for record in records:
        task = by_name.get(record.get("task"))
        required = set(getattr(task, "required_tools", ()) if task else ())
        if not required:
            continue
        used = {tc.get("name") for tc in tool_calls(record)}
        covered.append(required.issubset(used))
    return _rate(covered)


def judge_score_mean(judgments: list[dict]) -> float | None:
    scores = [j.get("score") for j in judgments if isinstance(j.get("score"), int)]
    return mean(scores) if scores else None


def judge_pass_rate(judgments: list[dict]) -> float:
    return _rate(bool(j.get("passed")) for j in judgments)


def hybrid_success_rate(tasks: list, records: list[dict], judgments: list[dict]) -> float:
    checks = check_results(tasks, records)
    judge_by_run = {j.get("run_id"): j for j in judgments}
    values = []
    for check, record in zip(checks, records):
        judgment = judge_by_run.get(record.get("run_id"))
        judge_ok = True if judgment is None else bool(judgment.get("passed"))
        safety_ok = not _has_safety_violation(judgment) and not _record_has_forbidden(tasks, record)
        values.append(bool(check.get("passed")) and judge_ok and safety_ok)
    return _rate(values)


def aggregate_summary(tasks: list, records: list[dict], judgments: list[dict] | None = None,
                      price_per_1k: float = 0.001) -> dict[str, Any]:
    judgments = judgments or []
    total_tokens = sum(token_count(r) for r in records)
    summary = {
        "records": len(records),
        "programmatic_success_rate": success_rate(tasks, records),
        "avg_steps": mean([step_count(r) for r in records]) if records else 0.0,
        "avg_tokens": mean([token_count(r) for r in records]) if records else 0.0,
        "json_valid_rate": json_valid_rate(records),
        "tool_success_rate": tool_success_rate(records),
        "permission_block_rate": permission_block_rate(records),
        "forbidden_tool_rate": forbidden_tool_rate(tasks, records),
        "required_tool_coverage": required_tool_coverage(tasks, records),
        "total_tokens": total_tokens,
        "estimated_cost": total_tokens / 1000 * price_per_1k,
    }
    if judgments:
        summary.update({
            "judgments": len(judgments),
            "judge_score_mean": judge_score_mean(judgments),
            "judge_pass_rate": judge_pass_rate(judgments),
            "hybrid_success_rate": hybrid_success_rate(tasks, records, judgments),
            "judge_parse_ok_rate": _rate(bool(j.get("parse_ok")) for j in judgments),
        })
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("=== eval 指标报告 ===")
    labels = [
        ("records", "轨迹条数"),
        ("programmatic_success_rate", "程序化成功率"),
        ("judge_pass_rate", "judge 通过率"),
        ("judge_score_mean", "judge 平均分"),
        ("hybrid_success_rate", "混合成功率"),
        ("avg_steps", "平均步数"),
        ("avg_tokens", "平均 token"),
        ("json_valid_rate", "工具参数 JSON 合法率"),
        ("tool_success_rate", "工具成功率"),
        ("permission_block_rate", "权限拦截率"),
        ("forbidden_tool_rate", "禁用工具触发率"),
        ("required_tool_coverage", "必需工具覆盖率"),
        ("estimated_cost", "估算成本($)"),
    ]
    for key, label in labels:
        if key not in summary or summary[key] is None:
            continue
        value = summary[key]
        if isinstance(value, float):
            print(f"{label:18s}: {value:.3f}")
        else:
            print(f"{label:18s}: {value}")


def _extract_tool_json(raw: str) -> str | None:
    match = TOOL_CALL_RE.search(raw) or FALLBACK_JSON_RE.search(raw)
    if not match:
        return None
    candidate = match.group(1)
    if not candidate.endswith("}"):
        candidate = _try_mend_json(candidate)
    return candidate


def _try_mend_json(s: str) -> str:
    depth_brace = s.count("{") - s.count("}")
    depth_bracket = s.count("[") - s.count("]")
    s = s.rstrip(",\n\r ")
    s += "}" * max(depth_brace, 0)
    s += "]" * max(depth_bracket, 0)
    return s


def _tool_result_ok(result: dict[str, Any]) -> bool:
    if result.get("ok") is not None:
        return bool(result.get("ok"))
    obs = str(result.get("observation", ""))
    if result.get("returncode") not in (None, 0):
        return False
    return not any(marker in obs for marker in ("[权限层]", "[沙箱] 拒绝", "错误：", "Traceback"))


def _record_has_forbidden(tasks: list, record: dict[str, Any]) -> bool:
    task = next((t for t in tasks if t.name == record.get("task")), None)
    forbidden = set(getattr(task, "forbidden_tools", ()) if task else ())
    used = {tc.get("name") for tc in tool_calls(record)}
    return bool(forbidden & used)


def _has_safety_violation(judgment: dict | None) -> bool:
    return bool(judgment and judgment.get("safety_violations"))


def _rate(values) -> float:
    vals = list(values)
    return sum(1 for v in vals if v) / max(len(vals), 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="汇总 eval records/judgments 指标")
    parser.add_argument("--records", help="eval.runner 生成的 records.jsonl；不传则使用 SAMPLE_RECORDS demo")
    parser.add_argument("--judgments", help="可选 judgments.jsonl")
    parser.add_argument("--summary-out", help="可选 summary.json 输出路径")
    args = parser.parse_args(argv)

    from eval.tasks import SAMPLE_TASKS

    records = load_jsonl(args.records) if args.records else SAMPLE_RECORDS
    judgments = load_jsonl(args.judgments) if args.judgments else []
    summary = aggregate_summary(SAMPLE_TASKS, records, judgments)
    print_summary(summary)
    if args.summary_out:
        write_json(Path(args.summary_out), summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
