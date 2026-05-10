# Code Walkthrough — A2A Application Management Demo

This document explains every Python file and method in the project, written to be read top-to-bottom by someone new to the codebase. Start with the Architecture Overview, then follow each agent in the order they are started.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Shared Concept: The Step Counter](#shared-concept-the-step-counter)
3. [Host Agent (LangGraph) — `host_agent_langgraph/`](#host-agent-langgraph)
   - [`host/__main__.py`](#host__mainpy)
   - [`host/agent.py`](#hostagentpy)
   - [`host/remote_agent_connection.py`](#hostremote_agent_connectionpy)
   - [`host/_step.py`](#host_steppy)
4. [Application Agent (LangGraph) — `application_agent/`](#application-agent-langgraph)
   - [`app/__main__.py`](#app__mainpy-application)
   - [`app/agent.py`](#appagentpy-application)
   - [`app/agent_executor.py`](#appagent_executorpy-application)

---

## Architecture Overview

```
Browser (http://localhost:10001)
        │  POST /chat  (SSE stream)
        ▼
Host Agent  ── LangGraph ──  gemini-2.5-flash  (port 10001)
        │
        │  A2A JSON-RPC  POST /
        └──────────────────────▶  Application Agent  (LangGraph, port 10005)
```

**How a request flows end-to-end:**

1. The user types a message in the browser.
2. The browser POSTs to `/chat` on the Host Agent and reads back a Server-Sent Events (SSE) stream.
3. The Host Agent's LangGraph graph decides to route the request and calls the `send_message` tool.
4. `send_message` wraps the query in an A2A `SendMessageRequest` and POSTs it to the Application Agent's HTTP endpoint.
5. The Application Agent queries or updates its in-memory application registry and responds with a `Task` result.
6. The host collects the result from the task artifacts and streams the final answer back to the browser.

---

## Shared Concept: The Step Counter

**File:** `host_agent_langgraph/host/_step.py`

Every `print` statement in the host uses `[Step NNN]` prefixes so you can read the terminal log and follow the exact order of execution across concurrent async calls.

### `step() → int`

- Increments a shared integer counter by 1 and returns the new value.
- Protected by a `threading.Lock` so concurrent coroutines never print the same step number.
- Called inline inside f-strings: `f"[Step {step():>3}] >> ENTER ..."`.

---

## Host Agent (LangGraph)

### `host/__main__.py`

This file is the web server entry point. Running it starts a Starlette HTTP server on port 10001 and serves the chat UI.

---

#### `lifespan(app)` — async context manager

**Purpose:** Runs once at server startup and once at shutdown (the async-with pattern Starlette uses for lifecycle hooks).

**Step by step:**
1. Checks that `GOOGLE_API_KEY` is set; exits immediately if not.
2. Defines the domain agent URL — the Application Agent at `http://localhost:10005`.
3. Calls `await HostAgent.create(...)` which fetches the Application Agent's `AgentCard` over HTTP and builds the LangGraph graph.
4. Stores the created `HostAgent` in the module-level `_host_agent` variable so the route handlers can use it.
5. `yield` — the server is now running and serving requests.

---

#### `homepage(request) → HTMLResponse`

**Purpose:** Serves the single-page chat UI.

Returns the `_HTML` constant — a self-contained HTML/CSS/JS page — as an HTTP response. No server-side templating; everything the browser needs is in that one string.

---

#### `chat_endpoint(request) → StreamingResponse`

**Purpose:** Receives a user message from the browser and streams the agent's reply back using Server-Sent Events (SSE).

**Step by step:**
1. Parses the JSON body to get `message` (user text) and `session_id` (browser-generated random ID that ties conversation turns together).
2. Defines an inner async generator `generate()` that:
   - Calls `_host_agent.stream(query, session_id)` and iterates over every yielded chunk.
   - Serialises each chunk to JSON and formats it as an SSE `data:` line.
   - Emits a final `data: [DONE]` line to signal the end of the stream.
3. Returns a `StreamingResponse` with `media_type="text/event-stream"` so the browser's `fetch` reader sees a live stream.

---

### `host/agent.py`

This file defines `HostAgent` — the orchestrator that owns the LangGraph graph, holds connections to domain agents, and exposes the `send_message` tool the LLM uses.

---

#### `HostAgent.__init__(self)`

**Purpose:** Creates an empty shell. No LLM or HTTP connections are made here.

Initialises four instance variables:
- `remote_agent_connections` — dict mapping agent name → `RemoteAgentConnections` instance.
- `cards` — dict mapping agent name → `AgentCard` (metadata about each domain agent).
- `agents` — string that will hold a JSON summary injected into the system prompt.
- `graph` — will hold the compiled LangGraph `CompiledGraph` after `_build_graph` runs.

---

#### `HostAgent._async_init_components(self, remote_agent_addresses)`

**Purpose:** Discovers domain agents by fetching their `AgentCard` from `/.well-known/agent.json` and stores a live connection for each.

**Step by step:**
1. Opens a shared `httpx.AsyncClient` (30-second timeout).
2. For each URL in `remote_agent_addresses`:
   - Creates an `A2ACardResolver` pointed at that URL.
   - Calls `await card_resolver.get_agent_card()` — an HTTP GET to `<url>/.well-known/agent.json`.
   - On success: wraps the card in a `RemoteAgentConnections` and stores it under the agent's name.
   - On `httpx.ConnectError` or any other exception: logs the error and moves on (missing agents are silently skipped).
3. Builds `self.agents` — a newline-joined list of `{"name": ..., "description": ...}` JSON objects. This string is later inserted into the LLM system prompt so the model knows which domain agents exist.

---

#### `HostAgent._build_graph(self)`

**Purpose:** Constructs the LangGraph `create_react_agent` graph with the system prompt and tools.

**Step by step:**
1. Captures `remote_connections` and `agents_info` as local variables (closures for the nested tool function).
2. Defines the `send_message` tool (see below).
3. Writes the system prompt string, embedding today's date and the available-agents list.
4. Creates a `ChatGoogleGenerativeAI` model instance using `gemini-2.5-flash`.
5. Calls `create_react_agent(model, tools=[send_message], checkpointer=_memory, prompt=system_prompt)` which compiles the ReAct loop graph with in-memory conversation history.
6. Stores the graph in `self.graph`.

**`send_message(agent_name, task)` — inner tool function**

This is the primary tool the LLM calls to delegate a task to a domain agent.

1. Looks up `agent_name` in `remote_connections`; raises `ValueError` if not found.
2. Generates fresh UUIDs for `message_id` and `context_id` (each call starts a new A2A task).
3. Builds a `SendMessageRequest` payload with the user's question as a `TextPart`.
4. Calls `await client.send_message(message_request)` — sends the A2A JSON-RPC POST.
5. Checks the response is a `SendMessageSuccessResponse` containing a `Task`; returns `"No response received from the agent."` otherwise.
6. Extracts text from two locations in order of priority:
   - **Artifacts** (`task.artifacts`) — used when the domain agent completes successfully.
   - **Status message** (`task.status.message`) — fallback for `input_required` or error states.
7. Joins all text parts with `\n` and returns the result string to the LLM.

---

#### `HostAgent.create(cls, remote_agent_addresses)` — classmethod

**Purpose:** Single entry point that fully initialises a `HostAgent`.

**Step by step:**
1. Calls `cls()` to get an empty instance.
2. Calls `await instance._async_init_components(...)` to discover domain agents.
3. Calls `instance._build_graph()` to compile the LangGraph graph.
4. Returns the ready instance.

Why a classmethod instead of `__init__`? Because `_async_init_components` is async, and `__init__` cannot be async. The classmethod acts as an async factory.

---

#### `HostAgent.stream(self, query, session_id) → AsyncIterable[dict]`

**Purpose:** Runs one turn of the conversation through the LangGraph graph and yields status dicts back to the web server.

**Step by step:**
1. Wraps the user's query as a LangGraph `{"messages": [("user", query)]}` input.
2. Builds a `RunnableConfig` with `thread_id=session_id` so `MemorySaver` can persist conversation history per session.
3. Calls `self.graph.astream(inputs, config, stream_mode="values")` — runs the ReAct loop and yields the full state snapshot after every node completes.
4. Inspects the last message in each snapshot:
   - `AIMessage` with tool calls → the LLM is calling a tool; yields `{"is_task_complete": False, "content": "The host agent is thinking..."}`.
   - `ToolMessage` → a tool just returned; yields the same thinking indicator.
   - `AIMessage` with no tool calls → the LLM produced its final answer; yields `{"is_task_complete": True, "content": <text>}`.

---

### `host/remote_agent_connection.py`

This file manages the HTTP connection to a single domain agent and logs every request/response.

---

#### `RemoteAgentConnections.__init__(self, agent_card, agent_url)`

**Purpose:** Creates an `A2AClient` pointed at one domain agent.

Stores:
- `_httpx_client` — a persistent async HTTP client (reused across all calls to this agent).
- `agent_client` — the A2A SDK client that knows the agent's card and URL.
- `card` — the `AgentCard` (used for the agent's display name in logs).

---

#### `RemoteAgentConnections.get_agent() → AgentCard`

Returns the stored `AgentCard`. Used by the host to read the agent's metadata.

---

#### `RemoteAgentConnections.send_message(self, message_request) → SendMessageResponse`

**Purpose:** Sends one A2A `message/send` request to the domain agent and returns the response, printing a formatted log block before and after the HTTP call.

**Before the call:**
Prints a box showing: destination agent name, message role, task ID, context ID, and the message text.

**The call itself:**
Calls `await self.agent_client.send_message(message_request)` — the actual HTTP POST.

**After the call:**
If the response is a `SendMessageSuccessResponse` containing a `Task`, prints a box showing: source agent name, task ID, task state, status text, and artifact text. Otherwise prints the raw response.

---

### `host/_step.py`

Provides the `step()` function — a thread-safe incrementing counter used as a debug log prefix (`[Step NNN]`) so concurrent async calls can be followed in order in the terminal output.

---

## Application Agent (LangGraph)

### `app/__main__.py` (Application)

Entry point for the Application Agent server on port 10005.

---

#### `MissingAPIKeyError`

A custom exception class used to signal that `GOOGLE_API_KEY` is not set.

---

#### `main()`

**Purpose:** Wires up and starts the A2A server for the Application Agent.

**Step by step:**
1. Validates `GOOGLE_API_KEY`.
2. Builds an `AgentCard` describing the agent's capabilities (`streaming=True`) and the three skills it offers.
3. Creates an `ApplicationAgentExecutor` (which internally creates an `ApplicationAgent`).
4. Creates a `DefaultRequestHandler` with:
   - The executor — runs the agent logic.
   - An `InMemoryTaskStore` — stores task state in RAM.
5. Wraps everything in `A2AStarletteApplication` which automatically serves the `AgentCard` at `/.well-known/agent.json` and routes A2A JSON-RPC calls to the handler.
6. Starts `uvicorn` on port 10005.

**Skills advertised in the AgentCard:**

| Skill ID | Name | What it does |
|---|---|---|
| `get_applications_by_owner` | Get Applications by Owner | Lists all apps owned by a given user ID |
| `get_application_description` | Get Application Description | Returns the description of an app by ID or name |
| `update_application_description` | Update Application Description | Updates an app's description by ID |

---

### `app/agent.py` (Application)

Defines the data model, tools, and the LangGraph agent that handles application management queries.

---

#### `Application` — dataclass

The data model for a software application entry.

| Field | Example |
|---|---|
| `application_name` | `"BillingService"` |
| `application_id` | `"app-001"` |
| `application_description` | `"Handles all billing and payment processing."` |
| `owner_user_id` | `"user-alice"` |

---

#### `APPLICATIONS` — module-level list

A hard-coded in-memory registry of five applications populated at module import time. Mutations (via `update_application_description`) persist for the lifetime of the process and reset on restart.

| ID | Name | Owner |
|---|---|---|
| app-001 | BillingService | user-alice |
| app-002 | InventoryManager | user-bob |
| app-003 | NotificationHub | user-alice |
| app-004 | ReportingDashboard | user-carol |
| app-005 | AuthService | user-bob |

---

#### `get_applications_by_owner(owner_user_id) → str` — LangGraph tool

**Purpose:** Returns all applications owned by a given user.

1. Filters `APPLICATIONS` to entries whose `owner_user_id` matches.
2. Returns a formatted string listing name, ID, and description for each match, or a "not found" message if the owner has no apps.

---

#### `get_application_description(identifier) → str` — LangGraph tool

**Purpose:** Returns the description of an application looked up by its ID or name.

1. Searches `APPLICATIONS` for an entry where `application_id == identifier` or `application_name == identifier`.
2. Returns the name, ID, and description, or a "not found" message.

---

#### `update_application_description(application_id, new_description) → str` — LangGraph tool

**Purpose:** Replaces the description of an application identified by ID.

1. Finds the application by `application_id`.
2. Mutates `match.application_description` in-place.
3. Returns a success message, or a failure message if the ID was not found.

---

#### `ResponseFormat` — Pydantic model

A structured output schema used by LangGraph's `response_format` feature.

| Field | Type | Meaning |
|---|---|---|
| `status` | `"input_required"` \| `"completed"` \| `"error"` | Whether the agent is done or needs more input |
| `message` | `str` | The text to send back |

The LLM is instructed to always populate this schema so `get_agent_response` can read a typed object rather than parsing free text.

---

#### `ApplicationAgent.__init__(self)`

**Purpose:** Builds the LangGraph `create_react_agent` graph.

1. Creates `ChatGoogleGenerativeAI(model="gemini-2.5-flash")`.
2. Sets `self.tools = [get_applications_by_owner, get_application_description, update_application_description]`.
3. Calls `create_react_agent` with:
   - The model and tools.
   - `checkpointer=memory` (a module-level `MemorySaver`) so conversation history is retained per `thread_id`.
   - `prompt=SYSTEM_INSTRUCTION` — the agent's persona and status-setting rules.
   - `response_format=ResponseFormat` — forces the LLM's final answer into the typed schema.

---

#### `ApplicationAgent.invoke(self, query, context_id)`

**Purpose:** Runs the graph synchronously and returns the structured response dict.

1. Builds a `RunnableConfig` using `context_id` as the `thread_id`.
2. Calls `self.graph.invoke(...)` — blocks until the graph finishes.
3. Calls `self.get_agent_response(config)` to extract the typed result.

> **Note:** This method exists but is not used by the executor (which uses `stream` instead). It can be called directly for testing.

---

#### `ApplicationAgent.stream(self, query, context_id) → AsyncIterable[dict]`

**Purpose:** Runs the graph and yields intermediate progress dicts followed by the final result dict.

**Step by step:**
1. Calls `self.graph.astream(inputs, config, stream_mode="values")` — yields the full state snapshot after every node.
2. For each snapshot, inspects the last message:
   - `AIMessage` with tool calls → the LLM is calling a tool; yields `{"is_task_complete": False, "require_user_input": False, "content": "Looking up application data..."}`.
   - `ToolMessage` → the tool just returned; yields `{"is_task_complete": False, "require_user_input": False, "content": "Processing result..."}`.
3. After the loop ends, calls `self.get_agent_response(config)` and yields that as the **final** dict.

---

#### `ApplicationAgent.get_agent_response(self, config) → dict`

**Purpose:** Reads the LLM's typed `ResponseFormat` from the graph's final state and maps it to a standard response dict.

**Step by step:**
1. Calls `self.graph.get_state(config)` to read the persisted state for this `thread_id`.
2. Looks up `"structured_response"` in `state.values` — LangGraph places the `response_format` output here.
3. Maps each `ResponseFormat.status` value:
   - `"completed"` → `{"is_task_complete": True, "require_user_input": False, "content": message}`.
   - `"input_required"` → `{"is_task_complete": False, "require_user_input": True, "content": message}`.
   - `"error"` → `{"is_task_complete": False, "require_user_input": True, "content": message}`.
4. If `structured_response` is missing → returns a generic "unable to process" dict with `require_user_input=True`.

---

### `app/agent_executor.py` (Application)

Bridges the `ApplicationAgent` to the A2A server's `AgentExecutor` interface.

---

#### `ApplicationAgentExecutor.__init__(self)`

Creates an `ApplicationAgent` instance and stores it as `self.agent`.

---

#### `ApplicationAgentExecutor.execute(self, context, event_queue)`

**Purpose:** Receives an incoming A2A task, runs the agent, and publishes task state events to the `event_queue` for the A2A server to consume.

**Step by step:**
1. Validates that `context.task_id`, `context.context_id`, and `context.message` are all set.
2. Creates a `TaskUpdater` — a helper that enqueues typed A2A events onto `event_queue`.
3. If this is a new task: calls `await updater.submit()` — emits a `submitted` status event.
4. Calls `await updater.start_work()` — emits a `working` status event.
5. Extracts the user's text via `context.get_user_input()`.
6. Iterates over `self.agent.stream(query, context_id)`:
   - **Intermediate item** (`is_task_complete=False`, `require_user_input=False`): emits a `working` status event with the intermediate text.
   - **Input-required item** (`require_user_input=True`): emits an `input_required` status event with `final=True` and breaks.
   - **Completion item** (`is_task_complete=True`): calls `await updater.add_artifact(parts)` (attaches the answer as a task artifact named `"application_result"`), then `await updater.complete()` and breaks.
7. On any exception: raises a `ServerError(InternalError())`.

---

#### `ApplicationAgentExecutor.cancel(self, context, event_queue)`

Raises `ServerError(UnsupportedOperationError())` — cancellation is not supported.
