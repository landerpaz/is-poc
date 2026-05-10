import json
import uuid
from datetime import datetime
from typing import Any, AsyncIterable, List

import httpx
from a2a.client import A2ACardResolver
from a2a.types import (
    AgentCard,
    MessageSendParams,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
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
from .remote_agent_connection import RemoteAgentConnections

load_dotenv()

_memory = MemorySaver()


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
                except httpx.ConnectError as e:
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
            print(f"[Step {step():>3}] >> ENTER send_message(agent_name={agent_name})")

            if agent_name not in remote_connections:
                print(f"[Step {step():>3}] << EXIT  send_message → error: agent '{agent_name}' not found")
                raise ValueError(f"Agent {agent_name} not found")
            client = remote_connections[agent_name]

            message_id = str(uuid.uuid4())
            # task_id = str(uuid.uuid4())
            context_id = str(uuid.uuid4())

            payload = {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": task}],
                    "messageId": message_id,
                    # "taskId": task_id,
                    "contextId": context_id,
                },
            }

            message_request = SendMessageRequest(
                id=message_id, params=MessageSendParams.model_validate(payload)
            )
            send_response: SendMessageResponse = await client.send_message(message_request)
            print("send_response", send_response)

            if not isinstance(
                send_response.root, SendMessageSuccessResponse
            ) or not isinstance(send_response.root.result, Task):
                print("Received a non-success or non-task response. Cannot proceed.")
                print(f"[Step {step():>3}] << EXIT  send_message → non-task response, aborting")
                return "No response received from the agent."

            task = send_response.root.result

            text_parts = []

            # Primary: artifact parts (completed state)
            for artifact in (task.artifacts or []):
                for p in (artifact.parts or []):
                    if hasattr(p.root, "text"):
                        text_parts.append(p.root.text)

            # Fallback: status message parts (input_required / error state)
            if not text_parts and task.status.message:
                for p in (task.status.message.parts or []):
                    if hasattr(p.root, "text"):
                        text_parts.append(p.root.text)

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

        model = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
        self.graph = create_react_agent(
            model,
            tools=[send_message],
            checkpointer=_memory,
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

    async def stream(self, query: str, session_id: str) -> AsyncIterable[dict[str, Any]]:
        print(f"[Step {step():>3}] >> ENTER stream(session_id={session_id})")
        inputs = {"messages": [("user", query)]}
        config: RunnableConfig = {"configurable": {"thread_id": session_id}}

        async for chunk in self.graph.astream(inputs, config, stream_mode="values"):
            last_message = chunk["messages"][-1]
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                yield {
                    "is_task_complete": False,
                    "content": "The host agent is thinking...",
                }
            elif isinstance(last_message, ToolMessage):
                yield {
                    "is_task_complete": False,
                    "content": "The host agent is thinking...",
                }
            elif isinstance(last_message, AIMessage) and not last_message.tool_calls:
                content = last_message.content
                if isinstance(content, list):
                    content = "\n".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict)
                    )
                print(f"[Step {step():>3}] << EXIT  stream → final response yielded")
                yield {
                    "is_task_complete": True,
                    "content": content,
                }
