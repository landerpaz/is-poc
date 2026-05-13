# Agentic AI Implementation Analysis

This document maps the six foundational steps of agentic AI against the current codebase, then lists gaps and concrete improvement opportunities.

---

## USED STEPS — What Is Implemented and How

---

### 01 · FOUNDATIONS

#### LLM Fundamentals: Prompting, Context, Sampling ✅

Both agents use `gemini-2.5-flash` via `langchain-google-genai`.

**Application Agent** (`application_agent/app/agent.py:143–156`):
- Crafts a precise system prompt that names each tool and defines exactly when to call it.
- Uses `response_format=ResponseFormat` to force structured output with a typed `status` field (`completed` / `input_required` / `error`). This constrains sampling to valid states and prevents the LLM from free-forming a response.

**Host Agent** (`host_agent_langgraph/host/agent.py:133–174`):
- Dynamically injects the list of registered sub-agents (name + description) into the system prompt at graph-build time so the LLM always has an up-to-date picture of what it can delegate to.
- Embeds today's date to give the model time-aware context.

#### ReAct Pattern: Reason + Act Loops ✅

Both agents are built with `langgraph.prebuilt.create_react_agent`, which implements the full Reason → Act → Observe loop natively.

- The Application Agent reasons over the user query, selects one of its three registry tools, observes the tool result, then emits a structured final answer.
- The Host Agent reasons over user intent, calls `send_message(agent_name, task)`, observes the delegated response, then formulates a reply.
- Intermediate streaming updates confirm the loop is executing: `"Looking up application data..."` and `"Processing result..."` are yielded on `AIMessage.tool_calls` and `ToolMessage` events respectively (`application_agent/app/agent.py:184–195`).

#### Agent Lifecycle: Plan → Execute → Reflect ⚠️ Partial

Execution is fully implemented. Planning and reflection are absent:
- There is no explicit planning step before tool calls.
- After a tool result there is no self-critique or validation pass — the agent emits the final structured response immediately.

---

### 02 · CORE COMPONENTS

#### Tools & Function Calling: APIs ✅

**Application Agent tools** (`application_agent/app/agent.py:66–120`):

| Tool | Purpose |
|---|---|
| `get_applications_by_owner` | Queries the in-memory registry by `owner_user_id` |
| `get_application_description` | Looks up an app by ID or name |
| `update_application_description` | Mutates an app's description in place |

Each tool uses a Pydantic `BaseModel` as `args_schema`, giving LangChain a typed JSON schema to pass to the LLM for function calling.

**Host Agent tool** (`host_agent_langgraph/host/agent.py:76–131`):

| Tool | Purpose |
|---|---|
| `send_message(agent_name, task)` | Posts a task to a remote A2A agent over HTTP and returns extracted text artifacts |

#### Memory Systems: In-Context (Session) ✅ — External / Long-Term ❌

Both agents instantiate `MemorySaver` from `langgraph.checkpoint.memory`:

```python
# application_agent/app/agent.py:13
memory = MemorySaver()

# host_agent_langgraph/host/agent.py:29
_memory = MemorySaver()
```

Sessions are keyed by `thread_id` (`context_id` in the Application Agent, `session_id` in the Host Agent). This provides turn-by-turn in-context memory within a session. However:
- `MemorySaver` is purely in-process RAM — state is lost on restart.
- There is no external store (Redis, Postgres, etc.) for durable conversation history.
- There is no long-term memory (user profiles, cross-session facts).

#### Context Engineering: State-Aware Prompts ✅

The Host Agent prompt is assembled at graph-build time by injecting the discovered agent registry:

```python
# host_agent_langgraph/host/agent.py:63–68
agent_info = [
    json.dumps({"name": card.name, "description": card.description})
    for card in self.cards.values()
]
self.agents = "\n".join(agent_info) if agent_info else "No domains found"
```

This means the LLM's system prompt automatically reflects which sub-agents are reachable at startup — if no agents respond, the prompt says `"No domains found"` and the host degrades gracefully.

---

### 03 · ORCHESTRATION

#### LangGraph: Stateful Graphs, Routing ✅

Both agents use LangGraph's prebuilt ReAct graph with a `MemorySaver` checkpointer. The `thread_id` / `context_id` passed in `RunnableConfig` enables per-session state checkpointing, so multi-turn conversations accumulate context within the graph.

Routing within each agent is implicit: the LLM decides which tool to call based on the system prompt and user message, and LangGraph handles the tool-call → tool-result → next-step loop.

#### Multi-Agent Systems: Supervisor + Worker Pattern ✅

The system is a textbook two-tier supervisor/worker setup:

```
Browser → Host Agent (supervisor, port 10001)
                └──→ Application Agent (worker, port 10005)
```

- **Host Agent** is the supervisor. It holds references to all registered sub-agents in `self.remote_agent_connections` and decides which worker to call.
- **Application Agent** is the worker. It is fully isolated — it knows nothing about the host and exposes only its A2A endpoint.
- Discovery happens over the A2A protocol: the host fetches the Application Agent's `AgentCard` from `/.well-known/agent.json` at startup (`host_agent_langgraph/host/agent.py:49–52`).
- Communication uses `SendMessageRequest` / `SendMessageResponse` typed objects from the `a2a-sdk` (`host_agent_langgraph/host/remote_agent_connection.py:43–87`).

#### Human-in-the-Loop: Approval Gates, Interrupts ⚠️ Partial

The `input_required` task state propagates a pause signal back to the user:

```python
# application_agent/app/agent_executor.py:62–75
elif require_user_input:
    await updater.update_status(
        TaskState.input_required,
        message=updater.new_agent_message(parts),
        final=True,
    )
    break
```

When the Application Agent cannot proceed (e.g., a required parameter is missing), it sets `TaskState.input_required` and stops. The Host Agent relays this back to the browser. This is a lightweight human-in-the-loop signal — but it is not an explicit LangGraph interrupt/approval gate where a human can inspect and modify graph state before resumption.

---

### 05 · DESIGN PATTERNS

#### Router Agent: Classify → Delegate ✅

The Host Agent's system prompt defines a routing table:

```
When the user asks anything about software applications → route to "Application Agent" using send_message
```

The LLM classifies the user's intent against the registered agents (injected dynamically), selects the appropriate worker, and delegates via `send_message`. The host also enforces pre-delegation validation: if a required parameter is missing it asks the user before calling the sub-agent.

---

### 06 · SAFETY & EVAL

#### Guardrails: Input Validation ⚠️ Partial

Tool inputs are validated via Pydantic `BaseModel` schemas:

```python
# application_agent/app/agent.py:66–68
class GetApplicationsByOwnerInput(BaseModel):
    owner_user_id: str = Field(..., description="...")
```

LangChain uses these schemas to constrain what the LLM can pass to each tool. There is no PII filtering, prompt-injection defense, or output sanitisation layer.

---

## NOT USED — Gaps and Potential Improvements

---

### 01 · FOUNDATIONS — Agent Reflection

**Gap:** After the LLM receives a tool result, it immediately generates a final answer. There is no self-critique step.

**Improvement:** Add a reflection node to each ReAct graph. After the tool result, ask the LLM: *"Is this answer complete, accurate, and sufficient for the user's original request?"* If not, re-enter the tool-call loop. This is especially valuable for the `update_application_description` tool where the agent could verify the update succeeded by immediately calling `get_application_description` to confirm the change.

---

### 02 · CORE COMPONENTS — External & Long-Term Memory

**Gap:** `MemorySaver` is in-process RAM. All session history is lost on restart.

**Improvements:**
- Replace `MemorySaver` with `langgraph.checkpoint.postgres.AsyncPostgresSaver` or `SqliteSaver` for durable sessions.
- Add a long-term memory store (e.g. a vector database) so the host can recall facts across sessions — for example, remembering that a particular user often queries `user-alice`'s applications.

---

### 03 · ORCHESTRATION — Human-in-the-Loop Approval Gates

**Gap:** There is no LangGraph `interrupt` point. Destructive operations like `update_application_description` execute immediately without user confirmation.

**Improvement:** Insert a LangGraph interrupt before any mutating tool call. The graph pauses, streams a confirmation prompt to the browser (`"Are you sure you want to update app-002's description?"`), waits for the human's approval event, then resumes. This can be implemented with LangGraph's `interrupt_before` checkpoint config or a custom `human_approval` node.

---

### 04 · RAG & RETRIEVAL — Entirely Missing

**Gap:** The application registry is a hardcoded Python list. There is no retrieval layer.

**Improvements (in order of complexity):**

1. **Agentic RAG (highest impact):** Move the registry to a vector store (e.g. ChromaDB, pgvector). Give the Application Agent a `search_applications(query)` tool that embeds the query and does semantic similarity search. The agent decides when to retrieve vs. when it already has enough context — this is the *Agentic RAG* pattern where retrieval is a tool choice, not a fixed pipeline step.

2. **Chunking & indexing:** If application descriptions become long documents (runbooks, architecture docs), apply semantic chunking before indexing so retrieval returns relevant paragraphs, not entire documents.

3. **Advanced RAG:** Add a re-ranking step (e.g. Cohere Rerank) after the initial vector search to improve result quality before passing context to the LLM.

---

### 05 · DESIGN PATTERNS — Reflection Agent & Plan-and-Self-Heal

**Gap — Reflection:** Neither agent critiques its own output. The Application Agent emits `status=completed` as soon as it has a tool result, even if that result is incomplete or ambiguous.

**Improvement:** Add a post-response self-evaluation node. The agent scores its own answer on dimensions like completeness and correctness, then either returns it or re-invokes a tool to fill gaps. This is the *Reflection* pattern.

**Gap — Plan & Self-Heal:** The Host Agent has no planning step and no recovery logic beyond a generic error message.

**Improvement:** Before delegating, have the Host Agent emit an explicit plan: *"I will call Application Agent with task X to answer this."* After receiving the response, a self-heal node checks whether the task was actually completed. If the Application Agent returned `input_required` or an error, the host retries with a refined query rather than surfacing the raw error to the user.

---

### 06 · SAFETY & EVAL — Comprehensive Guardrails & Evaluation

**Gap — Guardrails:** No PII detection, no prompt-injection defense, no output content filter.

**Improvements:**
- Add a PII-scrubbing middleware layer on the Starlette `/chat` endpoint before user input reaches the LLM.
- Add a prompt-injection guard (detect jailbreak attempts, role-override instructions) on inbound messages to both agents.
- Validate that tool arguments never contain shell metacharacters or SQL fragments (relevant if the registry moves to a real database).

**Gap — Evaluation:** There are no tests, no trajectory logging, and no tool-accuracy metrics.

**Improvements:**
- **Trajectory evaluation:** Log each full agent trajectory (messages, tool calls, tool results, final answer) to a structured store. Evaluate offline using an LLM judge against golden answers.
- **Tool accuracy:** Build a small eval set of (query → expected tool call → expected result) triples. Run the Application Agent against them in CI and assert tool selection accuracy and output correctness.
- **End-to-end integration tests:** Start both agents in a test subprocess and assert that specific user queries produce the correct A2A task state (`completed` vs. `input_required`).

---

## Summary Table

| Step | Sub-topic | Status | Notes |
|---|---|---|---|
| 01 Foundations | LLM Fundamentals | ✅ Used | Structured output, tool-aware prompts |
| 01 Foundations | ReAct Pattern | ✅ Used | `create_react_agent` in both agents |
| 01 Foundations | Agent Lifecycle (reflect) | ⚠️ Partial | Execute only; no plan or reflect step |
| 02 Core Components | Tools & Function Calling | ✅ Used | 3 registry tools + 1 inter-agent tool |
| 02 Core Components | In-Context Memory | ✅ Used | `MemorySaver` with thread_id sessions |
| 02 Core Components | External / Long-Term Memory | ❌ Missing | RAM only; no persistence |
| 02 Core Components | Context Engineering | ✅ Used | Dynamic agent-list injection in host prompt |
| 03 Orchestration | LangGraph Stateful Graphs | ✅ Used | Checkpointed ReAct graphs |
| 03 Orchestration | Multi-Agent Supervisor+Worker | ✅ Used | Host + Application Agent via A2A |
| 03 Orchestration | Human-in-the-Loop | ⚠️ Partial | `input_required` state; no LangGraph interrupt |
| 04 RAG & Retrieval | Chunking Strategies | ❌ Missing | — |
| 04 RAG & Retrieval | Advanced RAG | ❌ Missing | — |
| 04 RAG & Retrieval | Agentic RAG | ❌ Missing | Registry is a hardcoded list |
| 05 Design Patterns | Router Agent | ✅ Used | Host classifies intent and delegates |
| 05 Design Patterns | Reflection Agent | ❌ Missing | No self-critique loop |
| 05 Design Patterns | Plan & Self-Heal | ❌ Missing | No planning or retry-on-failure |
| 06 Safety & Eval | Guardrails (input validation) | ⚠️ Partial | Pydantic schemas only; no PII/injection |
| 06 Safety & Eval | Evaluation Framework | ❌ Missing | No tests, logging, or metrics |
