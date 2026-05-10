# Host Agent — Implementation Notes

This document describes the current implementation of the Host Agent (`host_agent_langgraph`).

## What was built

The Host Agent is a Starlette web application backed by a LangGraph `create_react_agent`. It:

1. Serves a browser chat UI at `http://localhost:10001`.
2. Accepts user messages via `POST /chat` and streams responses back as Server-Sent Events (SSE).
3. At startup, discovers domain agents by fetching their AgentCards from `/.well-known/agent.json`.
4. Routes user requests to the appropriate domain agent using the `send_message` tool.

## File structure

```
host_agent_langgraph/
├── pyproject.toml
└── host/
    ├── __main__.py                # Starlette server; lifespan initialises HostAgent
    ├── agent.py                   # HostAgent class; send_message tool; LangGraph graph
    ├── remote_agent_connection.py # A2AClient wrapper with request/response logging
    └── _step.py                   # Thread-safe step counter for debug logs
```

## Domain agents

The host currently connects to one domain agent:

| Agent | URL | Port |
|---|---|---|
| Application Agent | `http://localhost:10005` | 10005 |

URLs are listed in `host/__main__.py` → `lifespan()` → `friend_agent_urls`.

## Adding a new domain agent

1. Start the new agent on a free port so it serves a valid AgentCard at `/.well-known/agent.json`.
2. Append its URL to `friend_agent_urls` in `host/__main__.py`.
3. Restart the host agent — it will pick up the new card and inject it into the system prompt automatically.

## System prompt

The system prompt (built in `HostAgent._build_graph`) tells the LLM:
- Today's date.
- The list of available domain agents (injected from the discovered AgentCards).
- Routing rules for each supported operation.

New routing rules for additional domain agents should be added to the system prompt when those agents are introduced.
