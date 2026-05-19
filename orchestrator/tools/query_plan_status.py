"""
Tool: query_plan_status  [Sonia's Agent]

Answers structured queries about the cutover plan status.
All results include a mandatory source_reference field (Bibliography).

Supported query_types:
  status_summary  - counts by status + completion percentage
  task_detail     - full task record for a given item_id
  overdue         - tasks past their Due Date and not Completed
  blocked         - tasks with Status == "Not Ok"
  by_responsible  - tasks filtered by Responsible name (case-insensitive)
  by_side         - tasks filtered by SIDE value
"""
import logging
from datetime import datetime, timezone

import state

logger = logging.getLogger(__name__)

VALID_QUERY_TYPES = {"status_summary", "task_detail", "overdue", "blocked", "by_responsible", "by_side"}


def query_plan_status(query_type: str, filter_value: str = None) -> dict:
    """
    Query the loaded cutover plan for status information.

    Args:
        query_type:   One of: status_summary, task_detail, overdue, blocked,
                      by_responsible, by_side.
        filter_value: Required for task_detail, by_responsible, by_side.

    Returns:
        A dict with query_type, results, source_reference, total_results.
    """
    if not state.is_loaded():
        return {
            "success": False,
            "error": "No cutover plan loaded.",
            "query_type": query_type,
            "results": [],
            "source_reference": "No data loaded",
            "total_results": 0,
        }

    if query_type not in VALID_QUERY_TYPES:
        return {
            "success": False,
            "error": f"Unknown query_type '{query_type}'. Valid: {sorted(VALID_QUERY_TYPES)}",
            "query_type": query_type,
            "results": [],
            "source_reference": "",
            "total_results": 0,
        }

    tasks = state.cutover_plan

    if query_type == "status_summary":
        return _status_summary(tasks)
    if query_type == "task_detail":
        return _task_detail(tasks, filter_value)
    if query_type == "overdue":
        return _overdue(tasks)
    if query_type == "blocked":
        return _blocked(tasks)
    if query_type == "by_responsible":
        return _by_field(tasks, "responsible", filter_value, "Responsible")
    if query_type == "by_side":
        return _by_field(tasks, "side", filter_value, "SIDE")

    return {"success": False, "error": "Unhandled query_type", "results": [], "total_results": 0}


def _status_summary(tasks: list) -> dict:
    counts = {"Open": 0, "In progress": 0, "Completed": 0, "Not Ok": 0}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    total = len(tasks)
    pct = round(counts["Completed"] / total * 100, 1) if total > 0 else 0
    result = {**counts, "total": total, "completion_percentage": pct}
    logger.info("M6.achieved: status_summary delivered — %d tasks", total)
    return {
        "success": True,
        "query_type": "status_summary",
        "results": [result],
        "source_reference": "Sheet: SUM DMO | Column: Status | Rows: all",
        "total_results": 1,
        "no_match": False,
    }


def _task_detail(tasks: list, item_id: str) -> dict:
    if not item_id:
        return _no_filter_error("task_detail", "item_id")
    task = state.task_index.get(str(item_id).strip())
    if not task:
        return {
            "success": True,
            "query_type": "task_detail",
            "results": [],
            "source_reference": f"Sheet: SUM DMO | Column: Item ID | Value: {item_id}",
            "total_results": 0,
            "no_match": True,
        }
    return {
        "success": True,
        "query_type": "task_detail",
        "results": [task],
        "source_reference": f"Sheet: SUM DMO | Column: Item ID | Row: {item_id}",
        "total_results": 1,
        "no_match": False,
    }


def _overdue(tasks: list) -> dict:
    now = datetime.now(timezone.utc)
    overdue = []
    for t in tasks:
        if t["status"] == "Completed":
            continue
        due = _parse_date(t.get("due_date", ""))
        if due and due < now:
            overdue.append({**t, "overdue_by_days": (now - due).days})
    return {
        "success": True,
        "query_type": "overdue",
        "results": overdue,
        "source_reference": "Sheet: SUM DMO | Columns: Due Date, Status | Rows: non-completed past Due Date",
        "total_results": len(overdue),
        "no_match": len(overdue) == 0,
    }


def _blocked(tasks: list) -> dict:
    blocked = [t for t in tasks if t["status"] == "Not Ok"]
    return {
        "success": True,
        "query_type": "blocked",
        "results": blocked,
        "source_reference": "Sheet: SUM DMO | Column: Status | Value: Not Ok",
        "total_results": len(blocked),
        "no_match": len(blocked) == 0,
    }


def _by_field(tasks: list, field: str, filter_value: str, col_label: str) -> dict:
    if not filter_value:
        return _no_filter_error(f"by_{field}", "filter_value")
    matched = [t for t in tasks if t.get(field, "").lower() == filter_value.lower()]
    return {
        "success": True,
        "query_type": f"by_{field}",
        "results": matched,
        "source_reference": f"Sheet: SUM DMO | Column: {col_label} | Value: {filter_value}",
        "total_results": len(matched),
        "no_match": len(matched) == 0,
    }


def _no_filter_error(query_type: str, param: str) -> dict:
    return {
        "success": False,
        "error": f"query_type '{query_type}' requires '{param}' to be provided.",
        "query_type": query_type,
        "results": [],
        "source_reference": "",
        "total_results": 0,
    }


def _parse_date(date_str: str):
    if not date_str:
        return None
    try:
        from dateutil import parser as dp
        dt = dp.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
