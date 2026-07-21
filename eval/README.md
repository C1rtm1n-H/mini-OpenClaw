# eval 模块

`eval/` 提供任务判据、真实轨迹记录、LLM-as-judge、指标汇总和消融，用于把“看起来能用”变成可重复检查的数据。

## 文件职责

| 文件 | 作用 |
|---|---|
| `tasks.py` | Task 定义、只读默认任务集、可解释程序化判据 |
| `trajectory.py` | 将 `AgentLoop` 事件聚合为 canonical eval record，并读写 JSONL |
| `runner.py` | 运行真实 `AgentLoop`，保存 `records.jsonl` / `judgments.jsonl` / `summary.json` |
| `metrics.py` | 成功率、步数、token、tool-call JSON 合法率、judge/tool/safety 聚合指标 |
| `judge.py` | 基于最终答案 + 轨迹证据的 LLM-as-judge |
| `ablation.py` | 基于真实轨迹的 system prompt 消融 |
| `tracer.py` | 回放 runner 生成的 `records.jsonl`，展示工具 observation 与返回码 |

## 运行

首次运行评测测试时安装开发依赖：

```bash
python -m pip install -r requirements-dev.txt
```

使用项目环境与 `.env`：

```bash
conda activate openclaw
set -a && source .env && set +a
```

离线管线 smoke test（FakeBackend 只验证 harness，不代表真实能力）：

```bash
python -m eval.runner --backend fake --tasks audit-bad-experiment --repeat 1 --no-judge
python -m eval.metrics --records eval/runs/<run>/records.jsonl
python -m eval.tracer eval/runs/<run>/records.jsonl --index 0
```

如只需演示指标聚合代码，必须显式运行 `python -m eval.metrics --demo`。固定 demo
记录位于 `eval/demo_records.py`，不属于 Agent 运行结果，也不得用于正式成绩。

真实只读评估（需要 `DEEPSEEK_API_KEY`）：

```bash
python -m eval.runner --backend real \
  --tasks audit-bad-experiment,audit-nanogpt,detect-prompt-injection,paper-digest,audit-dangerous-commands \
  --repeat 3 --max-turns 30 --max-steps 120 --judge
```

真实消融：

```bash
python -m eval.ablation --backend real --repeat 3 \
  --tasks audit-bad-experiment,detect-prompt-injection --judge
```

## 任务列表

| 任务 | 目标 | 必用工具 |
|---|---|---|
| `audit-bad-experiment` | `eval_sample/bad_experiment/` 实验代码可复现性审计 | glob, grep, read |
| `audit-nanogpt` | `eval_sample/nanoGPT/` GPT 训练仓库审计 | glob, grep, read |
| `detect-prompt-injection` | `demo/inject.html` 提示注入检测 | read |
| `paper-digest` | `eval_sample/DSpark.pdf` 论文速读 | pdf_extract |
| `audit-dangerous-commands` | bad_experiment + nanoGPT 危险命令扫描 | grep |

## 设计原则

- 先记录，后评估：`runner.py` 先保存真实 `records.jsonl`，`metrics.py` 和 `judge.py` 再消费这些记录。
- 默认只读：默认任务集禁止 `write`/`edit`；`bash` 仅用于毫秒级诊断（`--help`、import 检查），危险命令由权限层拦截。
- judge 看证据：LLM-as-judge 同时看任务、rubric、最终答案和轨迹摘要；没有读取/扫描/执行证据就应扣分。
- 程序化判据也核验证据：审计报告中的文件引用必须能回溯到成功的工具 observation；带行号的引用必须与 observation 中的文件和行号一致。
- 报告多维指标：程序化成功率、judge 通过率、混合成功率、步数、token、工具成功率、权限拦截率和安全违规，而不是只给一个总分。
- 判据要求实质性报告：所有任务的 `check` 函数通过 `len(final) ≥ 200-300` 且不含 todo 标记来拒绝空壳报告。

正式报告建议每组多次运行（`--repeat 3`），固定任务集、模型、温度、工具和最大轮次，只改变一个变量，并保存原始 records/judgments 供人工抽查。
