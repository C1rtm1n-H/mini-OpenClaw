# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

mini-OpenClaw is a Claude Code-style command-line Agent built over a 10-day course. It implements a **ReAct main loop** that calls a **DeepSeek API backend**, which outputs **tool calls** (read/write/bash/edit/grep/glob). The loop executes those tools, feeds results back to the model, and repeats until the task is done. MCP (pluggable external tools), Skills (domain knowledge packs), and a safety layer are added in later days.

## Commands

```bash
# Self-check the skeleton (Day1+)
python -m agent.cli --selfcheck

# Run a task (Day5+)
python -m agent.cli "your task description here"

# Find all unimplemented TODO markers
grep -rn "TODO\[Day" .
```

No build step, no test runner — this is a course project where each module is implemented incrementally.

## Architecture

```
User request → [agent/cli.py] → [agent/loop.py: ReAct loop] → [backend/client.py: DeepSeek API]
                    ↑                    │   model outputs <tool_call>
                    │                    ▼
                    └──── tool result ── [ToolRegistry dispatch]
                                             ├── tools/fs.py (read, write)
                                             ├── tools/shell.py (bash)
                                             ├── tools/more_tools.py (edit, grep, glob, web_fetch, task_list)
                                             ├── MCP tools via mcp/client.py
                                             └── Skills via skills/loader.py
```

### Key modules (ordered by course progression)

| Module | Role | When |
|--------|------|------|
| `backend/client.py` | DeepSeek API client (OpenAI-compatible). `chat(messages, tools)` → normalized assistant message with `content` and `tool_calls`. Reads `DEEPSEEK_API_KEY` from env. | Day1–2 |
| `backend/fake_backend.py` | Rule-driven fallback backend for offline pipeline testing. Same `chat()` interface as the real client. Used automatically when no API key is set. | Day1 |
| `prompt/render.py` | Renders structured messages + tools into a single text string the model consumes. Implements manual `<tool_call>` parsing without relying on API function-calling. | Day3 |
| `tools/base.py` | `Tool` dataclass (name, description, JSON Schema parameters, run callable) and `ToolRegistry` (register/get/schemas). `build_default_registry()` assembles all built-in tools — tools are uncommented here as they're implemented. | Day5–7 |
| `agent/loop.py` | `AgentLoop` class: ReAct loop with max_turns guard. Iterates: call backend → if tool_calls, execute each via registry and inject observation → if no tool_calls, return final content. | Day5 |
| `agent/context.py` | Token budget estimation, compaction (summarize old turns, keep recent K), and observation truncation. | Day7 |
| `agent/prompts.py` | `SYSTEM_PROMPT` string — the system prompt sent on every conversation. | Day2/5 |
| `agent/cli.py` | Entry point: `--selfcheck` or a natural-language task. Builds registry, picks backend (DeepSeek if key is set, else FakeBackend), creates AgentLoop, runs. | Day1+ |
| `mcp/client.py` | Minimal MCP client over stdio + JSON-RPC. Starts a server subprocess, does initialize handshake, calls `tools/list` and `tools/call`, wraps results as `Tool` objects registered into the ToolRegistry. | Day8 |
| `mcp/echo_server.py` | A minimal MCP server for testing the client: exposes one `echo` tool, communicates via stdin/stdout JSON-RPC. | Day8 |
| `skills/loader.py` | Scans `skills/*/SKILL.md` directories, parses YAML frontmatter for name/description/body, renders a catalog string for the model's context. | Day9 |
| `eval/tasks.py` | Tool-call test cases and end-to-end task definitions for evaluation. | Day7/10 |
| `eval/metrics.py` | Three metrics: JSON validity rate, tool choice accuracy, argument accuracy. | Day7 |

## Key design decisions

- **Tool schema format**: OpenAI function-calling format (`{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}`). The `Tool.schema()` method produces this directly.
- **Backend normalization**: `DeepSeekBackend._normalize()` converts OpenAI's response into a flat internal format: `{"role": "assistant", "content": ..., "tool_calls": [{"id", "name", "arguments": dict}]}`. Arguments are JSON-parsed (not strings). The loop and FakeBackend both use this normalized format.
- **MCP namespace prefix**: MCP tools are registered as `mcp__<name>` to avoid collisions with built-in tools.
- **API key handling**: If `DEEPSEEK_API_KEY` is missing, `cli.py` catches the exception and falls back to `FakeBackend` automatically — no explicit config check needed.

## Conventions

- Implementation markers: `# TODO[DayN]` comments denote unimplemented work, organized by course day. Run `grep -rn "TODO\[Day" .` to find all.
- Git tags mark milestones: `v1` (Day6, end-to-end), `v3` (Day9, extensible), `final` (Day10, with safety layer).
- Each module should have its own `README.md` documenting design decisions (for grading).
- The course uses `conda` environments; `requirements.txt` is intentionally minimal (no torch/vllm — the model runs via API, not locally).
