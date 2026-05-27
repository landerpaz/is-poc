import json
import re
import uuid
from datetime import datetime
from typing import Any, AsyncIterable, List

import httpx
from a2a.client import A2ACardResolver, AgentCardResolutionError
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
)
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from ._step import step
from .llm_logger import LLMLogger
from .remote_agent_connection import RemoteAgentConnections
from .validation import PromptInjectionError, sanitize

load_dotenv()

_memory = MemorySaver()

# Operations that mutate state and require human confirmation before execution
_MUTATING_RE = re.compile(
    r"\b(create|add|insert|register|update|modify|change|edit|set|delete|remove|drop|unregister)\b",
    re.IGNORECASE,
)


def _is_mutating(task: str) -> bool:
    return bool(_MUTATING_RE.search(task))


class HostAgent:
    """The Host agent."""

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        print(f"[Step {step():>3}] >> ENTER HostAgent.__init__")
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}
        self.agents: str = ""
        self.graph: Any = None
        print(f"[Step {step():>3}] << EXIT  HostAgent.__init__")

    async def _async_init_components(self, remote_agent_addresses: List[str]):
        print(f"[Step {step():>3}] >> ENTER _async_init_components(addresses={remote_agent_addresses})")
        async with httpx.AsyncClient(timeout=30) as client:
            for address in remote_agent_addresses:
                card_resolver = A2ACardResolver(client, address)
                try:
                    card = await card_resolver.get_agent_card()
                    print(f"Successfully retrieved card from {address}: {card}")
                    remote_connection = RemoteAgentConnections(
                        agent_card=card, agent_url=address
                    )
                    self.remote_agent_connections[card.name] = remote_connection
                    self.cards[card.name] = card
                except AgentCardResolutionError as e:
                    print(f"ERROR: Failed to get agent card from {address}: {e}")
                except Exception as e:
                    print(f"ERROR: Failed to initialize connection for {address}: {e}")

        agent_info = [
            json.dumps({"name": card.name, "description": card.description})
            for card in self.cards.values()
        ]
        print("agent_info:", agent_info)
        self.agents = "\n".join(agent_info) if agent_info else "No domains found"
        print(f"[Step {step():>3}] << EXIT  _async_init_components → {len(self.cards)} agent(s) registered")

    def _build_graph(self):
        print(f"[Step {step():>3}] >> ENTER _build_graph")
        remote_connections = self.remote_agent_connections
        agents_info = self.agents

        @tool
        async def send_message(agent_name: str, task: str) -> str:
            """Sends a task to a remote domain agent to process the request."""
            print(f"[Step {step():>3}] >> ENTER send_message(agent_name={agent_name}, task={task})")

            if agent_name not in remote_connections:
                print(f"[Step {step():>3}] << EXIT  send_message → error: agent '{agent_name}' not found")
                raise ValueError(f"Agent {agent_name} not found")
            client = remote_connections[agent_name]

            message_id = str(uuid.uuid4())
            context_id = str(uuid.uuid4())

            message = Message(
                role=Role.ROLE_USER,
                parts=[Part(text=task)],
                message_id=message_id,
                context_id=context_id,
            )
            message_request = SendMessageRequest(message=message)

            stream_response: StreamResponse | None = await client.send_message(message_request)

            if stream_response is None:
                print("Received no response from domain agent.")
                print(f"[Step {step():>3}] << EXIT  send_message → no response")
                return "No response received from the agent."

            payload_type = stream_response.WhichOneof("payload")
            text_parts = []

            if payload_type == "task":
                # Full task object — extract from artifacts, fallback to status message
                result_task: Task = stream_response.task
                for artifact in result_task.artifacts:
                    for p in artifact.parts:
                        if p.WhichOneof("content") == "text":
                            text_parts.append(p.text)
                if not text_parts and result_task.status.HasField("message"):
                    for p in result_task.status.message.parts:
                        if p.WhichOneof("content") == "text":
                            text_parts.append(p.text)

            elif payload_type == "artifact_update":
                # Streaming artifact event — extract directly from the artifact parts
                artifact = stream_response.artifact_update.artifact
                for p in artifact.parts:
                    if p.WhichOneof("content") == "text":
                        text_parts.append(p.text)

            elif payload_type == "status_update":
                # Terminal status — extract from the status message if present
                status = stream_response.status_update.status
                if status.HasField("message"):
                    for p in status.message.parts:
                        if p.WhichOneof("content") == "text":
                            text_parts.append(p.text)

            else:
                print(f"Unhandled response payload type: {payload_type}")
                print(f"[Step {step():>3}] << EXIT  send_message → unhandled response type")
                return "No response received from the agent."

            result = "\n".join(text_parts) if text_parts else "No response received."
            print(f"[Step {step():>3}] << EXIT  send_message → {len(text_parts)} text part(s) from {agent_name}")
            return result

        system_prompt = f"""
        **Role:** You are the Host Agent — a multi-purpose assistant that can manage software applications. You coordinate with specialised sub-agents to fulfil user requests.

        **Today's Date (YYYY-MM-DD):** {datetime.now().strftime("%Y-%m-%d")}

        <Available Agents>
        {agents_info}
        </Available Agents>

        ---

        ## SECTION 1 — Application Management

        **When the user asks anything about software applications, route the request to "Application Agent" using `send_message`.**

        Supported operations — craft your message to the Application Agent accordingly:

        | User intent | What to ask the Application Agent |
        |---|---|
        | List apps for an owner | "Get all applications owned by <owner-user-id>" |
        | Get an app's description | "Get the description of application <app-id or app-name>" |
        | Update an app's description | "Update the description of application <app-id> to: <new description>" |

        **Application management rules:**
        *   Always forward application requests to "Application Agent" — never answer from memory.
        *   If the user does not provide a required parameter (owner ID, application ID, or new description), ask them for it before calling the agent.
        *   Relay the Application Agent's response back to the user verbatim, formatted for readability.

        ---

        ## General Rules (apply to all requests)

        *   **Tool reliance:** Use tools for all data — never generate responses based on assumptions.
        *   **Readability:** Respond in a concise, easy-to-read format; use bullet points where helpful.
        *   **Routing:** Classify the user's intent first (scheduling vs. application management), then follow the relevant section above.

        ---

        ## SECTION 2 — Other agents will be added later!


        """

        model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", callbacks=[LLMLogger()])
        self.graph = create_react_agent(
            model,
            tools=[send_message],
            checkpointer=_memory,
            interrupt_before=["tools"],
            prompt=system_prompt,
        )
        print(f"[Step {step():>3}] << EXIT  _build_graph → graph ready")

    @classmethod
    async def create(cls, remote_agent_addresses: List[str]):
        print(f"[Step {step():>3}] >> ENTER HostAgent.create(addresses={remote_agent_addresses})")
        instance = cls()
        await instance._async_init_components(remote_agent_addresses)
        instance._build_graph()
        print(f"[Step {step():>3}] << EXIT  HostAgent.create → instance ready")
        return instance

    async def _stream_graph(
        self, inputs: dict | None, config: RunnableConfig
    ) -> AsyncIterable[dict[str, Any]]:
        """
        Run one pass of the LangGraph and yield SSE-compatible chunks.

        With interrupt_before=["tools"] the graph pauses before any tool call.
        After the astream loop finishes we inspect the state:
          - mutating tool call  → yield requires_confirmation event and stop
          - read-only tool call → auto-resume transparently
          - no interrupt        → graph completed normally
        """
        async for chunk in self.graph.astream(inputs, config, stream_mode="values"):
            last_msg = chunk["messages"][-1]
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                print(f"[Step {step():>3}] tool calls pending: {[tc['name'] for tc in last_msg.tool_calls]}")
                yield {"is_task_complete": False, "content": "The host agent is thinking..."}
            elif isinstance(last_msg, ToolMessage):
                print(f"[Step {step():>3}] tool response received")
                yield {"is_task_complete": False, "content": "The host agent is thinking..."}
            elif isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
                content = last_msg.content
                if isinstance(content, list):
                    content = "\n".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                print(f"[Step {step():>3}] << EXIT _stream_graph → final response")
                yield {"is_task_complete": True, "content": content}
                return  # done — no need to check state

        # Loop ended without a final response → graph interrupted before tools
        state = await self.graph.aget_state(config)
        if not state.next:
            return

        last_msg = state.values["messages"][-1]
        if not (isinstance(last_msg, AIMessage) and last_msg.tool_calls):
            return

        mutating_calls = [
            tc for tc in last_msg.tool_calls
            if tc.get("name") == "send_message" and _is_mutating(tc["args"].get("task", ""))
        ]

        if mutating_calls:
            task_desc = mutating_calls[0]["args"].get("task", "")
            print(f"[Step {step():>3}] << PAUSED awaiting confirmation: {task_desc}")
            yield {
                "is_task_complete": False,
                "requires_confirmation": True,
                "pending_task": task_desc,
                "content": (
                    "I need your confirmation before proceeding with this operation:\n\n"
                    f"{task_desc}"
                ),
            }
        else:
            # Read-only tool call — approve automatically and continue
            print(f"[Step {step():>3}] auto-resuming read-only tool call")
            async for item in self._stream_graph(None, config):
                yield item

    async def stream(self, query: str, session_id: str) -> AsyncIterable[dict[str, Any]]:
        print(f"[Step {step():>3}] >> ENTER stream(session_id={session_id})")

        try:
            safe_query = sanitize(query)
        except PromptInjectionError as exc:
            print(f"[Step {step():>3}] << BLOCKED prompt injection: {exc}")
            yield {"is_task_complete": True, "content": "Your message was blocked: possible prompt injection detected."}
            return

        config: RunnableConfig = {"configurable": {"thread_id": session_id}}
        inputs = {"messages": [("user", safe_query)]}

        async for item in self._stream_graph(inputs, config):
            yield item

    async def stream_resume(
        self, session_id: str, approved: bool
    ) -> AsyncIterable[dict[str, Any]]:
        """Resume a graph that was paused waiting for human confirmation."""
        print(f"[Step {step():>3}] >> ENTER stream_resume(session_id={session_id}, approved={approved})")
        config: RunnableConfig = {"configurable": {"thread_id": session_id}}

        if not approved:
            # Inject cancellation ToolMessages so the LLM sees the operation was declined
            state = await self.graph.aget_state(config)
            last_msg = state.values["messages"][-1]
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                rejections = [
                    ToolMessage(
                        content="Operation cancelled by user.",
                        tool_call_id=tc["id"],
                    )
                    for tc in last_msg.tool_calls
                ]
                await self.graph.aupdate_state(config, {"messages": rejections}, as_node="tools")

        async for item in self._stream_graph(None, config):
            yield item
