# eval 模块

`eval/` 提供任务判据、轨迹指标、Judge、消融和 trace 示例，用于把“看起来能用”变成
可重复检查的数据。

## 文件职责

| 文件 | 作用 |
|---|---|
| `tasks.py` | Task 定义和程序化成功判据 |
| `metrics.py` | 成功率、步数、token、tool-call JSON 合法率 |
| `judge.py` | 开放式输出的 LLM-as-Judge 示例 |
| `ablation.py` | 有/无 system prompt 的最小消融 |
| `ablation_notes.md` | 实验设计、结果、限制与改进计划 |
| `trace_sample.jsonl` | 示例轨迹 |
| `tracer.py` | 早期评测 trace 示例；生产 trace 位于 `agent/tracer.py` |

## 运行

```powershell
python -m eval.metrics
python -m eval.ablation
python -m eval.judge
```

当前指标样本包含成功和失败轨迹，可验证评测代码是否正常。现有消融每组仅 2 条人工
样本，结果不能视为真实模型的统计证据。正式报告应改为：

- 固定任务集、模型、温度、工具和最大轮次。
- 每组至少 10 条真实 Agent 轨迹，最好多次运行。
- 只改变一个变量，例如 Todo、compaction、记忆或错误恢复。
- 报告成功率、平均步数、token/成本、均值与方差。
- 保存原始 trace，并解释失败类型而不是只给总分。
