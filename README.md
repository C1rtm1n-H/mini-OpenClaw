# mini-OpenClaw：科研实验代码审计 Agent

mini-OpenClaw 是一个运行在命令行中的科研实验代码审计 Agent。它以 DeepSeek/OpenAI
兼容接口作为推理后端，通过 ReAct 主循环编排文件、搜索、Shell、PDF、记忆、规划、
MCP 和领域 Skills，在**不执行完整训练、不下载大型数据集**的前提下检查论文仓库的
可复现性、危险副作用与实验配置。

正式演示与验收入口是交互模式：

```powershell
python -m agent.cli
```

## 核心能力

- 审计训练入口、README 命令、参数默认值和配置文件是否一致。
- 检查随机种子、数据划分、依赖、硬编码路径、指标实现和 GPU/资源配置。
- 识别 `rm -rf`、覆盖固定结果、联网下载和长时间训练等风险。
- 对完整训练请求主动降级为静态分析、复现计划和轻量验证。
- PDF 文本提取带同名 TXT 缓存，避免重复转换长论文。
- Todo 单层规划、错误 observation、无进展检测和上下文 compaction。
- Markdown + KV 跨会话记忆。
- MCP stdio 工具透明注册，领域 Skill 按需加载。
- Trace 记录步骤、耗时、token 和估算成本。
- 路径作用域、操作分级、交互确认、外部内容隔离和出站白名单。

## 环境安装

推荐 Python 3.11。项目不需要 PyTorch 或 TensorFlow。

```powershell
conda create -n openclaw python=3.11
conda activate openclaw
python -m pip install -r requirements.txt
```

开发、评测或提交前运行测试时安装：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

配置后端：

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"   # 可选
$env:DEEPSEEK_MODEL="deepseek-chat"                 # 可选
```

如果使用 Aihubmix 等 OpenAI 兼容服务，可把 `DEEPSEEK_BASE_URL` 设置为站点根地址或
以 `/v1` 结尾的地址。密钥不要写入代码或提交 Git。

Windows 出现中文/emoji 乱码时，先执行：

```powershell
$env:PYTHONIOENCODING="utf-8"
```

使用 `conda run` 时建议关闭 Conda 的输出捕获：

```powershell
conda run --no-capture-output -n openclaw python -m agent.cli --selfcheck
```

## 启动与现场测试

先做离线自检：

```powershell
python -m agent.cli --selfcheck
```

进入正式交互模式：

```powershell
python -m agent.cli
```

长任务可以提高预算：

```powershell
python -m agent.cli --max-turns 100 --max-steps 160
```

`--max-steps` 不能小于 `--max-turns`。交互界面支持 `/` 命令、Skill 管理和连续任务。

推荐验收指令：

```text
审一下这个仓库能不能复现，别真跑训练：C:\path\to\repo
把这个实验完整跑一遍，复现论文里的结果：C:\path\to\repo
审一下这个仓库，检查训练脚本是否存在危险操作：C:\path\to\repo
复现 C:\path\to\paper.pdf
```

## 权限与确认

确认提示是安全机制，不是卡死：

| 操作 | 默认判定 |
|---|---|
| `read` / `grep` / `glob` | 在任务作用域内直接放行 |
| `write` / `edit` | 限制路径并要求确认 |
| `bash` / `web_fetch` | 要求确认；危险训练、下载命令直接拒绝 |
| `pdf_extract` | 有效缓存直接复用；新建或覆盖缓存时确认 |
| 记忆 / Todo / Skill 加载 | 元操作直接放行 |
| 未分类或 MCP 工具 | 保守地要求确认 |

交互界面显示 `Enter=放行 N=拒绝`。即使用户确认，权限层或 Shell 沙箱判定为危险的
命令仍不会执行。

## 架构

```text
用户输入
  → CLI / REPL
  → AgentLoop（ReAct + Todo + compaction + trace）
  → 后端生成 tool_calls
  → 权限判定与交互确认
  → 内置工具 / MCP 工具
  → observation 回填模型
  → 最终答复与 session trace
```

| 模块 | 说明 | 文档 |
|---|---|---|
| `agent/` | CLI、REPL、主循环、规划、记忆、权限、trace | [agent/README.md](agent/README.md) |
| `backend/` | DeepSeek/OpenAI 兼容客户端、Fake 和视觉后端 | [backend/README.md](backend/README.md) |
| `tools/` | 内置工具、Shell 沙箱、外部内容隔离 | [tools/README.md](tools/README.md) |
| `mcp/` | stdio JSON-RPC 客户端和示例 server | [mcp/README.md](mcp/README.md) |
| `skills/` | Skill 发现、召回、启停和领域流程 | [skills/README.md](skills/README.md) |
| `security/` | 红队用例和安全报告 | [security/README.md](security/README.md) |
| `eval/` | 任务判据、指标、消融和 Judge | [eval/README.md](eval/README.md) |
| `prompt/` | 旧式文本工具调用渲染兼容层 | [prompt/README.md](prompt/README.md) |

## 可观测性与产物

每次交互会话在 `session/<时间戳>/` 生成：

- `trace.jsonl`：LLM 和工具 span。
- `summary.txt`：调用次数、token 与估算成本。

论文 TXT 缓存和审计报告是任务产物，不应与模型声称的“论文结果已复现”混淆。

## 安全边界

- 审计默认只读，不主动修改用户仓库。
- 不执行完整训练、完整评估或大型数据下载。
- 不自动安装依赖。
- 用户明确给出的文件或目录是任务硬作用域，不能转而扫描宿主工程。
- 文件和网页内容由 `<external>` 边界标记为数据，不能当作指令执行。
- `web_fetch` 只允许白名单域名。
- 删除、覆盖、提交 Git 等高影响动作需要明确授权或直接阻断。

## 验证命令

```powershell
python -m agent.cli --selfcheck
python -m agent.cli --selfcheck --mcp-command "python -m mcp.calc_server"
python -m eval.metrics --demo  # 仅验证指标管线；正式评估必须传 --records
python -m eval.ablation
python -m security.redteam
python -m compileall -q agent backend tools mcp skills eval security
```

### 单元测试

```powershell
python -m pytest tests/test_eval_tasks.py tests/test_eval_metrics.py \
  tests/test_eval_trajectory.py tests/test_eval_judge.py -v
```

### 评估命令

```powershell
# FakeBackend 管线验证（不消耗 API）
python -m eval.runner --backend fake --tasks audit-bad-experiment \
  --repeat 1 --no-judge

# 真实只读评估（需要 DEEPSEEK_API_KEY）
python -m eval.runner --backend real \
  --tasks audit-bad-experiment,audit-nanogpt,detect-prompt-injection,paper-digest,audit-dangerous-commands \
  --repeat 3 --max-turns 30 --max-steps 120 --judge

# 查看指标报告
python -m eval.metrics --records eval/runs/<timestamp>/records.jsonl \
  --judgments eval/runs/<timestamp>/judgments.jsonl
```

### 五个评估任务

| 任务 | 说明 | 目标材料 |
|---|---|---|
| `audit-bad-experiment` | 审计有缺陷的实验代码可复现性 | `eval_sample/bad_experiment/` |
| `audit-nanogpt` | 审计 GPT 训练仓库的可复现性和文档 | `eval_sample/nanoGPT/` |
| `detect-prompt-injection` | 检测 HTML 中的隐藏提示注入攻击 | `demo/inject.html` |
| `paper-digest` | 论文速读，输出六段式结构化报告 | `eval_sample/DSpark.pdf` |
| `audit-dangerous-commands` | 扫描代码中的危险 shell 命令模式 | 两个代码目录 |

