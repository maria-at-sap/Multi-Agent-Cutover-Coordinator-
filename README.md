# MAS Cutover Orchestrator

A multi-agent AI system for orchestrating SAP system migration cutovers. Three specialized agents collaborate to track tasks, send notifications, and maintain the cutover plan — driven by natural language conversation.

## Overview

The orchestrator manages the full lifecycle of an SAP cutover execution:

1. **Parse** the Excel cutover plan (tasks + SAP user access list)
2. **Track** task completion as the cutover progresses
3. **Notify** the next responsible person via Microsoft Teams when a task is ready
4. **Format** the Excel workbook with live color-coded status indicators

### Agents

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Sonia** | Analysis | Reads the plan, tracks task status, validates SAP prerequisites |
| **Maria** | Notification | Sends Microsoft Teams messages to responsible parties |
| **Silvia** | Formatting | Color-codes the Excel workbook and generates summary charts |

## Architecture

```
main.py          → Uvicorn HTTP server + web chat UI + A2A endpoint
agent.py         → LangGraph orchestrator (routes requests to tools)
agent_executor.py→ A2A SDK agent lifecycle
state.py         → Shared in-memory state (task index, access index, blockers)
tools/           → 7 LangChain StructuredTools (one per agent capability)
```

The LLM backend is a **LiteLLM proxy** (OpenAI-compatible interface). The default model is `claude-sonnet-4-6`.

### Tool Suite

| Tool | Agent | Description |
|------|-------|-------------|
| `parse_cutover_plan` | Sonia | Load and index the Excel workbook |
| `mark_task_complete` | Sonia | Update a task's status |
| `get_next_tasks` | Sonia | Identify the next task by Item ID and set it to "In progress" |
| `validate_prerequisites` | Sonia | Return SAP role requirements for a task's assignee |
| `query_plan_status` | Sonia | Query the plan (summary, detail, overdue, blocked, by responsible, by side) |
| `send_teams_notification` | Maria | Post a Teams MessageCard to the configured webhook |
| `color_excel` | Silvia | Color-code rows by status and apply formatting enhancements |

### Status Color Scheme

| Status | Color |
|--------|-------|
| Completed | Green `#21AD30` |
| In progress | Yellow `#EDE653` |
| Open | Gray `#9AA69A` |
| Not Ok | Red `#E04843` |

A task with status **Not Ok** becomes a blocker and halts the notification pipeline until resolved.

## Prerequisites

- Python 3.10+
- A running **LiteLLM proxy** instance with a Claude model
- A Microsoft Teams **incoming webhook URL**
- The SAP cutover plan in `.xlsx` format (two sheets: task list + user access list)

## Setup

**1. Clone the repository and install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env`:

```env
LITELLM_BASE_URL=http://localhost:6655/litellm/v1
LITELLM_API_KEY=your-api-key
LITELLM_MODEL=anthropic--claude-sonnet-4-6
EXCEL_FILE_PATH=Cutover Plan Test.xlsx
TEAMS_WEBHOOK_URL=https://sap.webhook.office.com/webhookb2/...
HOST=0.0.0.0
PORT=5000
```

**3. Run the server**

```bash
python main.py
```

Open `http://localhost:5000` in your browser to access the chat UI.

## Usage

Interact with the orchestrator via the chat UI using natural language:

```
> Parse the cutover plan
> What tasks are currently in progress?
> Mark item 42 as completed
> What are the prerequisites for item 43?
> Show me all overdue tasks
> Send a Teams notification for item 43
> Color the Excel file and save to output.xlsx
```

After marking a task complete, the orchestrator automatically:
- Identifies the next task by Item ID
- Sets it to "In progress"
- Validates the next assignee's SAP prerequisites
- Sends a Teams notification to the responsible person
- Re-colors the Excel workbook

## Excel Workbook Format

The workbook must contain two sheets:

- **Sheet 1 (Task list)**: Cutover tasks with columns including Item ID, Task Description, Status, Responsible, Start/End dates, Side
- **Sheet 2 (User Access List)**: SAP user roles with columns including Name, System, Authorization details

The orchestrator cross-references both sheets by matching the task's `Responsible` field to the access list `Name` field (case-insensitive).

## Project Structure

```
MAS-orchestrator/
├── .env.example              # Environment variable template
├── agent.py                  # Core LangGraph orchestrator + system prompt
├── agent_executor.py         # A2A SDK executor
├── main.py                   # HTTP server entry point
├── mcp_tools.py              # MCP tool loader (extensibility hook)
├── state.py                  # Shared in-memory state
├── requirements.txt          # Python dependencies
├── static/
│   └── index.html            # Web chat UI
└── tools/
    ├── parse_cutover_plan.py
    ├── mark_task_complete.py
    ├── get_next_tasks.py
    ├── validate_prerequisites.py
    ├── query_plan_status.py
    ├── send_teams_notification.py
    └── color_excel.py
```
