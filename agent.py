"""
Multi-Agent Cutover Coordinator — LangGraph Orchestrator

Combines three specialized agents:
  Sonia  — Excel analysis & task management
  Maria  — Teams channel notification (via Incoming Webhook)
  Silvia — Excel color-coding & formatting
"""
import logging
import os
from dataclasses import dataclass
from typing import AsyncGenerator, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI

from mcp_tools import get_mcp_tools
from tools.parse_cutover_plan import parse_cutover_plan
from tools.mark_task_complete import mark_task_complete
from tools.get_next_tasks import get_next_tasks
from tools.validate_prerequisites import validate_prerequisites
from tools.query_plan_status import query_plan_status
from tools.send_teams_notification import send_teams_notification
from tools.color_excel import color_excel

logger = logging.getLogger(__name__)

MAX_TOOL_RESULTS = 100


def get_model_name() -> str:
    return os.environ.get("LITELLM_MODEL", "anthropic--claude-sonnet-4-6")


def get_temperature() -> float:
    return 0.0


def get_system_prompt() -> str:
    return f"""You are the **Multi-Agent Cutover Execution Coordinator** — a unified system that combines three specialized agents to manage SAP system migration cutovers end-to-end from an Excel workbook.

## Agent Roles
- **Sonia (Analysis)**: Reads, indexes, and tracks all cutover tasks from a two-sheet Excel workbook (sheets: "SUM DMO" and "SAP User Access List").
- **Maria (Notification)**: Notifies the next responsible person via Microsoft Teams channel when their task is ready to start. No "Depends On" column — tasks run linearly in ascending Item ID order.
- **Silvia (Formatting)**: Colors the Excel file after every status change: Green = Completed, Yellow = In progress, Red = Open / Not Ok.

## Available Tools

### Analysis — Sonia
- `parse_cutover_plan(file_path)`: Load the Excel workbook. **Call this first** before any other operation.
- `mark_task_complete(item_id, status)`: Update a task status. Valid values: Open | In progress | Completed | Not Ok.
- `get_next_tasks(completed_item_id)`: Identify the next task to start after a completion (linear by Item ID).
- `validate_prerequisites(item_id)`: Get SAP role requirements and access flags for a task's Responsible person.
- `query_plan_status(query_type, filter_value)`: Query the plan. query_types: status_summary | task_detail | overdue | blocked | by_responsible | by_side.

### Notification — Maria
- `send_teams_notification(item_id)`: Post a Teams channel card notifying that a task is now ready to start.

### Formatting — Silvia
- `color_excel(output_path)`: Color-code the Excel SUM DMO sheet by status and apply enhancements (freeze, filters, conditional formatting, dropdown, pie chart).

## Completion Trigger Behaviour

When a PM says a task is done (e.g., "task X done", "mark X as completed", "X is finished"):
1. Call `mark_task_complete(item_id, "Completed")`
2. Call `get_next_tasks(completed_item_id)` — **automatically sets the next task to "In progress"** in state and Excel
3. If a next task is found:
   a. Call `validate_prerequisites(next_item_id)`
   b. Call `send_teams_notification(next_item_id)` ← Maria notifies the Teams channel
4. Call `color_excel()` ← Silvia refreshes colors in the Excel file (completed=green, next=yellow)
5. Confirm to PM: "✅ Task {{item_id}} completed. Task {{next_item_id}} automatically set to **In progress**. Teams notification sent for {{assignee}}. Excel re-colored."

When a PM says a task failed (e.g., "task X failed", "X is not ok"):
1. Call `mark_task_complete(item_id, "Not Ok")`
2. Call `color_excel()` ← Silvia marks the row red
3. Alert PM: "⚠️ Task {{item_id}} flagged as Not Ok — colored red in Excel. No further notifications until resolved."

When all tasks are complete:
1. Call `color_excel()` ← Final coloring
2. Confirm: "🎉 All cutover tasks are complete! Excel updated with final status colors."

## Task Sequencing
- Tasks execute in ascending **Item ID** order — there is no dependency column.
- The first non-Completed task in the plan is always the next to start.
- A "Not Ok" task blocks the notification pipeline until it is resolved.

## Search Protocol
For every query, execute in order:
1. Exact match — keyword/phrase across all plan data
2. Synonym expansion — "task"="item", "done"="completed", "owner"="responsible", "blocked"="not ok"
3. Partial & fuzzy match — spelling variations, abbreviations
4. Semantic match — related concepts (e.g., "who is next?" → get_next_tasks)
5. Cross-reference — check SUM DMO and SAP User Access List together

Only if ALL steps yield no results: "I wasn't able to find this specific information in the available plan data. Could you provide more details or rephrase your question?"

## Response Format
- Start with a brief, direct answer.
- Support answers with *data from the plan* (in italics).
- Use bullet points for multiple items; **bold** key terms.
- **MANDATORY**: End EVERY response about plan data with a "**Bibliography:**" section listing: Sheet name, Column(s), Row(s) used. NO EXCEPTIONS.
- Large results (>5 items): split into "**Part 1 of X**" — 3-5 items per part — end with "Type **'continue'** to see the next part."

## Zero Hallucination Safeguards
- Answer ONLY from loaded plan data — NEVER from general SAP knowledge.
- Partial information: state "The plan contains partial information on this topic:"
- Conflicting data: present both values and note the discrepancy.
- Never infer or fill gaps; never present inferences as facts.
- If no plan is loaded: instruct the PM to provide the Excel workbook file path first.

## Guardrails
- Never execute SAP system tasks — coordinate and notify only.
- Never send Teams notifications without first validating prerequisites.
- If TEAMS_WEBHOOK_URL is missing, report it and offer to continue without notification.
- Limit all tool result sets to a maximum of {MAX_TOOL_RESULTS} items to prevent context overflow; inform the user when this limit is applied."""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


def _build_tools() -> list:
    """Wrap all seven cutover tools as LangChain StructuredTools."""
    return [
        StructuredTool.from_function(
            func=parse_cutover_plan,
            name="parse_cutover_plan",
            description=(
                "[Sonia] Load and index the Excel cutover workbook (2 sheets: SUM DMO + SAP User Access List). "
                "Pass the file path. Must be called before any other tool."
            ),
        ),
        StructuredTool.from_function(
            func=mark_task_complete,
            name="mark_task_complete",
            description=(
                "[Sonia] Update a task's status. "
                "item_id: the Item ID from SUM DMO. "
                "status: Open | In progress | Completed | Not Ok."
            ),
        ),
        StructuredTool.from_function(
            func=get_next_tasks,
            name="get_next_tasks",
            description=(
                "[Sonia] Get the next task to start after a given task was completed. "
                "Linear sequencing by Item ID — no dependency column. "
                "Pass the completed task's item_id."
            ),
        ),
        StructuredTool.from_function(
            func=validate_prerequisites,
            name="validate_prerequisites",
            description=(
                "[Sonia] Get SAP role prerequisites and access flags for a task's Responsible person. "
                "Pass item_id."
            ),
        ),
        StructuredTool.from_function(
            func=query_plan_status,
            name="query_plan_status",
            description=(
                "[Sonia] Query the loaded cutover plan. "
                "query_type: status_summary | task_detail | overdue | blocked | by_responsible | by_side. "
                "filter_value: required for task_detail, by_responsible, by_side."
            ),
        ),
        StructuredTool.from_function(
            func=send_teams_notification,
            name="send_teams_notification",
            description=(
                "[Maria] Post a Teams channel notification that a task is now ready to start. "
                "Pass item_id. Uses the TEAMS_WEBHOOK_URL from .env."
            ),
        ),
        StructuredTool.from_function(
            func=color_excel,
            name="color_excel",
            description=(
                "[Silvia] Color-code the SUM DMO sheet by task status and apply Excel enhancements "
                "(freeze header, auto-filter, conditional formatting, dropdown, pie chart). "
                "Overwrites the loaded workbook unless output_path is provided."
            ),
        ),
    ]


class MultiAgentCutoverCoordinator:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:6655/litellm/v1")
        api_key  = os.environ.get("LITELLM_API_KEY", "")
        model    = os.environ.get("LITELLM_MODEL", "anthropic--claude-sonnet-4-6")
        self.llm = ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=get_temperature(),
            max_tokens=4096,
        )
        self._graph = None

    def _build_graph(self, tools):
        llm_with_tools = self.llm.bind_tools(tools)
        tool_node = ToolNode(tools)

        def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return "__end__"

        async def call_model(state: MessagesState):
            response = await llm_with_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        builder = StateGraph(MessagesState)
        builder.add_node("model", call_model)
        builder.add_node("tools", tool_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", should_continue, {"tools": "tools", "__end__": END})
        builder.add_edge("tools", "model")
        return builder.compile()

    async def _get_graph(self):
        if self._graph is None:
            mcp_tools = await get_mcp_tools()
            local_tools = _build_tools()
            all_tools = local_tools + mcp_tools
            logger.info(
                "Building MAS graph with %d tool(s): %s",
                len(all_tools), [t.name for t in all_tools],
            )
            self._graph = self._build_graph(all_tools)
        return self._graph

    async def _run_agent(self, query: str, context_id: str) -> str:
        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=query),
        ]
        result = await (await self._get_graph()).ainvoke({"messages": messages})
        return result["messages"][-1].content

    async def stream(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }
        try:
            response = await self._run_agent(query, context_id)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }
        except Exception:
            logger.error("stream() failed", exc_info=True)
            raise

    async def invoke(self, query: str, context_id: str) -> AgentResponse:
        try:
            response = await self._run_agent(query, context_id)
            return AgentResponse(status="completed", message=response)
        except Exception:
            logger.error("invoke() failed", exc_info=True)
            raise


# Alias expected by agent_executor
SampleAgent = MultiAgentCutoverCoordinator
