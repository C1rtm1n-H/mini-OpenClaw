"""极小轨迹记录器：一步一行 JSON（JSONL），可回放。

讲义 §11：一个没有 trace 的 agent 无法被认真评估，也几乎无法被调试。
D4 起真 agent 每跑一步都应调用 tracer.log_step()，把所有工具调用和 token
用量写入 JSONL。步骤 2 的四项指标本质上都是对这种结构化 trace 的事后聚合——
先记录，后评估。

设计原则：
  - 每步一行 JSON（JSONL），可流式追加，不占内存。
  - 包含 ts（时间戳）、step（步号）、tool_calls、token 计数、note（可选备注）。
  - replay() 可把轨迹逐步回放打印，方便人工审查。
"""
from __future__ import annotations
import json
import time
from pathlib import Path


class Tracer:
    """轨迹记录器：创建时清空/新建文件，之后每步追加一行 JSON。"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.write_text("", encoding="utf-8")   # 清空/新建

    def log_step(self, step: int, tool_calls: list, prompt_tokens: int,
                 completion_tokens: int, note: str = "") -> None:
        """记录一步：工具调用 + token 计数 + 可选备注。"""
        event = {
            "ts": round(time.time(), 3),
            "step": step,
            "tool_calls": tool_calls,
            "note": note,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def replay(path: str) -> None:
    """把一条 JSONL 轨迹逐步打印出来（回放）。"""
    total_tok = 0
    content = Path(path).read_text(encoding="utf-8")
    if not content.strip():
        print("  （轨迹为空）")
        return
    for line in content.splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        tok = e["prompt_tokens"] + e["completion_tokens"]
        total_tok += tok
        names = [tc["name"] for tc in e["tool_calls"]] or ["(无工具调用)"]
        print(f"  step {e['step']}: 调用 {names}  |  本步 {tok} tok  |  {e.get('note', '')}")
    print(f"  —— 轨迹共 {total_tok} token")


if __name__ == "__main__":
    # 用步骤 2 的一条样本喂进来（模拟 D4 真 agent 逐步 log 的效果）
    from eval.metrics import SAMPLE_RECORDS

    rec = SAMPLE_RECORDS[0]
    tr = Tracer("eval/trace_sample.jsonl")
    for i, s in enumerate(rec["steps"]):
        tr.log_step(i, s.get("tool_calls", []),
                    s.get("prompt_tokens", 0), s.get("completion_tokens", 0),
                    note=s.get("raw", "")[:40])
    print(f"已写入 eval/trace_sample.jsonl（任务={rec['task']}）；回放：")
    replay("eval/trace_sample.jsonl")
