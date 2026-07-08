"""Day 3 · 成功率与效率指标（讲义 §8：报告一组指标，而非一个数字）。

四项指标：
  - success_rate：对不对（复用 tasks.py 的 check 函数）
  - step_count / token_count：贵不贵（效率维度）
  - json_valid_rate：工具调用格式稳不稳

为在没有真 agent 的情况下就能跑，内置一批样本轨迹记录。
D4 起把真 agent 的轨迹换进来即可，指标函数一行不用改。
"""
from __future__ import annotations
import json
import re
from typing import Any

# 匹配完整 <tool_call>{...}</tool_call>
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
# 检测是否有 <tool_call> 开头（包括因截断缺少 </tool_call> 的情况）
HAS_TOOL_CALL_RE = re.compile(r"<tool_call>", re.DOTALL)
# 从 <tool_call> 后尽量提取一段 JSON 候选串（到 </tool_call> 或行末）
FALLBACK_JSON_RE = re.compile(r"<tool_call>\s*(\{.*)", re.DOTALL)

# ---- 样本轨迹记录 ----
# 一条记录 = 一次任务运行留下的轨迹。steps 里每步含：
#   tool_calls: 模型这步请求的工具调用（结构化列表）
#   raw: 原始文本（含 <tool_call> 标记）
#   prompt_tokens / completion_tokens: 该步的 token 计数
SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "task": "read-config",
        "steps": [
            {"tool_calls": [{"name": "read", "arguments": {"path": "config.json"}}],
             "raw": '<tool_call>{"name":"read","arguments":{"path":"config.json"}}</tool_call>',
             "prompt_tokens": 310, "completion_tokens": 22},
        ],
        "final": "config.json 里 timeout = 30 秒。",
    },
    {
        "task": "list-dir",
        "steps": [
            {"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}],
             "raw": '<tool_call>{"name":"bash","arguments":{"command":"ls"}}</tool_call>',
             "prompt_tokens": 290, "completion_tokens": 18},
        ],
        "final": "当前目录有：main.py config.json README.md",
    },
    {
        "task": "read-config",          # 一条"失败/低质量"样本：JSON 被截断，且没报出值
        "steps": [
            {"tool_calls": [],
             "raw": '<tool_call>{"name":"read","arguments":{"path":',   # 坏 JSON
             "prompt_tokens": 305, "completion_tokens": 12},
            {"tool_calls": [], "raw": "我不确定 timeout 的值。",
             "prompt_tokens": 340, "completion_tokens": 15},
        ],
        "final": "我不确定 timeout 的值。",
    },
    {
        "task": "domain-scan-todos",
        "steps": [
            {"tool_calls": [{"name": "grep", "arguments": {"pattern": "TODO", "path": "."}}],
             "raw": '<tool_call>{"name":"grep","arguments":{"pattern":"TODO","path":"."}}</tool_call>',
             "prompt_tokens": 350, "completion_tokens": 25},
        ],
        "final": "扫描结果：\n- TODO[Day3] 完善任务判据\n- TODO[Day4] 实现主循环\n- TODO[Day5] 上下文压缩",
    },
    {
        "task": "run-bash-script",
        "steps": [
            {"tool_calls": [{"name": "bash", "arguments": {"command": "bash scripts/setup.sh"}}],
             "raw": '<tool_call>{"name":"bash","arguments":{"command":"bash scripts/setup.sh"}}</tool_call>',
             "prompt_tokens": 320, "completion_tokens": 21},
        ],
        "final": "已运行 scripts/setup.sh，脚本执行完毕，依赖安装成功。",
    },
]


# ---- 指标函数 ----

def success_rate(tasks: list, records: list[dict]) -> float:
    """对每条 (task, trajectory) 记录跑 task.check，返回成功比例。"""
    by_name = {t.name: t for t in tasks}
    ok = 0
    for r in records:
        task = by_name.get(r["task"])
        if task and task.check(r):      # 复用步骤 1 的成功判据
            ok += 1
    return ok / max(len(records), 1)


def step_count(record: dict) -> int:
    """单条轨迹的步数。"""
    return len(record["steps"])


def token_count(record: dict) -> int:
    """单条轨迹的总 token（prompt + completion）。"""
    return sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
               for s in record["steps"])


def json_valid_rate(records: list[dict]) -> float:
    """从每步的 raw 里提取 <tool_call> JSON 并校验合法性。

    只计入含 <tool_call> 标记的步（这步确实想调工具），纯文本步不参与计算。
    对于截断/缺标签等边缘情况也尽量提取 JSON 候选串尝试解析。
    """
    total, ok = 0, 0
    for r in records:
        for s in r["steps"]:
            raw = s.get("raw", "")
            # 这步是否出现了 <tool_call>（不管是否完整）
            if not HAS_TOOL_CALL_RE.search(raw):
                continue                # 纯文本步，无工具调用意图
            total += 1
            # 优先用完整匹配提取 JSON
            m = TOOL_CALL_RE.search(raw)
            if not m:
                # 回退：从 <tool_call> 后尽量截取（截断/缺闭合标签）
                m = FALLBACK_JSON_RE.search(raw)
            if not m:
                continue                # 无法提取任何 JSON 候选串
            candidate = m.group(1)
            # 尝试补全截断的 JSON：补上缺失的闭合括号
            if not candidate.endswith("}"):
                # 简单补全：先尝试补 }}
                candidate = _try_mend_json(candidate)
            try:
                json.loads(candidate)
                ok += 1
            except json.JSONDecodeError:
                pass                     # 坏 JSON：计入分母、不计入分子
    return ok / max(total, 1)


def _try_mend_json(s: str) -> str:
    """尝试修补截断的 JSON：统计未闭合的 { 和 [，补上对应闭合符。"""
    depth_brace = s.count("{") - s.count("}")
    depth_bracket = s.count("[") - s.count("]")
    # 去掉尾部逗号（JSON 不允许 trailing comma）
    s = s.rstrip(",\n\r ")
    s += "}" * max(depth_brace, 0)
    s += "]" * max(depth_bracket, 0)
    return s


# ---- 驱动（可直接 python -m eval.metrics 运行）----
if __name__ == "__main__":
    from eval.tasks import SAMPLE_TASKS

    recs = SAMPLE_RECORDS
    print("=== Day 3 指标报告（样本轨迹）===")
    print(f"成功率        : {success_rate(SAMPLE_TASKS, recs):.2f}")
    print(f"平均步数      : {sum(step_count(r) for r in recs) / len(recs):.1f}")
    print(f"平均 token    : {sum(token_count(r) for r in recs) / len(recs):.0f}")
    print(f"JSON 合法率   : {json_valid_rate(recs):.2f}")
    print()
    print('（讲义 §8：同时看"对不对"和"贵不贵"两类维度，别只报一个数字）')
