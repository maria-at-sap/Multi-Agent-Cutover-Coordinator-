"""
Tool: send_teams_notification  [Maria's Agent]

Sends a Microsoft Teams channel notification via Incoming Webhook when the
next cutover task is ready to start. Linear sequencing: first task done →
next task notified. No dependency column — Item ID order is the sequence.

Reuses Maria's Teams webhook key from the TEAMS_WEBHOOK_URL environment variable.
"""
import logging
import os
from datetime import datetime

import requests

import state

logger = logging.getLogger(__name__)


def send_teams_notification(item_id: str) -> dict:
    """
    Post a Teams MessageCard to notify the channel that a task is ready to start.

    Args:
        item_id: The Item ID of the task that is now ready to start.

    Returns:
        A dict with success, message, and delivery_method.
    """
    if not state.is_loaded():
        return {"success": False, "error": "No cutover plan loaded.", "item_id": item_id}

    task = state.task_index.get(item_id)
    if task is None:
        return {"success": False, "error": f"Item ID '{item_id}' not found.", "item_id": item_id}

    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")
    if not webhook_url:
        return {
            "success": False,
            "error": "TEAMS_WEBHOOK_URL is not set in .env — cannot send Teams notification.",
            "item_id": item_id,
        }

    assignee_name = task.get("responsible") or task.get("owner") or "Unknown"
    task_name = task.get("item_description", "Unknown")
    due_date = task.get("due_date", "")
    notes = task.get("env_comment", "") or task.get("comments_mp1", "")
    team = task.get("responsible_team", "")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    facts = [
        {"name": "Task ID",     "value": item_id},
        {"name": "Task",        "value": task_name},
        {"name": "Assignee",    "value": assignee_name},
        {"name": "Activated At","value": timestamp},
    ]
    if team:
        facts.append({"name": "Team", "value": team})
    if due_date:
        facts.append({"name": "Due Date", "value": due_date})
    if notes:
        facts.append({"name": "Notes", "value": notes})

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "c0392b",
        "summary": f"Cutover task ready: {task_name}",
        "sections": [{
            "activityTitle": "🔴 **ACTION REQUIRED** — Cutover Task Ready to Start",
            "activitySubtitle": (
                f"**{assignee_name}**, your task is now unblocked and ready to begin. "
                "All preceding tasks are complete."
            ),
            "facts": facts,
            "markdown": True,
        }],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(
            "M5.achieved: Teams notification sent — task_id=%s, assignee=%s",
            item_id, assignee_name,
        )
        return {
            "success": True,
            "message": f"Teams notification sent for task '{task_name}' (Assignee: {assignee_name})",
            "item_id": item_id,
            "assignee": assignee_name,
            "delivery_method": "Teams webhook",
        }
    except Exception as exc:
        logger.error("Teams notification failed for task_id=%s: %s", item_id, exc)
        return {
            "success": False,
            "error": f"Teams notification failed: {exc}",
            "item_id": item_id,
        }
