# agent 模块

`agent/` 是系统控制层，负责把用户输入、模型决策、工具执行、安全判定、规划状态和
trace 串成完整会话。

## 文件职责

| 文件 | 职责 |
|---|---|
| `cli.py` | 参数解析、组件组装、MCP 启动、session 创建与清理 |
| `repl.py` | 正式交互界面、工具过程展示、Enter/N 权限确认、Skill 管理 |
| `loop.py` | ReAct 主循环、tool result 回填、终止、反思与错误 observation |
| `context.py` | token 估算、compaction、tool-call 事务保护、结果截断 |
| `planning.py` | Todo 状态机、重试、反思次数、无进展与循环检测 |
| `memory.py` | `MEMORY.md` 追加记忆和 `memory.json` KV 记忆 |
| `permissions.py` | 只读/写/执行/元操作分级、路径作用域、训练下载拦截 |
| `prompts.py` | 科研审计角色、工具说明、任务边界和报告要求 |
| `tracer.py` | span、JSONL、回放、token 与成本摘要 |

## 主循环

每次 `send()` 都视为一个新执行任务：清理旧 Todo 和卡死计数，检测用户明确提供的
Windows 路径作为硬作用域，再循环执行：

1. 注入 Todo、作用域与强制降级策略。
2. 必要时压缩上下文。
3. 调用后端获得 assistant 消息和 `tool_calls`。
4. 对每个工具调用进行权限判定和用户确认。
5. 执行工具，将带 `tool_call_id` 的 `role=tool` observation 回填。
6. 模型不再调用工具时返回最终答复。

默认 `max_turns=60`、`max_steps=100`。Todo 全部完成不会直接截断循环，模型仍会看到
最后一个工具结果并生成面向用户的总结。

## 规划约束

- 每个用户任务最多建立一次单层主清单。
- 已有主清单后，禁止为子任务创建嵌套小清单。
- 子任务使用 pending / in_progress / completed / blocked 状态。
- 同一动作重复和连续无进展会触发反思提示。
- 每项反思次数有限，防止反思套娃。

## 上下文与记忆

compaction 会保留 system prompt 和最近消息，并确保 assistant 的 tool call 与对应 tool
result 不被拆开。工具 observation 默认最多注入 4000 字符。

启动时 `recall_all()` 合并 `MEMORY.md` 和 `memory.json` 注入 system prompt，因此新会话
仍能读取项目约定。不要把密钥或隐私数据写进记忆文件。

## 错误恢复

- 普通工具异常会转换为 observation 交给模型调整方案。
- `TransientError` 最多指数退避重试 3 次。
- `PermanentError` 不重试。
- 后端连接异常目前返回错误并结束本次任务，不会自动切换后端。

## Trace

LLM 与工具执行都记录为 span：`step/kind/name/ok/ms/out`，后端提供 usage 时还记录
prompt、completion 和 total token。退出会话时生成 `trace.jsonl` 与 `summary.txt`。
