"""最小 MCP 客户端（Day6）。

MCP（Model Context Protocol）让工具集从"写死在代码里"变成"可插拔的外部 server"。
本文件实现一个最小客户端：通过 stdio 跟 server 通信，做 JSON-RPC。

要实现的握手与调用：
  1. 启动 server 子进程（stdio transport）
  2. initialize 握手
  3. tools/list  —— 拉取 server 暴露的工具
  4. tools/call  —— 把某次调用转发给 server，拿回结果
然后在 agent/loop 里，把这些 MCP 工具**透明合并**进内置 ToolRegistry。
"""
from __future__ import annotations
import json
import queue
import subprocess
import threading
from typing import Any

from tools.base import Tool, ToolRegistry


class MCPClient:
    def __init__(self, command: list[str], timeout: float = 10.0):
        self.command = command
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        """启动 stdio server 并完成 initialize 握手。"""
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"MCP server 启动失败：{self.command}: {e}") from e

        if self.proc.stdout is None or self.proc.stdin is None:
            raise RuntimeError("MCP server stdio 初始化失败")

        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mini-OpenClaw", "version": "0.1"},
        })
        self._notify("notifications/initialized")

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for line in self.proc.stdout:
                self._stdout_queue.put(line)
        finally:
            self._stdout_queue.put(None)

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        """发一条 JSON-RPC 请求（带自增 id），读回对应响应。"""
        self._id += 1
        rid = self._id
        req = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)

        while True:
            line = self._readline()
            try:
                resp = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MCP server 返回非 JSON：{line!r}") from e

            # 忽略通知或其它请求，只接受对应 id 的响应。
            if resp.get("id") != rid:
                continue
            if "error" in resp:
                err = resp["error"]
                raise RuntimeError(f"MCP RPC error {err.get('code')}: {err.get('message')}")
            return resp.get("result")

    def _notify(self, method: str, params: dict | None = None) -> None:
        """发送 JSON-RPC notification，不等待响应。"""
        req = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)

    def _send(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("MCP server 尚未启动")
        if self.proc.poll() is not None:
            raise RuntimeError(f"MCP server 已退出，returncode={self.proc.returncode}")
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"写入 MCP server 失败：{e}") from e

    def _readline(self) -> str:
        try:
            line = self._stdout_queue.get(timeout=self.timeout)
        except queue.Empty as e:
            self.close()
            raise RuntimeError(f"MCP server 响应超时（>{self.timeout}s）：{self.command}") from e
        if line is None or line == "":
            code = self.proc.poll() if self.proc is not None else None
            stderr = ""
            if self.proc is not None and self.proc.stderr is not None:
                try:
                    stderr = self.proc.stderr.read().strip()
                except Exception:
                    stderr = ""
            detail = f"，stderr: {stderr}" if stderr else ""
            raise RuntimeError(f"MCP server 已退出或关闭 stdout，returncode={code}{detail}")
        return line.strip()

    def list_tools(self) -> list[dict]:
        """调用 tools/list，返回工具描述列表。"""
        result = self._rpc("tools/list")
        tools = result.get("tools", []) if isinstance(result, dict) else []
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list 返回格式错误：tools 不是 list")
        return tools

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用 tools/call，返回结果文本。"""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        content = result.get("content", []) if isinstance(result, dict) else []
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(result)

        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)

    def close(self) -> None:
        """尽量清理 MCP server 子进程。"""
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def register_mcp_tools(registry: ToolRegistry, client: MCPClient) -> None:
    """把一个 MCP server 的工具包装成内置 Tool 并注册，实现透明合并。"""
    for spec in client.list_tools():
        name = spec["name"]
        registry.register(Tool(
            name=f"mcp__{name}",            # 命名空间避免和内置工具撞名
            description=spec.get("description", ""),
            parameters=spec.get("inputSchema", {"type": "object", "properties": {}}),
            run=lambda _n=name, **kw: client.call_tool(_n, kw),
        ))
