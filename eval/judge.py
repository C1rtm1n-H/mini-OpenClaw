"""LLM-as-judge：按固定 rubric 给一个答复打分（1-5）。

复用 D2 打通的 backend/client.py 的 chat()，让 deepseek-v4-flash 充当评审。
设计要点（讲义 §9.3）：
  - rubric 固定并公开：同一把尺子，任何人重跑结果可比。
  - 先理由后打分：强制模型先给理由再给分数，比直接吐数字更稳、可人工抽查。
  - judge 本身也有偏差（冗长偏差、一致性差、自我偏好/共享盲区），需抽样人工校准。
"""
from __future__ import annotations
import re
from backend.client import DeepSeekBackend   # 复用 D2 的 chat()

RUBRIC = (
    "你是严格的评审。请按 1-5 分给【回答】打分：\n"
    "  5=完全正确且直接命中问题；3=部分正确或答非所问；1=错误或跑题。\n"
    "只依据【问题】判断【回答】，忽略回答的长度与措辞华丽程度。\n"
    "务必先写一行【理由】，再单独一行写【分数: X】（X 为 1-5 整数）。"
)


def judge(question: str, answer: str) -> dict:
    """用 LLM 给一个答复打分，返回 {"score": int|None, "raw": str}。

    score 为 None 表示解析失败（模型没按约定格式输出）。
    """
    messages = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": f"【问题】{question}\n【回答】{answer}"},
    ]
    resp = DeepSeekBackend().chat(messages)      # deepseek-v4-flash，无 tools
    text = resp["content"]
    m = re.search(r"分数[:：]\s*([1-5])", text)   # 从"先理由后打分"里抠出分数
    score = int(m.group(1)) if m else None
    return {"score": score, "raw": text}


if __name__ == "__main__":
    q = "config.json 里 timeout 是多少？"

    samples = [
        ("正确答复", "timeout = 30 秒。"),
        ("含糊答复", "我不太确定，可能是某个数吧。"),
        # 冗长偏差测试：又长又客气但仍不给值
        ("冗长但无值", (
            "感谢您的提问！关于 config.json 中的 timeout 参数，这是一个非常重要的配置项。"
            "通常来说，timeout 的值会因为项目不同而有所差异。我建议您查阅相关文档，"
            "或者咨询团队中的资深成员，以确保获取最准确的信息。如果您有其他问题，"
            "我也很乐意为您继续解答。"
        )),
    ]

    print("=== LLM-as-judge 验证（deepseek-v4-flash）===\n")
    for label, ans in samples:
        r = judge(q, ans)
        print(f"[{label}]")
        print(f"  答复: {ans!r}")
        print(f"  分数: {r['score']}")
        print(f"  judge 理由首行: {r['raw'].splitlines()[0] if r['raw'].splitlines() else '(空)'}")
        print()

