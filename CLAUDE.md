# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A multi-agent demo using the Agent-to-Agent (A2A) protocol for application management. Two agents built on LangGraph communicate over HTTP — a Host Agent that serves the chat UI and a domain Application Agent that manages a registry of software applications.

## Prerequisites & Environment

- Python 3.13 (see `.python-version`)
- `uv` for package management (each subproject has its own `pyproject.toml`)
- `.env` in the project root with `GOOGLE_API_KEY="..."` — all agents load this via `python-dotenv`

## Running the System

Start the Application Agent first, then the Host Agent.

```bash
# Terminal 1 — Application Agent (LangGraph, port 10005)
cd application_agent && uv run --active app/__main__.py

# Terminal 2 — Host Agent (LangGraph web UI, port 10001)
cd host_agent_langgraph && uv run --active host/__main__.py
```

First run: `uv venv --python 3.13 && source .venv/bin/activate` inside each subproject directory before `uv run`.

## Architecture

```
Browser (http://localhost:10001)
      │
      ▼
Host Agent (LangGraph, port 10001)    ← orchestrator; user talks here
      │
      └──→ Application Agent (LangGraph, port 10005)
```

### How inter-agent communication works

At startup, `HostAgent._async_init_components()` fetches the Application Agent's **AgentCard** via `A2ACardResolver`. The card is stored in `self.remote_agent_connections` (keyed by agent name) and its name/description is injected into the host's system prompt so the LLM knows which agents exist.

When the host LLM calls `send_message(agent_name, task)`, `RemoteAgentConnections` wraps the request in a `SendMessageRequest` and posts it to the agent's A2A HTTP endpoint. Responses come back as `Task` objects; the host extracts artifact parts from `result.artifacts`.

### Agent structure

Both agents follow the same file pattern:

| File | Role |
|---|---|
| `agent.py` | Defines the LLM agent (`create_react_agent`) with tools |
| `agent_executor.py` | Adapts the agent to the A2A `AgentExecutor` interface — receives `RequestContext`, drives the agent, calls `TaskUpdater` to emit results |
| `__main__.py` | Builds the `AgentCard`, wires up `A2AStarletteApplication` + `DefaultRequestHandler`, starts `uvicorn` |

The Host Agent does not use `AgentExecutor` — it serves a browser chat UI directly via Starlette.

### State is in-memory and ephemeral

- The application registry (`APPLICATIONS` list in `application_agent/app/agent.py`) is populated at startup and never persisted — updates reset on restart.
- Sessions use `MemorySaver` (LangGraph) in both the host and application agents.

### Models in use

- Host Agent: `gemini-2.5-flash` (via `langchain-google-genai`)
- Application Agent: `gemini-2.5-flash` (via `langchain-google-genai`)

## Key Design Note

The A2A protocol requires each agent to advertise an `AgentCard` at `/.well-known/agent.json` (handled automatically by `A2AStarletteApplication`). The host resolves this card at startup — if the Application Agent is not running when the host starts, it will be silently absent from the host's available-agent list.
