# A2A SDK Migration: 0.2.x → 1.0.2

## Overview

This document records every change made when upgrading `a2a-sdk` from `0.2.x` to `1.0.2`/`1.0.3` (the version installed satisfies `>=1.0.2,<2.0.0`).

---

## 1. Dependency Updates

| File | Before | After |
|---|---|---|
| `application_agent/pyproject.toml` | `a2a-sdk>=0.2.5,<0.3.0` | `a2a-sdk>=1.0.2,<2.0.0` |
| `application_agent/pyproject.toml` | _(not present)_ | `starlette>=0.41.0` added |
| `host_agent_langgraph/pyproject.toml` | `a2a-sdk>=0.2.5,<0.3.0` | `a2a-sdk>=1.0.2,<2.0.0` |

**Why `starlette` was added to `application_agent`:** In 0.2.x, the `A2AStarletteApplication` wrapper included Starlette as an internal dependency and built the app for you. In 1.0.2, Starlette is an optional extra (`a2a-sdk[http-server]`) and the app must be assembled manually, so `starlette` must be declared explicitly.

**New transitive dependencies installed with 1.0.x:**
- `protobuf` — types are now protobuf-generated instead of Pydantic models
- `google-api-core`, `googleapis-common-protos` — proto support
- `proto-plus`, `json-rpc`, `packaging` — protocol helpers

---

## 2. Architecture Change: Pydantic → Protobuf Types

**The single biggest change in 1.0.0.** All A2A types (`AgentCard`, `Task`, `Message`, `Part`, `TaskState`, `Role`, etc.) moved from Pydantic models to Protocol Buffer (protobuf) generated classes.

### What this means in practice

| Pydantic (0.2.x) | Protobuf (1.0.x) |
|---|---|
| `model.field` | `model.field` (same — protobuf uses snake_case) |
| `model.model_validate(dict)` | `ParseDict(dict, ModelClass())` |
| `model.model_dump(mode="json")` | `MessageToJson(model)` |
| `oneof_field.root.text` | `oneof_field.WhichOneof("content") == "text"` then `oneof_field.text` |
| `isinstance(x, SomeVariant)` for union types | `x.WhichOneof("payload")` |

### Part access pattern changed

`Part` in 1.0.x uses a protobuf `oneof` named `content` with variants: `text`, `raw`, `url`, `data`.

```python
# 0.2.x — Part was a Pydantic discriminated union, .root held the variant
if hasattr(p.root, "text"):
    value = p.root.text

# 1.0.x — Part is a proto message; check the active oneof field
if p.WhichOneof("content") == "text":
    value = p.text
```

### Optional message fields use HasField

```python
# 0.2.x
if task.status.message:
    ...

# 1.0.x
if task.status.HasField("message"):
    ...
```

---

## 3. Server-Side Changes (Application Agent)

### 3a. `A2AStarletteApplication` removed

`A2AStarletteApplication` was the single-call way to create the Starlette app. It is gone in 1.0.0. The replacement is two builder functions that return Starlette `Route` lists, combined manually into a `Starlette` app.

```python
# 0.2.x
server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
uvicorn.run(server.build(), host=host, port=port)

# 1.0.x
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from starlette.applications import Starlette

routes = create_agent_card_routes(agent_card) + create_jsonrpc_routes(request_handler, rpc_url="/")
app = Starlette(routes=routes)
uvicorn.run(app, host=host, port=port)
```

### 3b. `AgentCard` construction changed

`AgentCard` no longer has a `url` field. The agent's HTTP address is now declared in a `supported_interfaces` list, each entry being an `AgentInterface` with explicit protocol binding and version.

```python
# 0.2.x
AgentCard(
    url=f"http://{host}:{port}/",
    defaultInputModes=...,
    defaultOutputModes=...,
    ...
)

# 1.0.x
from a2a.types import AgentInterface
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol

AgentCard(
    supported_interfaces=[
        AgentInterface(
            url=f"http://{host}:{port}/",
            protocol_binding=TransportProtocol.JSONRPC,   # "JSONRPC"
            protocol_version=PROTOCOL_VERSION_CURRENT,     # "1.0"
        )
    ],
    default_input_modes=...,   # snake_case
    default_output_modes=...,  # snake_case
    ...
)
```

### 3c. Use `LegacyRequestHandler` for TaskUpdater-based executors

`DefaultRequestHandler` in 1.0.x is now an alias for `DefaultRequestHandlerV2`, which uses a new active-task registry. `DefaultRequestHandlerV2` requires the agent executor to enqueue a `Task` proto object as the _very first event_ before any `TaskStatusUpdateEvent` — a different contract from 0.2.x.

Our executor uses `TaskUpdater.submit()` followed by `start_work()`, which emit `TaskStatusUpdateEvent` directly (no prior `Task` object). This is fully compatible with `LegacyRequestHandler`, which pre-creates the task for the agent before calling `execute()`.

```python
# 0.2.x
DefaultRequestHandler(
    agent_executor=ApplicationAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

# 1.0.x — use LegacyRequestHandler to keep TaskUpdater-based executor unchanged
from a2a.server.request_handlers import LegacyRequestHandler

LegacyRequestHandler(
    agent_executor=ApplicationAgentExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,  # mandatory in both handlers
)
```

**Why not `DefaultRequestHandlerV2`?** Migrating to `DefaultRequestHandlerV2` would require the executor to emit a `Task` proto object first (before any status events), which is a deeper rewrite. `LegacyRequestHandler` is the correct handler for the `submit() → start_work() → update_status()` TaskUpdater pattern and carries full 1.0.x support otherwise.

### 3d. `TaskState` enum values renamed

All enum variants gained a `TASK_STATE_` prefix to match protobuf naming conventions.

| 0.2.x | 1.0.x |
|---|---|
| `TaskState.working` | `TaskState.TASK_STATE_WORKING` |
| `TaskState.input_required` | `TaskState.TASK_STATE_INPUT_REQUIRED` |
| `TaskState.completed` | `TaskState.TASK_STATE_COMPLETED` |
| `TaskState.failed` | `TaskState.TASK_STATE_FAILED` |
| `TaskState.submitted` | `TaskState.TASK_STATE_SUBMITTED` |
| `TaskState.canceled` | `TaskState.TASK_STATE_CANCELED` |

### 3e. `TaskUpdater.update_status` — `final` parameter removed

The `final=True` keyword argument is gone. Use the dedicated helper methods instead:

```python
# 0.2.x
await updater.update_status(TaskState.input_required, message=msg, final=True)

# 1.0.x — use the helper method
await updater.requires_input(message=msg)
# Or equivalently:
await updater.update_status(TaskState.TASK_STATE_INPUT_REQUIRED, message=msg)
```

Available helpers: `submit()`, `start_work()`, `complete()`, `failed()`, `reject()`, `cancel()`, `requires_input()`, `requires_auth()`.

### 3f. `Part` construction changed

```python
# 0.2.x — required wrapping in TextPart
from a2a.types import Part, TextPart
parts = [Part(root=TextPart(text=item["content"]))]

# 1.0.x — Part is a flat proto message; set the field directly
from a2a.types import Part
parts = [Part(text=item["content"])]
```

### 3g. `ServerError` removed

The `ServerError` wrapper class is gone. Raise the underlying `A2AError` subclass directly. The framework catches any exception from `execute()` and transitions the task to an error state.

```python
# 0.2.x
from a2a.utils.errors import ServerError
raise ServerError(error=InternalError()) from e

# 1.0.x
from a2a.types import InternalError
raise InternalError() from e
```

---

## 4. Client-Side Changes (Host Agent)

### 4a. `A2AClient` removed → `ClientFactory` / `create_client`

`A2AClient` is gone. The replacement is a transport-aware `ClientFactory` that inspects the `AgentCard`'s `supported_interfaces` to select the right protocol.

```python
# 0.2.x
from a2a.client import A2AClient
self.agent_client = A2AClient(self._httpx_client, agent_card, url=agent_url)

# 1.0.x
from a2a.client import ClientFactory
from a2a.client.client import ClientConfig
factory = ClientFactory(ClientConfig(httpx_client=self._httpx_client))
self.agent_client = factory.create(agent_card)
```

The factory reads the protocol binding and URL from `agent_card.supported_interfaces`, so the explicit `url` parameter is no longer needed.

### 4b. `send_message` returns `AsyncIterator[StreamResponse]` — consume all events correctly

`SendMessageResponse`, `SendMessageSuccessResponse`, and `MessageSendParams` are all gone. `send_message` is now an **async generator** that yields `StreamResponse` events as they arrive (streaming-first design).

```python
# 0.2.x — single awaitable returning a discriminated union
from a2a.types import MessageSendParams, SendMessageRequest, SendMessageResponse, SendMessageSuccessResponse, Task

message_request = SendMessageRequest(
    id=message_id,
    params=MessageSendParams.model_validate(payload),
)
send_response: SendMessageResponse = await client.send_message(message_request)
if isinstance(send_response.root, SendMessageSuccessResponse) and isinstance(send_response.root.result, Task):
    task = send_response.root.result

# 1.0.x — build request from proto types; iterate the stream
from a2a.types import Message, Part, Role, SendMessageRequest, StreamResponse, Task

message = Message(
    role=Role.ROLE_USER,
    parts=[Part(text=task_text)],
    message_id=message_id,
    context_id=context_id,
)
message_request = SendMessageRequest(message=message)

# Streaming sends: task → status_update(working) × N → artifact_update → status_update(COMPLETED)
# Do NOT blindly keep the last event — that is always status_update with no artifact.
# Prefer artifact_update (has the result content) > task > status_update.
last_task = last_artifact = last_status = None
async for sr in client.send_message(message_request):
    pt = sr.WhichOneof("payload")
    if pt == "task":
        last_task = sr
    elif pt == "artifact_update":
        last_artifact = sr          # ← this has the actual response text
    elif pt in ("status_update", "message"):
        last_status = sr

final_response = last_artifact or last_task or last_status
```

**Critical pitfall:** Naively keeping the last `StreamResponse` always yields the terminal `status_update(COMPLETED)` which carries no artifact content. You must track `artifact_update` events separately and prefer them over status events.

### 4c. `AgentCardResolutionError` replaces `httpx.ConnectError`

`A2ACardResolver.get_agent_card()` now wraps all network and parsing errors in `AgentCardResolutionError` instead of propagating raw `httpx` exceptions.

```python
# 0.2.x
except httpx.ConnectError as e:
    print(f"Failed: {e}")

# 1.0.x
from a2a.client import AgentCardResolutionError
except AgentCardResolutionError as e:
    print(f"Failed: {e}")
```

### 4d. `Message` and `Role` construction

`Message.role` is now a protobuf enum (`Role.ROLE_USER`, `Role.ROLE_AGENT`) instead of a string.

```python
# 0.2.x (payload dict approach)
payload = {
    "message": {
        "role": "user",
        "parts": [{"type": "text", "text": task}],
        "messageId": message_id,
        "contextId": context_id,
    }
}

# 1.0.x (proto constructors)
from a2a.types import Message, Part, Role
Message(
    role=Role.ROLE_USER,
    parts=[Part(text=task)],
    message_id=message_id,
    context_id=context_id,
)
```

---

## 5. Impact Summary

| Area | Risk | Notes |
|---|---|---|
| Wire protocol | **None** | A2A JSON-RPC protocol itself is unchanged; agents talk the same language |
| Agent card JSON | Low | 1.0.x `A2ACardResolver` includes backward-compat shims that convert old `url` / `preferredTransport` JSON fields into the new `supportedInterfaces` structure, so old card JSON from 0.3.x agents is still readable |
| Streaming behaviour | Low | `send_message` is now always an async iterator; non-streaming agents still return a single `StreamResponse` wrapping the `Task` |
| Error propagation | Low | `ServerError` wrapper removed; unhandled exceptions from `execute()` are caught by the framework — same runtime behaviour |
| Type safety | Medium | Switching from Pydantic to protobuf removes runtime field validation on construction (protobuf silently ignores unknown fields). The API surface is smaller and more explicit |
| Performance | Positive | Protobuf serialisation is significantly faster than Pydantic JSON round-trips for large messages |

---

## 6. Files Changed

| File | What changed |
|---|---|
| `application_agent/pyproject.toml` | SDK version bump; added `starlette` dependency |
| `host_agent_langgraph/pyproject.toml` | SDK version bump |
| `application_agent/app/__main__.py` | `AgentCard` → `supported_interfaces`; `A2AStarletteApplication` → `create_agent_card_routes` + `create_jsonrpc_routes` + `Starlette`; `DefaultRequestHandler` → `LegacyRequestHandler` (compatible with TaskUpdater flow); `agent_card=` param added |
| `application_agent/app/agent_executor.py` | `Part(root=TextPart(...))` → `Part(text=...)`; `TaskState.working/input_required` → `TASK_STATE_*`; `update_status(final=True)` → `requires_input()`; `ServerError` → `InternalError` |
| `host_agent_langgraph/host/remote_agent_connection.py` | `A2AClient` → `ClientFactory`; `send_message` → async iteration over `StreamResponse`; `p.root.text` → `p.text` with `WhichOneof` check |
| `host_agent_langgraph/host/agent.py` | `MessageSendParams` → proto `Message`; `SendMessageResponse` → `StreamResponse` iterator; `AgentCardResolutionError` replaces `httpx.ConnectError`; `p.root.text` → proto access |
