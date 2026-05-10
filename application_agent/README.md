# Application Agent

An A2A-compatible agent built on LangGraph that manages a registry of software applications. It handles incoming requests from a host agent, queries or updates the in-memory application store, and returns structured responses over the A2A protocol.

---

## Overview

```
Host Agent (port 10001)
      │
      │  A2A JSON-RPC  POST /
      ▼
Application Agent (LangGraph, port 10005)
      │
      ├── get_applications_by_owner   — list apps by owner user ID
      ├── get_application_description — look up description by app ID or name
      └── update_application_description — update description by app ID
```

The agent uses `gemini-2.5-flash` via LangGraph's `create_react_agent` with a structured `ResponseFormat` output schema so every response is explicitly tagged as `completed`, `input_required`, or `error`.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.13 |
| `uv` | latest |
| `GOOGLE_API_KEY` | set in `.env` at project root |

---

## Setup

```bash
cd application_agent
uv venv --python 3.13
source .venv/bin/activate
```

---

## Running

```bash
# Option A
uv run --active app/__main__.py

# Option B
uv run --active .
```

The server starts on **http://localhost:10005**.  
The AgentCard is served automatically at **http://localhost:10005/.well-known/agent.json**.

> Start this agent **before** the host agent so its AgentCard is discoverable at host startup.

---

## File Structure

```
application_agent/
├── README.md
├── pyproject.toml          # project metadata and dependencies
├── .python-version         # pins Python 3.13
├── __init__.py
├── __main__.py             # delegates to app/__main__.py for `uv run --active .`
└── app/
    ├── __init__.py
    ├── agent.py            # data model, tools, ApplicationAgent class
    ├── agent_executor.py   # A2A AgentExecutor bridge with request/response logging
    └── __main__.py         # AgentCard, server wiring, uvicorn startup
```

---

## Data Model

All data lives in memory and resets on restart.

```python
@dataclass
class Application:
    application_name: str        # e.g. "BillingService"
    application_id: str          # e.g. "app-001"
    application_description: str # human-readable description
    owner_user_id: str           # e.g. "user-alice"
```

### Sample Data

| ID      | Name                  | Owner       |
|---------|-----------------------|-------------|
| app-001 | BillingService        | user-alice  |
| app-002 | InventoryManager      | user-bob    |
| app-003 | NotificationHub       | user-alice  |
| app-004 | ReportingDashboard    | user-carol  |
| app-005 | AuthService           | user-bob    |

---

## Skills

### 1. Get Applications by Owner

Returns all applications owned by a given user.

- **Input:** `owner_user_id` — the user ID of the owner (e.g. `user-alice`)
- **Output:** Application name, ID, and description for each owned application

**Example request to host:**
```
List all applications owned by user-alice.
```

**Example response:**
```
Applications owned by 'user-alice':
- Name: BillingService | ID: app-001 | Description: Handles all billing and payment processing for customers.
- Name: NotificationHub | ID: app-003 | Description: Sends email, SMS, and push notifications to users.
```

---

### 2. Get Application Description

Returns the description of a specific application looked up by its ID or name.

- **Input:** `identifier` — application ID (e.g. `app-003`) or application name (e.g. `NotificationHub`)
- **Output:** Application name, ID, and description

**Example request to host:**
```
What does the BillingService application do?
Get the description of app-003.
```

**Example response:**
```
Application: NotificationHub (ID: app-003)
Description: Sends email, SMS, and push notifications to users.
```

---

### 3. Update Application Description

Updates the description of a specific application.

- **Input:** `application_id` — the ID of the application to update (e.g. `app-002`), `new_description` — the replacement text
- **Output:** Success or failure message

**Example request to host:**
```
Update the description of app-002 to "Manages stock levels in real time across all warehouses."
```

**Example response:**
```
Success: description for 'InventoryManager' (ID: app-002) has been updated to:
"Manages stock levels in real time across all warehouses."
```

---

## Response States

| State            | When used |
|------------------|-----------|
| `completed`      | Tool ran successfully and result is ready |
| `input_required` | A required parameter (owner ID, app ID, new description) was not provided |
| `error`          | Tool returned a failure (e.g. app ID not found) |

---

## Logs

The agent prints structured logs for every request and response:

```
INFO:app.agent_executor:┌─ REQUEST  task_id=abc123  ctx=def456
                        └─ Query   : Get all applications owned by user-carol
INFO:app.agent_executor:  ↳ [working] Looking up application data...
INFO:app.agent_executor:  ↳ [working] Processing result...
INFO:app.agent_executor:┌─ RESPONSE task_id=abc123
                        ├─ State   : completed
                        └─ Result  : Applications owned by 'user-carol': ...
```

---

## Adding to the Host Agent

The host agent discovers agents at startup from the URL list in  
`host_agent_langgraph/host/__main__.py`. `http://localhost:10005` is already included:

```python
domain_agent_urls = [
    "http://localhost:10005",  # Application Agent  ← this one
]
```

Restart the host agent after starting the Application Agent for it to appear in the available-agents list.
