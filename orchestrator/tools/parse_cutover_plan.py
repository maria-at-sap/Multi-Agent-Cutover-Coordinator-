"""
Tool: parse_cutover_plan  [Sonia's Agent]

Reads and indexes the two-sheet Excel cutover workbook:
  - Sheet "SUM DMO"             : Cutover task plan
  - Sheet "SAP User Access List": People, emails and SAP role prerequisites

Performs a cross-sheet join: Responsible/Owner names → access list by Name.
Stores the result in shared agent state.
"""
import logging
import os
import re
from typing import Any

import pandas as pd

import state

logger = logging.getLogger(__name__)

REQUIRED_DMO_COLS = {
    "Item ID", "SIDE", "Item Description", "Status",
    "Responsible", "Owner", "Due Date",
    "Comments MP1", "Comments DRY RUN", "Comments QAS",
    "Comments DEV", "Comments SBX",
}
REQUIRED_ACCESS_COLS = {
    "Team", "Name", "Email", "QX-User ID",
    "Needed Authorizations (source)", "Needed Authorizations (target)",
    "Comment", "Access tested on MP1 source",
}
VALID_STATUSES = {"Open", "In progress", "Completed", "Not Ok"}
SIDE_TO_COMMENT_COL = {
    "MP1": "Comments MP1",
    "DRY RUN": "Comments DRY RUN",
    "QAS": "Comments QAS",
    "DEV": "Comments DEV",
    "SBX": "Comments SBX",
}

DEFAULT_PLAN_PATH = os.environ.get("EXCEL_FILE_PATH", "Cutover Plan Test.xlsx")


def _normalise_name(name: Any) -> str:
    if not name or not isinstance(name, str):
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def parse_cutover_plan(file_path: str = DEFAULT_PLAN_PATH) -> dict:
    """
    Parse the Excel cutover workbook and load both sheets into agent state.

    Args:
        file_path: Absolute or relative path to the .xlsx workbook.

    Returns:
        A dict with keys:
          - success (bool)
          - tasks (list of task dicts)
          - unresolved_names (list of names not found in the access list)
          - total_tasks (int)
          - total_owners (int)
          - error (str, only on failure)
    """
    state.reset()

    try:
        xl = pd.ExcelFile(file_path, engine="openpyxl")
    except Exception as exc:
        msg = f"Cannot open workbook '{file_path}': {exc}"
        logger.error("M1.missed: %s", msg)
        return {"success": False, "error": msg, "tasks": [], "unresolved_names": [], "total_tasks": 0, "total_owners": 0}

    sheet_names = xl.sheet_names

    missing_sheets = []
    if "SUM DMO" not in sheet_names:
        missing_sheets.append("SUM DMO")
    if "SAP User Access List" not in sheet_names:
        missing_sheets.append("SAP User Access List")
    if missing_sheets:
        msg = f"Missing required sheets: {missing_sheets}. Found: {sheet_names}"
        logger.error("M1.missed: %s", msg)
        return {"success": False, "error": msg, "tasks": [], "unresolved_names": [], "total_tasks": 0, "total_owners": 0}

    dmo_df = xl.parse("SUM DMO", dtype=str).fillna("")
    access_df = xl.parse("SAP User Access List", dtype=str).fillna("")

    missing_dmo = REQUIRED_DMO_COLS - set(dmo_df.columns)
    if missing_dmo:
        msg = f"SUM DMO sheet missing columns: {sorted(missing_dmo)}"
        logger.error("M1.missed: %s", msg)
        return {"success": False, "error": msg, "tasks": [], "unresolved_names": [], "total_tasks": 0, "total_owners": 0}

    missing_access = REQUIRED_ACCESS_COLS - set(access_df.columns)
    if missing_access:
        msg = f"SAP User Access List sheet missing columns: {sorted(missing_access)}"
        logger.error("M1.missed: %s", msg)
        return {"success": False, "error": msg, "tasks": [], "unresolved_names": [], "total_tasks": 0, "total_owners": 0}

    access_index: dict = {}
    for _, row in access_df.iterrows():
        key = _normalise_name(row.get("Name", ""))
        if key:
            access_index[key] = row.to_dict()
    state.access_index = access_index

    def _sort_key(val: str):
        try:
            return (0, float(val))
        except (ValueError, TypeError):
            return (1, str(val))

    dmo_df["_sort_key"] = dmo_df["Item ID"].apply(_sort_key)
    dmo_df = dmo_df.sort_values("_sort_key").drop(columns=["_sort_key"])

    tasks = []
    unresolved_names = []
    seen_names: set = set()

    for _, row in dmo_df.iterrows():
        item_id = str(row.get("Item ID", "")).strip()
        if not item_id:
            continue

        responsible_raw = str(row.get("Responsible", "")).strip()
        owner_raw = str(row.get("Owner", "")).strip()
        side = str(row.get("SIDE", "")).strip().upper()

        resp_key = _normalise_name(responsible_raw)
        resp_record = access_index.get(resp_key, {})
        if responsible_raw and not resp_record:
            if responsible_raw not in seen_names:
                unresolved_names.append(responsible_raw)
                seen_names.add(responsible_raw)

        owner_key = _normalise_name(owner_raw)
        owner_record = access_index.get(owner_key, {})
        if owner_raw and not owner_record and owner_raw not in seen_names:
            unresolved_names.append(owner_raw)
            seen_names.add(owner_raw)

        env_comment_col = SIDE_TO_COMMENT_COL.get(side, "")
        env_comment = str(row.get(env_comment_col, "")).strip() if env_comment_col else ""

        task = {
            "item_id": item_id,
            "side": side,
            "item_description": str(row.get("Item Description", "")).strip(),
            "status": str(row.get("Status", "Open")).strip(),
            "responsible": responsible_raw,
            "owner": owner_raw,
            "due_date": str(row.get("Due Date", "")).strip(),
            "comments_mp1": str(row.get("Comments MP1", "")).strip(),
            "comments_dry_run": str(row.get("Comments DRY RUN", "")).strip(),
            "comments_qas": str(row.get("Comments QAS", "")).strip(),
            "comments_dev": str(row.get("Comments DEV", "")).strip(),
            "comments_sbx": str(row.get("Comments SBX", "")).strip(),
            "env_comment": env_comment,
            "responsible_email": resp_record.get("Email", ""),
            "responsible_qx_user_id": resp_record.get("QX-User ID", ""),
            "responsible_team": resp_record.get("Team", ""),
            "authorizations_source": resp_record.get("Needed Authorizations (source)", ""),
            "authorizations_target": resp_record.get("Needed Authorizations (target)", ""),
            "access_comment": resp_record.get("Comment", ""),
            "access_tested": _parse_access_tested(resp_record.get("Access tested on MP1 source", "")),
            "owner_email": owner_record.get("Email", ""),
            "owner_team": owner_record.get("Team", ""),
        }
        tasks.append(task)

    state.cutover_plan = tasks
    state.task_index = {t["item_id"]: t for t in tasks}
    state.workbook_path = file_path

    total_owners = len({t["responsible"] for t in tasks if t["responsible"]}
                       | {t["owner"] for t in tasks if t["owner"]})

    logger.info("M1.achieved: Cutover plan loaded — %d tasks, %d owners", len(tasks), total_owners)
    return {
        "success": True,
        "tasks": tasks,
        "unresolved_names": unresolved_names,
        "total_tasks": len(tasks),
        "total_owners": total_owners,
    }


def _parse_access_tested(value: str) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"yes", "true", "1", "x", "✓", "done", "tested"}
