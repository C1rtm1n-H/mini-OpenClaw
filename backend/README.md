# backend 模块

`backend/` 把不同模型服务统一成主循环使用的接口：

```python
chat(messages, tools) -> {
    "role": "assistant",
    "content": str,
    "tool_calls": list,
    "usage": dict,  # 后端提供时
}
```

## 组成

- `client.py`：DeepSeek/OpenAI 兼容的同步 HTTP 客户端。
- `fake_backend.py`：无密钥时使用的规则后端，仅用于离线打通管道。
- `multimodal.py`：读取和压缩图片，构造图文用户消息。
- `server.py`：课程阶段保留的后端服务入口。

## 环境变量

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 文本后端密钥；必需 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认 `deepseek-chat` |
| `VISION_API_KEY` | 图像后端密钥 |
| `VISION_BASE_URL` | 图像兼容接口地址 |
| `VISION_MODEL` | 支持视觉输入的模型名 |

`DEEPSEEK_BASE_URL` 可以是站点根地址或以 `/v1` 结尾的地址，客户端会规范化为
`/chat/completions`。HTTP 错误会保留服务端 JSON 正文，便于定位模型、tool schema、
配额或消息格式问题。

## 消息兼容

客户端负责：

- 把内部 tool call 转为 OpenAI `function.arguments` JSON 字符串。
- 保留每条 tool result 的 `tool_call_id`。
- 把 OpenAI tool calls 归一化为内部 `{id, name, arguments}`。
- 把内部 base64 图像块转为 `image_url` data URL。

FakeBackend 不具备通用推理能力，只匹配少量固定模式。不能用其结果评价随机任务质量。
当前后端连接失败不会自动重试或切换 FakeBackend，现场演示前应先检查网络和模型配置。
