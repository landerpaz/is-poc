import logging
import os
import sys

import uvicorn
from a2a.server.request_handlers import LegacyRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from app.agent import ApplicationAgent
from app.agent_executor import ApplicationAgentExecutor
from dotenv import load_dotenv
from starlette.applications import Starlette

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingAPIKeyError(Exception):
    """Raised when GOOGLE_API_KEY is not set."""


def main():
    """Starts the Application Agent server on port 10005."""
    host = "localhost"
    port = 10005
    try:
        if not os.getenv("GOOGLE_API_KEY"):
            raise MissingAPIKeyError("GOOGLE_API_KEY environment variable not set.")

        capabilities = AgentCapabilities(streaming=True)

        skills = [
            AgentSkill(
                id="get_applications_by_owner",
                name="Get Applications by Owner",
                description=(
                    "Returns all applications owned by a given user. "
                    "Input: owner user ID. "
                    "Output: application name, application ID, and description for each owned app."
                ),
                tags=["applications", "owner", "list"],
                examples=["List all applications owned by user-alice."],
            ),
            AgentSkill(
                id="get_application_description",
                name="Get Application Description",
                description=(
                    "Returns the description of a specific application. "
                    "Input: application ID or application name. "
                    "Output: application description."
                ),
                tags=["applications", "description", "lookup"],
                examples=["What does the BillingService application do?", "Get description for app-003."],
            ),
            AgentSkill(
                id="update_application_description",
                name="Update Application Description",
                description=(
                    "Updates the description of a specific application. "
                    "Input: application ID and new description text. "
                    "Output: success or failure message."
                ),
                tags=["applications", "description", "update"],
                examples=["Update the description of app-002 to 'Manages stock levels in real time.'"],
            ),
        ]

        agent_card = AgentCard(
            name="Application Agent",
            description=(
                "Manages a registry of software applications. "
                "Can list applications by owner, retrieve descriptions, and update descriptions."
            ),
            supported_interfaces=[
                AgentInterface(
                    url=f"http://{host}:{port}/",
                    protocol_binding=TransportProtocol.JSONRPC,
                    protocol_version=PROTOCOL_VERSION_CURRENT,
                )
            ],
            version="1.0.0",
            default_input_modes=ApplicationAgent.SUPPORTED_CONTENT_TYPES,
            default_output_modes=ApplicationAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=skills,
        )

        request_handler = LegacyRequestHandler(
            agent_executor=ApplicationAgentExecutor(),
            task_store=InMemoryTaskStore(),
            agent_card=agent_card,
        )

        routes = create_agent_card_routes(agent_card) + create_jsonrpc_routes(
            request_handler, rpc_url="/"
        )
        app = Starlette(routes=routes)

        logger.info(f"Starting Application Agent on http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)

    except MissingAPIKeyError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An error occurred during server startup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
