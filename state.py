"""
In-memory agent state for the Multi-Agent Cutover Coordinator.

Shared across all three agents (Sonia / Maria / Silvia) via this module.
State is session-scoped: reload the workbook to reset.
"""
import uuid
from typing import Optional

# Parsed and indexed task plan from SUM DMO sheet (list of task dicts, sorted by Item ID)
cutover_plan: Optional[list] = None

# Task records keyed by Item ID string
task_index: dict = {}

# Access list records keyed by normalised Name (lowercase, stripped)
access_index: dict = {}

# Current Not Ok blocker task ID (if any); halts the notification pipeline
blocked_task_id: Optional[str] = None

# Path to the loaded workbook — used for Excel write-back and coloring
workbook_path: Optional[str] = None

# Unique session identifier
session_id: str = str(uuid.uuid4())


def reset():
    """Reset all state — called when a new workbook is loaded."""
    global cutover_plan, task_index, access_index, blocked_task_id, session_id, workbook_path
    cutover_plan = None
    task_index = {}
    access_index = {}
    blocked_task_id = None
    workbook_path = None
    session_id = str(uuid.uuid4())


def is_loaded() -> bool:
    """Return True if a cutover plan has been successfully loaded."""
    return cutover_plan is not None and len(task_index) > 0
