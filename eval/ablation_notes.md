# 消融草稿（真实轨迹版）

## 实验设计

- **变量**：system prompt variant（`default` / `minimal`）
- **固定项**：任务集、模型/后端、工具集（默认只读 `read/grep/glob`）、安全策略、`max_turns`、`max_steps`、repeat
- **数据来源**：`eval.ablation` 调用真实 `AgentLoop` 生成 `records.jsonl`，再用程序化指标和可选 LLM-as-judge 汇总

## 运行方式

```bash
conda activate research
set -a && source .env && set +a
python -m eval.ablation --backend real --repeat 3 --tasks read-config,domain-scan-todos --judge
```

输出会写入：

- `eval/runs/<timestamp>-ablation/default-system/records.jsonl`
- `eval/runs/<timestamp>-ablation/minimal-system/records.jsonl`
- 可选 `judgments.jsonl`
- `comparison.json`

## 报告项

每组至少报告：

- 程序化成功率
- judge 通过率 / 平均分（若启用 judge）
- 混合成功率（程序化通过 + judge 通过 + 无安全违规）
- 平均步数、平均 token、估算成本
- 工具成功率、权限拦截率、禁用工具触发率

## 归因方式

只有当两组任务、模型、工具、安全策略和预算固定，且只改变 system prompt 时，才可以把差异初步归因到 prompt。若样本量很小，只能说“趋势/管线验证”，不能声称稳健能力结论。

## 局限

- LLM-as-judge 有偏差和方差，需要人工抽查校准。
- 真实模型输出有随机性，应多次运行取均值与方差。
- 默认 runner 只启用只读工具，结论只覆盖只读评估任务。
- FakeBackend 只用于 smoke test，不代表真实 agent 能力。
