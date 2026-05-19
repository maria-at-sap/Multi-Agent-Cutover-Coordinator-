"""
Tool: validate_prerequisites  [Sonia's Agent]

Reads SAP role authorizations and access flags for the Responsible person
of a given task, as resolved from the SAP User Access List sheet.
"""
import logging
import re

import state

logger = logging.getLogger(__name__)


def validate_prerequisites(item_id: str) -> dict:
    """
    Return SAP role prerequisites and access flags for a task's Responsible person.

    Args:
        item_id: The Item ID of the task to validate.

    Returns:
        A dict with responsible details, authorizations, access flags, and risk_flags.
    """
    if not state.is_loaded():
        return {
            "success": False,
            "error": "No cutover plan loaded.",
            "item_id": item_id,
            "has_prerequisites": False,
        }

    task = state.task_index.get(item_id)
    if task is None:
        msg = f"Item ID '{item_id}' not found."
        logger.error("M4.missed: task_id=%s not found", item_id)
        return {"success": False, "error": msg, "item_id": item_id, "has_prerequisites": False}

    auth_source = task.get("authorizations_source", "")
    auth_target = task.get("authorizations_target", "")
    access_tested = task.get("access_tested", False)
    access_comment = task.get("access_comment", "")

    auth_source_list = _parse_authorizations(auth_source)
    auth_target_list = _parse_authorizations(auth_target)
    has_prerequisites = bool(auth_source_list or auth_target_list)

    risk_flags = []
    if not access_tested:
        risk_flags.append("⚠️ Access has not been tested on MP1 source for this user.")
    if not task.get("responsible_email"):
        risk_flags.append("⚠️ Could not resolve email address for Responsible person — name may not match the Access List.")

    n = len(auth_source_list) + len(auth_target_list)
    logger.info("M4.achieved: Prerequisites validated — task_id=%s, count=%d", item_id, n)
    return {
        "success": True,
        "item_id": item_id,
        "responsible_name": task.get("responsible", ""),
        "responsible_email": task.get("responsible_email", ""),
        "qx_user_id": task.get("responsible_qx_user_id", ""),
        "team": task.get("responsible_team", ""),
        "authorizations_source": auth_source_list,
        "authorizations_target": auth_target_list,
        "access_comment": access_comment,
        "access_tested": access_tested,
        "has_prerequisites": has_prerequisites,
        "risk_flags": risk_flags,
    }


def _parse_authorizations(raw: str) -> list:
    if not raw or not raw.strip():
        return []
    parts = re.split(r"[,;]+", raw)
    return [p.strip() for p in parts if p.strip()]
