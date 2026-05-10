# Project: A2A Application Management Demo

## 1. Overview

This project demonstrates a multi-agent system built on the Agent-to-Agent (A2A) communication protocol. A central Host Agent orchestrates domain agents, each of which owns a specific capability. The initial domain agent manages a registry of software applications.

## 2. Architecture

```
Browser (http://localhost:10001)
      │  POST /chat  (SSE stream)
      ▼
Host Agent (LangGraph, port 10001)    ← user interacts here
      │
      │  A2A JSON-RPC  POST /
      ▼
Application Agent (LangGraph, port 10005)
```

- **Host Agent** (`host_agent_langgraph`): The central orchestrator. Serves the browser chat UI, discovers domain agents at startup via their AgentCards, and routes user requests to the appropriate agent using the `send_message` tool.
- **Application Agent** (`application_agent`): A domain agent that manages an in-memory registry of software applications. Supports listing apps by owner, retrieving descriptions, and updating descriptions.

## 3. Agents

### 3.1. Host Agent

- **Framework:** LangGraph (`create_react_agent`) + Starlette web server
- **Role:** Orchestrator. Serves the chat UI and routes requests to domain agents via A2A `SendMessageRequest`.
- **Port:** `10001`
- **Model:** `gemini-2.5-flash` (via `langchain-google-genai`)

### 3.2. Application Agent

- **Framework:** LangGraph (`create_react_agent`) + A2A SDK (`A2AStarletteApplication`)
- **Role:** Domain agent for application registry management.
- **Port:** `10005`
- **Model:** `gemini-2.5-flash` (via `langchain-google-genai`)

**Tools:**

| Tool | Input | Output |
|---|---|---|
| `get_applications_by_owner` | `owner_user_id` | All apps owned by that user |
| `get_application_description` | `identifier` (app ID or name) | App name, ID, and description |
| `update_application_description` | `application_id`, `new_description` | Success or failure message |

**Sample data (in-memory, resets on restart):**

| ID | Name | Owner |
|---|---|---|
| app-001 | BillingService | user-alice |
| app-002 | InventoryManager | user-bob |
| app-003 | NotificationHub | user-alice |
| app-004 | ReportingDashboard | user-carol |
| app-005 | AuthService | user-bob |

## 4. A2A Protocol Mechanics

- Each domain agent advertises its capabilities at `/.well-known/agent.json` (the AgentCard), served automatically by `A2AStarletteApplication`.
- The Host Agent resolves these cards at startup via `A2ACardResolver`. Agents not reachable at startup are silently skipped.
- When the host LLM decides to delegate, it calls `send_message(agent_name, task)`. This POSTs a `SendMessageRequest` to the domain agent's endpoint and returns the result text extracted from the Task's artifacts.

## 5. State

All state is in-memory and ephemeral — the application registry and conversation histories reset on every restart. LangGraph `MemorySaver` preserves per-session chat history within a single process run.

## 6. Extensibility

Additional domain agents can be added by:
1. Creating a new agent subproject following the same three-file pattern (`agent.py`, `agent_executor.py`, `__main__.py`).
2. Adding its URL to the `friend_agent_urls` list in `host_agent_langgraph/host/__main__.py`.
3. Restarting the host agent to pick up the new AgentCard.
