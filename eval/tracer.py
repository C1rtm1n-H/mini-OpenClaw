"""回放 ``eval.runner`` 生成的真实评测记录。

本模块不生成样例轨迹，也不接受手写的“成功”文本作为运行证据。记录的唯一来源是
runner 写出的 ``records.jsonl``，其中包含 AgentLoop 的模型调用、工具参数、完整
observation、返回码和最终回答。
"""
from __future__ import annotations

import argparse

from eval.trajectory import load_jsonl, record_to_judge_digest


def replay(records_path: str, index: int = 0) -> None:
    records = load_jsonl(records_path)
    if not records:
        raise ValueError(f"没有可回放的评测记录：{records_path}")
    if index < 0 or index >= len(records):
        raise IndexError(f"记录索引越界：{index}（共 {len(records)} 条）")
    print(record_to_judge_digest(records[index], observation_limit=4_000))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回放 eval.runner 的 records.jsonl")
    parser.add_argument("records", help="eval.runner 生成的 records.jsonl")
    parser.add_argument("--index", type=int, default=0, help="要回放的记录索引，默认 0")
    args = parser.parse_args(argv)
    replay(args.records, args.index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
