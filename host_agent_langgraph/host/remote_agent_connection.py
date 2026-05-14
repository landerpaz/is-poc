from typing import Callable

import httpx
from a2a.client import A2AClient
from a2a.types import (
    AgentCard,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
)
from dotenv import load_dotenv

from ._step import step

load_dotenv()

TaskCallbackArg = Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
TaskUpdateCallback = Callable[[TaskCallbackArg, AgentCard], Task]


class RemoteAgentConnections:
    """A class to hold the connections to the remote agents."""

    def __init__(self, agent_card: AgentCard, agent_url: str):
        print(f"[Step {step():>3}] >> ENTER RemoteAgentConnections.__init__(agent={agent_card.name}, url={agent_url})")
        self._httpx_client = httpx.AsyncClient(timeout=30)
        self.agent_client = A2AClient(self._httpx_client, agent_card, url=agent_url)
        self.card = agent_card
        self.conversation_name = None
        self.conversation = None
        self.pending_tasks = set()
        print(f"[Step {step():>3}] << EXIT  RemoteAgentConnections.__init__ → connection ready for {agent_card.name}")

    def get_agent(self) -> AgentCard:
        print(f"[Step {step():>3}] >> ENTER RemoteAgentConnections.get_agent")
        result = self.card
        print(f"[Step {step():>3}] << EXIT  RemoteAgentConnections.get_agent → {result.name}")
        return result

    async def send_message(
        self, message_request: SendMessageRequest
    ) -> SendMessageResponse:
        print(f"[Step {step():>3}] >> ENTER RemoteAgentConnections.send_message(id={message_request.id})")
        msg = message_request.params.message
        text_parts = [
            p.root.text
            for p in (msg.parts or [])
            if hasattr(p.root, "text")
        ]
        print(f"[Step {step():>3}] >> Sending message to {self.card.name}")
        print(
            f"  ┌─ To      : {self.card.name}\n"
            f"  ├─ Role    : {msg.role}\n"
            f"  ├─ Task ID : {msg.task_id}\n"
            f"  ├─ Ctx ID  : {msg.context_id}\n"
            f"  └─ Message : {' | '.join(text_parts) or '(no text parts)'}"
        )
        result = await self.agent_client.send_message(message_request)
        print(f"[Step {step():>3}] << EXIT  RemoteAgentConnections.send_message → response received")
        self._log_response(result)
        return result

    def _log_response(self, result: SendMessageResponse) -> None:
        if isinstance(result.root, SendMessageSuccessResponse) and isinstance(result.root.result, Task):
            task = result.root.result
            status_text = " | ".join(
                p.root.text
                for p in (task.status.message.parts or [])
                if hasattr(p.root, "text")
            ) if task.status.message else ""
            artifact_texts = [
                p.root.text
                for artifact in (task.artifacts or [])
                for p in (artifact.parts or [])
                if hasattr(p.root, "text")
            ]
            print(
                f"  ┌─ From     : {self.card.name}\n"
                f"  ├─ Task ID  : {task.id}\n"
                f"  ├─ State    : {task.status.state}\n"
                f"  ├─ Status   : {status_text or '(none)'}\n"
                f"  └─ Artifacts: {' | '.join(artifact_texts) or '(none)'}"
            )
        else:
            print(f"  └─ Response : {result.root}")
