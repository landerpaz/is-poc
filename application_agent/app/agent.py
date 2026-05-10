from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

memory = MemorySaver()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Application:
    application_name: str
    application_id: str
    application_description: str
    owner_user_id: str


APPLICATIONS: list[Application] = [
    Application(
        application_name="BillingService",
        application_id="app-001",
        application_description="Handles all billing and payment processing for customers.",
        owner_user_id="user-alice",
    ),
    Application(
        application_name="InventoryManager",
        application_id="app-002",
        application_description="Tracks product inventory levels across warehouses.",
        owner_user_id="user-bob",
    ),
    Application(
        application_name="NotificationHub",
        application_id="app-003",
        application_description="Sends email, SMS, and push notifications to users.",
        owner_user_id="user-alice",
    ),
    Application(
        application_name="ReportingDashboard",
        application_id="app-004",
        application_description="Generates business intelligence reports and visualisations.",
        owner_user_id="user-carol",
    ),
    Application(
        application_name="AuthService",
        application_id="app-005",
        application_description="Manages user authentication and authorisation.",
        owner_user_id="user-bob",
    ),
]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class GetApplicationsByOwnerInput(BaseModel):
    owner_user_id: str = Field(..., description="The user ID of the owner whose applications should be listed.")


@tool(args_schema=GetApplicationsByOwnerInput)
def get_applications_by_owner(owner_user_id: str) -> str:
    """Returns all applications owned by the given user, including their name, ID, and description."""
    owned = [a for a in APPLICATIONS if a.owner_user_id == owner_user_id]
    if not owned:
        return f"No applications found for owner '{owner_user_id}'."
    lines = [
        f"- Name: {a.application_name} | ID: {a.application_id} | Description: {a.application_description}"
        for a in owned
    ]
    return f"Applications owned by '{owner_user_id}':\n" + "\n".join(lines)


class GetApplicationDescriptionInput(BaseModel):
    identifier: str = Field(
        ...,
        description="The application ID (e.g. 'app-001') or application name (e.g. 'BillingService') to look up.",
    )


@tool(args_schema=GetApplicationDescriptionInput)
def get_application_description(identifier: str) -> str:
    """Returns the description of an application looked up by its ID or name."""
    match = next(
        (a for a in APPLICATIONS if a.application_id == identifier or a.application_name == identifier),
        None,
    )
    if match is None:
        return f"No application found with ID or name '{identifier}'."
    return (
        f"Application: {match.application_name} (ID: {match.application_id})\n"
        f"Description: {match.application_description}"
    )


class UpdateApplicationDescriptionInput(BaseModel):
    application_id: str = Field(..., description="The ID of the application to update (e.g. 'app-001').")
    new_description: str = Field(..., description="The new description to set for the application.")


@tool(args_schema=UpdateApplicationDescriptionInput)
def update_application_description(application_id: str, new_description: str) -> str:
    """Updates the description of an application identified by its ID. Returns a success or failure message."""
    match = next((a for a in APPLICATIONS if a.application_id == application_id), None)
    if match is None:
        return f"Failed: no application found with ID '{application_id}'."
    match.application_description = new_description
    return (
        f"Success: description for '{match.application_name}' (ID: {application_id}) "
        f"has been updated to: \"{new_description}\""
    )


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class ResponseFormat(BaseModel):
    """Structured response the LLM must always produce."""

    status: Literal["input_required", "completed", "error"] = "input_required"
    message: str


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ApplicationAgent:
    """LangGraph-based agent for application management queries."""

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    SYSTEM_INSTRUCTION = (
        "You are an application management assistant. "
        "You have access to a registry of software applications, each with a name, ID, description, and owner. "
        "Use the provided tools to answer questions and perform updates. Never guess or fabricate data — "
        "always call the appropriate tool. "
        "Available tools and when to use them:\n"
        "- get_applications_by_owner: call this when the user wants to list all applications belonging to a specific owner (user ID).\n"
        "- get_application_description: call this when the user wants the description of a specific application by its ID or name.\n"
        "- update_application_description: call this when the user wants to change or update the description of an application by its ID.\n"
        "Response status rules (apply exactly one per response):\n"
        "- Set status to 'completed' as soon as you have called the relevant tool and are reporting the result — your job ends there.\n"
        "- Set status to 'input_required' ONLY when the user has not provided a required parameter (e.g. missing owner ID, application ID, or new description) and you cannot call the tool yet.\n"
        "- Set status to 'error' only if a tool returns a failure or an unexpected error prevents you from answering."
    )

    def __init__(self):
        self.model = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
        self.tools = [
            get_applications_by_owner,
            get_application_description,
            update_application_description,
        ]
        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=ResponseFormat,
        )

    def invoke(self, query: str, context_id: str) -> dict[str, Any]:
        config: RunnableConfig = {"configurable": {"thread_id": context_id}}
        self.graph.invoke({"messages": [("user", query)]}, config)
        return self.get_agent_response(config)

    async def stream(self, query: str, context_id: str) -> AsyncIterable[dict[str, Any]]:
        inputs = {"messages": [("user", query)]}
        config: RunnableConfig = {"configurable": {"thread_id": context_id}}

        async for item in self.graph.astream(inputs, config, stream_mode="values"):
            message = item["messages"][-1]
            if isinstance(message, AIMessage) and message.tool_calls:
                yield {
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": "Looking up application data...",
                }
            elif isinstance(message, ToolMessage):
                yield {
                    "is_task_complete": False,
                    "require_user_input": False,
                    "content": "Processing result...",
                }

        yield self.get_agent_response(config)

    def get_agent_response(self, config: RunnableConfig) -> dict[str, Any]:
        current_state = self.graph.get_state(config)
        structured_response = current_state.values.get("structured_response")
        if structured_response and isinstance(structured_response, ResponseFormat):
            if structured_response.status == "completed":
                return {
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": structured_response.message,
                }
            if structured_response.status == "input_required":
                return {
                    "is_task_complete": False,
                    "require_user_input": True,
                    "content": structured_response.message,
                }
            if structured_response.status == "error":
                return {
                    "is_task_complete": False,
                    "require_user_input": True,
                    "content": structured_response.message,
                }

        return {
            "is_task_complete": False,
            "require_user_input": True,
            "content": "Unable to process your request at the moment. Please try again.",
        }
