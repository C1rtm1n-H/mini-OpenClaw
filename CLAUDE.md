# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

mini-OpenClaw is a CLI agent (like Claude Code) built as a 10-day student project. A **ReAct loop** calls a **DeepSeek API** backend; the model outputs tool calls (read/write/bash/edit/grep/…); the loop executes them and feeds results back until the task completes. MCP and Skills layers add pluggable external tools and domain-specific capabilities.

## Commands

```bash
# Self-check: verifies tool registry, FakeBackend, and agent loop can import
python -m agent.cli --selfcheck

# Run a task (requires DEEPSEEK_API_KEY; falls back to FakeBackend otherwise)
python -m agent.cli "create hello.py and run it"

# Run the echo MCP server (Day8 — for testing MCP client against)
python -m mcp.echo_server
```

**Environment variables:**
- `DEEPSEEK_API_KEY` — required for real model; never commit this
- `DEEPSEEK_BASE_URL` — defaults to `https://api.deepseek.com`
- `DEEPSEEK_MODEL` — defaults to `deepseek-chat`

## Architecture

```
user request → [agent/loop.py  (ReAct loop)] → [backend/ (DeepSeek API)]
                    ▲   │  model outputs tool_calls
                    │   ▼
              tool result ← [tools/  (registry of Tool objects)]
                              ├── built-in: read, write, bash, edit, grep, glob, web_fetch, task_list
                              ├── MCP: external servers via mcp/client.py (stdio + JSON-RPC)
                              └── Skills: domain knowledge via skills/loader.py (SKILL.md files)
```

### Key modules

| Module | Purpose |
|--------|---------|
| `agent/loop.py` | ReAct loop: while no final answer → call backend → execute tool_calls → inject observations → repeat. Hard cap at `max_turns` (default 20). |
| `agent/cli.py` | CLI entry point. `--selfcheck` runs skeleton validation; otherwise instantiates `AgentLoop` with the task. |
| `agent/prompts.py` | `SYSTEM_PROMPT` — the agent's persona and behavior rules. Quality here directly impacts task success rate. |
| `agent/context.py` | Token budget estimation, compaction (summarize old turns, keep recent K), observation truncation. |
| `backend/client.py` | `DeepSeekBackend` — OpenAI-compatible client. Normalizes internal message format ↔ OpenAI format. The `chat(messages, tools)` contract is shared with `FakeBackend`. |
| `backend/fake_backend.py` | `FakeBackend` — rule-based mock for offline pipeline testing. Auto-selected when no API key is set. |
| `tools/base.py` | `Tool` dataclass (name, description, JSON Schema parameters, `run()` callable) and `ToolRegistry`. `build_default_registry()` assembles built-in tools. |
| `tools/fs.py` | `read` and `write` tools. |
| `tools/shell.py` | `bash` tool — subprocess execution with timeout. |
| `tools/more_tools.py` | `edit` (search-replace), `grep` (ripgrep-based), `glob` (path glob), `web_fetch` (URL→markdown), `task_list` (structured todo). |
| `mcp/client.py` | Minimal MCP client: spawns server subprocess, JSON-RPC over stdio, `tools/list` + `tools/call`. `register_mcp_tools()` wraps MCP tools into the registry with `mcp__` prefix. |
| `mcp/echo_server.py` | Toy MCP server exposing a single `echo` tool — used to validate the client handshake before connecting real servers. |
| `prompt/render.py` | Converts structured `messages + tools` into a single text string for the model, using role tokens. Also `parse_tool_calls()` to extract `<tool_call>...</tool_call>` from raw model output. |
| `skills/loader.py` | Scans `skills/*/SKILL.md`, parses YAML frontmatter (name + description + body). Skills are injected into the system prompt as capability descriptions; the model decides when to invoke them. |
| `eval/` | Tool-call test set + end-to-end task set + three metrics (JSON validity, tool choice accuracy, arg accuracy). |

### Data flow

1. User task → `AgentLoop.run()` builds initial `messages = [system, user]`
2. Loop: `backend.chat(messages, tools=registry.schemas())` → assistant message with optional `tool_calls`
3. For each `tool_call`: resolve tool from registry → `tool.run(**arguments)` → append `{role: "tool", content: observation}` to messages
4. If no tool calls, return assistant content as final answer
5. Context compaction (Day7) triggers when estimated tokens exceed budget

### Progressive TODO markers

All implementation points are tagged `# TODO[DayN]` throughout the codebase. Find them all with:
```bash
grep -rn "TODO\[Day" .
```

The course schedule: Day1–2 (backend + first tools), Day3 (prompt rendering), Day5 (ReAct loop + read/write/bash), Day6 (edit/grep/glob → v1 milestone), Day7 (web_fetch/task_list + context compaction + eval), Day8 (MCP), Day9 (Skills), Day10 (security sandbox + final demo).
