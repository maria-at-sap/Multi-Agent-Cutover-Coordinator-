from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import logging
import os

import click
import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from starlette.responses import HTMLResponse
from starlette.routing import Route

from agent_executor import AgentExecutor

_STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))


@click.command()
@click.option("--host", default=HOST)
@click.option("--port", default=PORT)
def main(host: str, port: int):
    skill = AgentSkill(
        id="mas-cutover-coordinator",
        name="mas-cutover-coordinator",
        description=(
            "Multi-Agent SAP Cutover Coordinator combining three specialized agents: "
            "Sonia (Excel analysis), Maria (Teams notifications), Silvia (Excel formatting). "
            "Tracks tasks linearly by Item ID, notifies via Teams, and auto-colors the workbook."
        ),
        tags=["cutover", "coordinator", "multi-agent", "sap", "teams", "excel"],
        examples=[
            "Load the cutover plan from Cutover Plan Test.xlsx",
            "Mark task 10 as completed",
            "Show me the status summary",
            "What tasks are overdue?",
        ],
    )
    agent_card = AgentCard(
        name="mas-cutover-coordinator",
        description=(
            "Multi-Agent SAP Cutover Coordinator — Sonia analyzes the Excel plan, "
            "Alex sends Teams notifications for the next task, Silvia styles the workbook. Maria orchestrates."
        ),
        url=os.environ.get("AGENT_PUBLIC_URL", f"http://{host}:{port}/"),
        version="1.0.0",
        defaultInputModes=["text", "text/plain"],
        defaultOutputModes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        skills=[skill],
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=DefaultRequestHandler(
            agent_executor=AgentExecutor(),
            task_store=InMemoryTaskStore(),
        ),
    )
    _chat_html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

    async def _chat_ui(request):
        return HTMLResponse(_chat_html)

    app = server.build()
    app.add_route("/chat", _chat_ui, methods=["GET"])

    logger.info("Starting Multi-Agent Cutover Coordinator at http://%s:%d", host, port)
    logger.info("Chat UI: http://%s:%d/chat", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
