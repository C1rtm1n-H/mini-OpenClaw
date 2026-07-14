# prompt 模块

`prompt/render.py` 是早期文本工具调用协议的兼容层：把结构化 messages 和工具 schema
渲染成单段文本，并解析模型输出中的 `<tool_call>...</tool_call>` JSON。

当前生产路径主要使用 OpenAI 兼容后端的原生 `tools` 字段和结构化 tool calls；完整
系统行为规范位于 `agent/prompts.py`。

保留该模块的价值：

- 支持不具备原生 function calling 的文本模型。
- 可用于课程对照实验和 tool-call JSON 合法率评测。
- 便于解释角色消息、工具 schema 和 observation 如何进入提示词。

如果修改工具调用格式，应同步检查：

- 多个 tool call 的解析。
- 无效或截断 JSON 的错误处理。
- 外部内容不能伪造新的系统指令。
- 生产 OpenAI tool-call 路径与文本兼容路径不要混用。
