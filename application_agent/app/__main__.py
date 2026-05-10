import logging
import os
import sys

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from app.agent import ApplicationAgent
from app.agent_executor import ApplicationAgentExecutor
from dotenv import load_dotenv

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
            url=f"http://{host}:{port}/",
            version="1.0.0",
            defaultInputModes=ApplicationAgent.SUPPORTED_CONTENT_TYPES,
            defaultOutputModes=ApplicationAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=skills,
        )

        request_handler = DefaultRequestHandler(
            agent_executor=ApplicationAgentExecutor(),
            task_store=InMemoryTaskStore(),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler,
        )

        logger.info(f"Starting Application Agent on http://{host}:{port}")
        uvicorn.run(server.build(), host=host, port=port)

    except MissingAPIKeyError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An error occurred during server startup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
