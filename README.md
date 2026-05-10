# A2A Application Management Demo

A multi-agent demo using the Agent-to-Agent (A2A) protocol. Two agents communicate over HTTP — a Host Agent that serves the chat UI and routes requests, and an Application Agent that manages a registry of software applications.

## Agents

- **Host Agent** (`host_agent_langgraph`, port 10001) — LangGraph orchestrator with a browser-based chat UI. Routes user requests to domain agents via A2A.
- **Application Agent** (`application_agent`, port 10005) — LangGraph agent that lists, looks up, and updates application descriptions in an in-memory registry.

## Prerequisites

1. **Python 3.13** (see `.python-version`)
2. **uv** — [install guide](https://docs.astral.sh/uv/getting-started/installation/)
3. A `.env` file in the project root:

```
GOOGLE_API_KEY="your_api_key_here"
```

## Running the System

Start the Application Agent before the Host Agent so its AgentCard is discoverable at host startup.

### Terminal 1 — Application Agent (port 10005)

```bash
cd application_agent
uv venv --python 3.13
source .venv/bin/activate
uv run --active app/__main__.py
```

### Terminal 2 — Host Agent (port 10001)

```bash
cd host_agent_langgraph
uv venv --python 3.13
source .venv/bin/activate
uv run --active host/__main__.py
```

On first run `uv` creates the virtual environment and installs all dependencies automatically.

## Using the System

Open **http://localhost:10001** in your browser. A chat interface will appear.

Example prompts:
- `List all applications owned by user-alice`
- `What does the BillingService application do?`
- `Update the description of app-002 to "Manages stock levels in real time."`

## Architecture

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

## References

- https://github.com/google/a2a-python
- https://google.github.io/A2A/
