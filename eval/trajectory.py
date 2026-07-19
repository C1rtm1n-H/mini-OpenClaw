"""真实评估轨迹：把 AgentLoop 事件聚合成可评估的 JSONL record。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "eval_record_v1"


def now_ts() -> float:
    return round(time.time(), 3)


def preview(text: str, limit: int = 800) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "..."


def looks_permission_blocked(observation: str) -> bool:
    return "[权限层]" in observation


def looks_tool_ok(observation: str, returncode: int | None = None) -> bool:
    if returncode not in (None, 0):
        return False
    bad_markers = ("[权限层]", "[沙箱] 拒绝", "错误：", "Traceback")
    return not any(marker in observation for marker in bad_markers)


class TrajectoryRecorder:
    """把 AgentLoop 的 trajectory_sink 事件聚合为一次任务运行 record。"""

    def __init__(self, task: Any, agent_meta: dict[str, Any] | None = None,
                 run_id: str | None = None):
        self.task = task
        self.record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id or uuid.uuid4().hex,
            "task": getattr(task, "name", str(task)),
            "instruction": getattr(task, "instruction", ""),
            "started_at": now_ts(),
            "ended_at": None,
            "status": "running",
            "final": "",
            "agent": agent_meta or {},
            "steps": [],
            "events": [],
            "summary": {},
        }

    def sink(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("ts", now_ts())
        self.record["events"].append(event)

        typ = event.get("type")
        if typ == "llm":
            self._add_llm_step(event)
        elif typ == "tool_result":
            self._add_tool_result(event)
        elif typ == "final":
            self.record["status"] = event.get("status") or "completed"
            self.record["final"] = event.get("content", "")
            self.record["ended_at"] = event["ts"]

    def finish(self, final: str | None = None, status: str | None = None,
               spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if final is not None:
            self.record["final"] = final
        if status is not None:
            self.record["status"] = status
        if self.record["status"] == "running":
            self.record["status"] = "completed"
        self.record["ended_at"] = self.record.get("ended_at") or now_ts()
        if spans is not None:
            self.record["spans"] = spans
        self.record["summary"] = summarize_record(self.record)
        return self.record

    def _add_llm_step(self, event: dict[str, Any]) -> None:
        raw_calls = event.get("tool_calls") or []
        tool_calls = []
        for i, call in enumerate(raw_calls):
            args = call.get("arguments") if isinstance(call, dict) else {}
            tool_calls.append({
                "id": call.get("id") or f"call_{len(self.record['steps'])}_{i}",
                "name": call.get("name"),
                "arguments": args if isinstance(args, dict) else {},
                "raw_arguments": call.get("raw_arguments"),
                "arguments_parse_ok": call.get("arguments_parse_ok", isinstance(args, dict)),
                "arguments_parse_error": call.get("arguments_parse_error"),
            })
        usage = event.get("usage") or {}
        self.record["steps"].append({
            "index": len(self.record["steps"]),
            "turn": event.get("turn"),
            "assistant_content": event.get("content", ""),
            "raw": event.get("content", ""),
            "tool_calls": tool_calls,
            "tool_results": [],
            "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
            "completion_tokens": usage.get("completion_tokens", 0) or 0,
            "usage": usage,
        })

    def _add_tool_result(self, event: dict[str, Any]) -> None:
        if not self.record["steps"]:
            self.record["steps"].append({
                "index": 0,
                "turn": event.get("turn"),
                "assistant_content": "",
                "raw": "",
                "tool_calls": [],
                "tool_results": [],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "usage": {},
            })
        observation = event.get("observation", "") or ""
        returncode = event.get("returncode")
        result = {
            "tool_call_id": event.get("tool_call_id"),
            "name": event.get("name"),
            "observation": observation,
            "observation_preview": preview(observation),
            "ok": event.get("ok", looks_tool_ok(observation, returncode)),
            "permission_blocked": event.get("permission_blocked", looks_permission_blocked(observation)),
            "returncode": returncode,
        }
        for step in reversed(self.record["steps"]):
            if step.get("turn") == event.get("turn"):
                step.setdefault("tool_results", []).append(result)
                return
        self.record["steps"][-1].setdefault("tool_results", []).append(result)


def summarize_record(record: dict[str, Any]) -> dict[str, Any]:
    steps = record.get("steps", [])
    tool_results = [tr for s in steps for tr in s.get("tool_results", [])]
    tool_calls = [tc for s in steps for tc in s.get("tool_calls", [])]
    prompt_tokens = sum(s.get("prompt_tokens", 0) or 0 for s in steps)
    completion_tokens = sum(s.get("completion_tokens", 0) or 0 for s in steps)
    return {
        "llm_calls": len(steps),
        "tool_calls": len(tool_calls),
        "tool_results": len(tool_results),
        "tools_used": sorted({tc.get("name") for tc in tool_calls if tc.get("name")}),
        "tool_successes": sum(1 for tr in tool_results if tr.get("ok")),
        "permission_blocked": sum(1 for tr in tool_results if tr.get("permission_blocked")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens": prompt_tokens + completion_tokens,
    }


def record_to_judge_digest(record: dict[str, Any], observation_limit: int = 600) -> str:
    lines = [
        f"任务: {record.get('task')}",
        f"指令: {record.get('instruction')}",
        f"状态: {record.get('status')}",
        f"最终答案: {preview(record.get('final', ''), 1200)}",
        "轨迹证据:",
    ]
    for step in record.get("steps", []):
        lines.append(f"- step {step.get('index')}: assistant={preview(step.get('assistant_content', ''), 240)!r}")
        for tc in step.get("tool_calls", []):
            lines.append(
                f"  tool_call {tc.get('id')}: {tc.get('name')} args={json.dumps(tc.get('arguments', {}), ensure_ascii=False)} "
                f"parse_ok={tc.get('arguments_parse_ok', True)}"
            )
        for tr in step.get("tool_results", []):
            lines.append(
                f"  tool_result {tr.get('tool_call_id')}: {tr.get('name')} ok={tr.get('ok')} "
                f"returncode={tr.get('returncode')} permission_blocked={tr.get('permission_blocked')} "
                f"obs={preview(tr.get('observation', ''), observation_limit)!r}"
            )
    lines.append(f"摘要: {json.dumps(record.get('summary', summarize_record(record)), ensure_ascii=False)}")
    return "\n".join(lines)


def append_jsonl(path: str | Path, obj: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def write_json(path: str | Path, obj: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
