# Host Agent (LangGraph)

The Host Agent is the central orchestrator of this A2A demo. It serves a browser-based chat UI, discovers domain agents at startup, and routes user requests to them over the A2A protocol.

Built with **LangGraph** (`create_react_agent`) and served via a lightweight **Starlette** web application.

## Architecture

```
Browser (http://localhost:10001)
        │  POST /chat  (SSE stream)
        ▼
Host Agent (LangGraph, port 10001)    ← you interact here
        │
        │  A2A JSON-RPC  POST /
        └──→ Application Agent (LangGraph, port 10005)
```

At startup the host fetches each domain's **AgentCard** via `A2ACardResolver`. Discovered agents are injected into the system prompt so the LLM knows who to contact. If a domain agent is not reachable at startup it is silently skipped.

## Prerequisites

- **Python 3.12+**
- **uv** — [install guide](https://docs.astral.sh/uv/getting-started/installation/)
- A `.env` file in the **project root** containing:

```
GOOGLE_API_KEY="your_api_key_here"
```

## Running

Start the Application Agent first, then start this agent.

### Terminal 1 — Application Agent (port 10005)

```bash
cd application_agent
uv venv --python 3.13 && source .venv/bin/activate
uv run --active app/__main__.py
```

### Terminal 2 — Host Agent (this package, port 10001)

```bash
cd host_agent_langgraph
uv venv --python 3.13 && source .venv/bin/activate
uv run --active host/__main__.py
```

On first run `uv` creates the virtual environment and installs all dependencies automatically.

## Interacting with the Host Agent

Open **http://localhost:10001** in your browser. A chat interface will appear.

Example prompts:
- `List all applications owned by user-alice`
- `What does the BillingService application do?`
- `Update the description of app-002 to "Manages stock levels in real time."`

## Project Structure

```
host_agent_langgraph/
├── pyproject.toml                 # LangGraph / Starlette dependencies
└── host/
    ├── __main__.py                # Starlette web server + HTML chat UI (port 10001)
    ├── agent.py                   # HostAgent class (LangGraph react agent)
    ├── remote_agent_connection.py # A2A client wrapper for domain agents
    └── _step.py                   # Thread-safe step counter for debug logging
```

### Key files

| File | Role |
|---|---|
| `agent.py` | `HostAgent.create()` resolves domain AgentCards, builds a LangGraph `create_react_agent` with a `send_message` tool |
| `__main__.py` | Starlette app: serves the HTML chat UI at `/` and a streaming SSE endpoint at `/chat` |
| `remote_agent_connection.py` | Wraps `A2AClient` to send `SendMessageRequest` objects to domain agents with request/response logging |
| `_step.py` | Thread-safe counter used in `[Step NNN]` debug log prefixes |

## Models

| Agent | Model | Framework |
|---|---|---|
| Host Agent | `gemini-2.5-flash` | LangGraph / `langchain-google-genai` |
| Application Agent | `gemini-2.5-flash` | LangGraph / `langchain-google-genai` |

## Notes

- All state is **in-memory and ephemeral** — chat history resets on restart.
- Domain agents not running when the host starts are silently skipped; only discovered agents appear in the host's available-agent list.
- Sessions are identified by a random `session_id` generated in the browser; conversation history is preserved across messages within the same browser tab.
