"""可观测性层：Tracer + 回放 + 成本核算（Day 9）。

把 agent 的每一步（LLM 调用、工具执行）结构化成可回放的 span，
同时持久化到 session 目录下的 JSONL，供事后分析和调试。

设计原则（讲义 §2 / §4）：
  - 每个 span = {kind, name, ok, ms, out, tokens, ...}
  - span() 用 finally 确保异常时也记录，且异常照常 raise
  - 回放只看关键字段；完整数据在 JSONL 里
  - token/成本核算从 LLM span 聚合
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any, Callable


class Tracer:
    """一次运行 = 一串 span。用统一包裹自动采集，不必处处埋点。

    用法::

        tracer = Tracer(session_dir=Path("/session/2026-07-14_15-30-00"))
        resp = tracer.span("llm", "decide", lambda: backend.chat(messages))
        obs  = tracer.span("tool", "read", lambda: registry.run("read", {...}))
    """

    def __init__(self, session_dir: str | Path | None = None):
        self.spans: list[dict[str, Any]] = []
        self.session_dir = Path(session_dir) if session_dir else None
        self._step = 0  # 全局递增步号

    # ------------------------------------------------------------------
    # 核心：span 包裹
    # ------------------------------------------------------------------

    def span(self, kind: str, name: str, fn: Callable[[], Any], **meta) -> Any:
        """执行 fn()，自动记录耗时/成败/输出摘要/额外 meta。

        如果 fn() 抛异常：记录 ok=False + 异常 repr，然后照常 raise——
        不会吞异常。"""
        t0 = time.time()
        ok, out = True, None
        try:
            out = fn()
            return out
        except Exception as e:
            ok, out = False, repr(e)
            raise
        finally:
            self._step += 1
            span_data: dict[str, Any] = {
                "step": self._step,
                "ts": round(time.time(), 3),
                "kind": kind,
                "name": name,
                "ok": ok,
                "ms": round((time.time() - t0) * 1000),
                "out": str(out)[:500] if out is not None else "",
                **meta,
            }
            self.spans.append(span_data)
            # 持久化到 session 目录
            self._append_jsonl(span_data)

    # ------------------------------------------------------------------
    # 便捷方法：更新最近一个 span 的字段（用于事后补 token 等）
    # ------------------------------------------------------------------

    def update_last(self, kind: str, **kwargs) -> None:
        """更新最近一个指定 kind 的 span 的字段。

        典型用法：LLM 调用之后把 usage 写进对应的 llm span。"""
        for s in reversed(self.spans):
            if s["kind"] == kind:
                s.update(kwargs)
                break
        # 同时更新 JSONL（重写最后一行）
        if self.session_dir:
            self._rewrite_last_jsonl()

    # ------------------------------------------------------------------
    # JSONL 持久化
    # ------------------------------------------------------------------

    @property
    def _jsonl_path(self) -> Path | None:
        if self.session_dir is None:
            return None
        self.session_dir.mkdir(parents=True, exist_ok=True)
        return self.session_dir / "trace.jsonl"

    def _append_jsonl(self, span_data: dict[str, Any]) -> None:
        path = self._jsonl_path
        if path is None:
            return
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(span_data, ensure_ascii=False) + "\n")

    def _rewrite_last_jsonl(self) -> None:
        """把 spans 完整重写到 JSONL（简单可靠）。"""
        path = self._jsonl_path
        if path is None:
            return
        with path.open("w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # 保存会话摘要
    # ------------------------------------------------------------------

    def save_summary(self) -> str | None:
        """把 cost_report 输出写入 session_dir/summary.txt，返回文本。"""
        if self.session_dir is None:
            return None
        text = cost_report(self, to_string=True)
        (self.session_dir / "summary.txt").write_text(text, encoding="utf-8")
        return text


# ---------------------------------------------------------------------------
# 回放（replay）：把一次运行渲染出来
# ---------------------------------------------------------------------------

def replay(tracer: Tracer) -> None:
    """打印一次运行的每一步：类型、名称、耗时、token、输出预览、异常标记。"""
    if not tracer.spans:
        print("  （无 trace 数据）")
        return
    for i, s in enumerate(tracer.spans, 1):
        tok = ("  %stok" % s.get("tokens")) if s.get("tokens") else ""
        flag = "" if s.get("ok", True) else "  ✗ FAIL"
        print("#%d %-4s %-12s %5dms%s  → %s%s"
              % (i, s["kind"], s["name"], s["ms"], tok, s.get("out", "")[:40], flag))


# ---------------------------------------------------------------------------
# token / 成本核算
# ---------------------------------------------------------------------------

def cost_report(tracer: Tracer, price_per_1k: float = 0.001,
                to_string: bool = False) -> str:
    """从 LLM span 聚合 token 与成本。

    price_per_1k 默认 $0.001（≈ deepseek-chat 价格数量级；可按实际调整）。
    """
    llm = [s for s in tracer.spans if s["kind"] == "llm" and s.get("tokens")]
    if not llm:
        msg = "（无 LLM span 或 token 数据）"
        if to_string:
            return msg
        print(msg)
        return msg

    total = sum(s["tokens"] for s in llm)
    priciest = max(llm, key=lambda s: s["tokens"], default=None)

    lines = [
        f"LLM 调用次数：{len(llm)}",
        f"总 token：{total}",
        f"估算成本：${total / 1000 * price_per_1k:.4f}  (@ ${price_per_1k}/1k tokens)",
    ]
    if priciest:
        lines.append(
            f"最贵一步：#{priciest.get('step', '?')} {priciest['name']}，"
            f"{priciest['tokens']} tok"
        )

    # 二次膨胀观测：打印每轮 prompt_tokens
    prompt_series = [s.get("prompt_tokens") for s in llm if s.get("prompt_tokens")]
    if len(prompt_series) >= 2:
        lines.append(
            f"每轮 prompt_tokens：{' → '.join(str(t) for t in prompt_series)}"
        )
        if prompt_series[-1] > prompt_series[0]:
            growth = prompt_series[-1] - prompt_series[0]
            lines.append(
                f"⚠ 二次膨胀：首轮 {prompt_series[0]} → 末轮 {prompt_series[-1]}"
                f"（增长 +{growth}，{growth / max(prompt_series[0], 1) * 100:.0f}%）"
            )

    msg = "\n".join(lines)
    if to_string:
        return msg
    print(msg)
    return msg
