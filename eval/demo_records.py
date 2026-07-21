"""仅用于离线演示指标管线的固定记录。

这些记录不是 Agent 实际运行结果，正式评估不得导入本模块；应使用
``eval.runner`` 生成的 ``records.jsonl``。
"""
from __future__ import annotations

from typing import Any


DEMO_RECORDS: list[dict[str, Any]] = [
    {
        "task": "audit-bad-experiment",
        "steps": [{
            "tool_calls": [
                {"name": "glob", "arguments": {"pattern": "*.py", "path": "eval_sample/bad_experiment"}},
                {"name": "grep", "arguments": {"pattern": "seed|/home/|cuda:0", "path": "eval_sample/bad_experiment"}},
                {"name": "read", "arguments": {"path": "eval_sample/bad_experiment/train.py"}},
            ],
            "tool_results": [
                {"name": "glob", "observation": "train.py\nevaluate.py\nconfig.yaml", "ok": True},
                {"name": "grep", "observation": "train.py:85:  # no random seed set", "ok": True},
                {"name": "read", "observation": "DEVICE = 'cuda:0'\nDATA_DIR = '/home/user/data/'", "ok": True},
            ],
            "raw": '<tool_call>{"name":"glob","arguments":{"pattern":"*.py","path":"eval_sample/bad_experiment"}}</tool_call>',
            "prompt_tokens": 310,
            "completion_tokens": 22,
        }],
        "final": (
            "发现3个缺陷：1) train.py:85 未设置随机种子 "
            "2) train.py:32 硬编码cuda:0 3) requirements.txt缺少scikit-learn。"
            "建议添加torch.manual_seed(42)，将硬编码路径改为命令行参数。"
        ),
    },
    {
        "task": "audit-bad-experiment",
        "steps": [
            {
                "tool_calls": [],
                "raw": '<tool_call>{"name":"glob","arguments":{"pattern":',
                "prompt_tokens": 305,
                "completion_tokens": 12,
            },
            {
                "tool_calls": [],
                "raw": "未发现明显的可复现性问题。",
                "prompt_tokens": 340,
                "completion_tokens": 15,
            },
        ],
        "final": "代码看起来没有明显的可复现性问题。",
    },
]

