import httpx
from a2a.client import ClientFactory
from a2a.client.client import ClientConfig
from a2a.types import (
    AgentCard,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
)
from dotenv import load_dotenv

from ._step import step

load_dotenv()


class RemoteAgentConnections:
    """A class to hold the connections to the remote agents."""

    def __init__(self, agent_card: AgentCard, agent_url: str):
        print(f"[Step {step():>3}] >> ENTER RemoteAgentConnections.__init__(agent={agent_card.name}, url={agent_url})")
        self._httpx_client = httpx.AsyncClient(timeout=30)
        factory = ClientFactory(ClientConfig(httpx_client=self._httpx_client))
        self.agent_client = factory.create(agent_card)
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
    ) -> StreamResponse | None:
        print(f"[Step {step():>3}] >> ENTER RemoteAgentConnections.send_message")
        msg = message_request.message
        text_parts = [
            p.text
            for p in msg.parts
            if p.WhichOneof("content") == "text"
        ]
        print(f"[Step {step():>3}] >> Sending message to {self.card.name}")
        print(
            f"  ┌─ To      : {self.card.name}\n"
            f"  ├─ Role    : {msg.role}\n"
            f"  ├─ Task ID : {msg.task_id}\n"
            f"  ├─ Ctx ID  : {msg.context_id}\n"
            f"  └─ Message : {' | '.join(text_parts) or '(no text parts)'}"
        )

        last_task: StreamResponse | None = None
        last_artifact: StreamResponse | None = None
        last_status: StreamResponse | None = None

        async for stream_response in self.agent_client.send_message(message_request):
            payload_type = stream_response.WhichOneof("payload")
            if payload_type == "task":
                last_task = stream_response
            elif payload_type == "artifact_update":
                last_artifact = stream_response
            elif payload_type in ("status_update", "message"):
                last_status = stream_response

        # Prefer artifact content (has the result) > full task > status-only
        final_response = last_artifact or last_task or last_status
        print(f"[Step {step():>3}] << EXIT  RemoteAgentConnections.send_message → response received")
        self._log_response(final_response)
        return final_response

    def _log_response(self, result: StreamResponse | None) -> None:
        if result is None:
            print("  └─ Response : (none)")
            return

        payload_type = result.WhichOneof("payload")
        if payload_type == "task":
            task = result.task
            status_text = ""
            if task.status.HasField("message"):
                status_text = " | ".join(
                    p.text
                    for p in task.status.message.parts
                    if p.WhichOneof("content") == "text"
                )
            artifact_texts = [
                p.text
                for artifact in task.artifacts
                for p in artifact.parts
                if p.WhichOneof("content") == "text"
            ]
            print(
                f"  ┌─ From     : {self.card.name}\n"
                f"  ├─ Task ID  : {task.id}\n"
                f"  ├─ State    : {task.status.state}\n"
                f"  ├─ Status   : {status_text or '(none)'}\n"
                f"  └─ Artifacts: {' | '.join(artifact_texts) or '(none)'}"
            )
        else:
            print(f"  └─ Response : {result}")
