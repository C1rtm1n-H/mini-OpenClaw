# MCP 模块

`mcp/` 实现最小 stdio MCP 客户端，使外部 server 的工具可以透明加入同一个
`ToolRegistry`。

## 协议流程

1. `subprocess.Popen` 启动 server。
2. JSON-RPC `initialize` 握手。
3. 发送 `notifications/initialized`。
4. `tools/list` 获取工具 schema。
5. `register_mcp_tools()` 以 `mcp__<name>` 注册。
6. 模型调用时通过 `tools/call` 转发参数并返回文本 observation。

客户端使用后台线程读取 stdout，并为 RPC 设置超时；关闭会话时终止子进程。

## 内置示例

- `echo_server.py`：暴露 `echo(text)`，CLI 默认接入，用于验证 MCP 全链路。
- `calc_server.py`：暴露 `add(a, b)`。

测试：

```powershell
python -m agent.cli --selfcheck --mcp-command "python -m mcp.calc_server"
```

启动 Agent 时也可以追加 server：

```powershell
python -m agent.cli --mcp-command "python -m mcp.calc_server"
```

MCP 工具当前未列入内置权限分类，因此采用保守默认策略：交互模式会要求用户确认。
server 必须保持 stdout 为逐行 JSON-RPC；日志应写 stderr，避免破坏协议。
