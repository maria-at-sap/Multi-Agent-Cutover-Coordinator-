"""
Tool: color_excel  [Silvia's Agent]

Applies row-level color coding and Excel enhancements to the "SUM DMO" sheet
of the loaded cutover workbook based on current task statuses.

Color legend:
  Green  (#00B050) — Completed / Done
  Yellow (#FFFF00) — In progress
  Red    (#FF0000) — Open / Not Ok / Pending

Also applies: frozen header row, auto-filter, native conditional formatting
rules (auto-update when Status is edited in Excel), data-validation dropdown,
and a pie chart showing task distribution by status.
"""
import logging
from collections import Counter

import openpyxl
from openpyxl.chart import PieChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import state

logger = logging.getLogger(__name__)

#Completed
GREEN     = PatternFill(start_color="21AD30", end_color="21AD30", fill_type="solid")

#In progress
YELLOW    = PatternFill(start_color="EDE653", end_color="EDE653", fill_type="solid")

#Open
GRAY      = PatternFill(start_color="9AA69A", end_color="9AA69A", fill_type="solid")

#Not Ok
RED       = PatternFill(start_color="E04843", end_color="E04843", fill_type="solid")

BLUE_BOLD = Font(color="0070C0", bold=True)

STATUS_MAP = {
    "completed":   GREEN,
    "in progress": YELLOW,
    "open":        GRAY,
    "not ok":      RED,
}

VALID_STATUSES_DROPDOWN = "Completed,In progress,Open,Not Ok"


def color_excel(output_path: str = None) -> dict:
    """
    Color-code the SUM DMO sheet and apply Excel formatting enhancements.

    Uses state.workbook_path (set by parse_cutover_plan). Overwrites the
    source file unless output_path is specified.

    Args:
        output_path: Optional path to save the formatted file instead of
                     overwriting the source.

    Returns:
        A dict with success, output_file, colored_rows_count, status_counts,
        enhancements, and legend.
    """
    if not state.is_loaded():
        return {"success": False, "error": "No cutover plan loaded.", "output_file": None}

    file_path = state.workbook_path
    if not file_path:
        return {"success": False, "error": "Workbook path not set in state.", "output_file": None}

    save_path = output_path or file_path

    try:
        wb = openpyxl.load_workbook(file_path)

        if "SUM DMO" not in wb.sheetnames:
            wb.close()
            return {"success": False, "error": "'SUM DMO' sheet not found.", "output_file": None}

        ws = wb["SUM DMO"]

        headers = [str(cell.value).strip().lower() if cell.value else "" for cell in ws[1]]
        try:
            status_col_idx = next(i for i, h in enumerate(headers) if "status" in h)
        except StopIteration:
            wb.close()
            return {"success": False, "error": "Status column not found in SUM DMO.", "output_file": None}

        status_col = status_col_idx + 1
        status_col_ltr = get_column_letter(status_col)
        name_cols = [
            i + 1 for i, h in enumerate(headers)
            if any(k in h for k in ("responsible", "owner", "name"))
        ]
        max_row = ws.max_row
        max_col = ws.max_column

        # ── Manual row color coding ────────────────────────────────────────────
        colored = []
        for row_idx in range(2, max_row + 1):
            status_cell = ws.cell(row=row_idx, column=status_col)
            raw = str(status_cell.value).strip() if status_cell.value else ""
            fill = next((f for k, f in STATUS_MAP.items() if k in raw.lower()), None)
            if fill:
                for cell in ws[row_idx]:
                    cell.fill = fill
                colored.append({"row": row_idx, "status": raw})
            for col in name_cols:
                cell = ws.cell(row=row_idx, column=col)
                if cell.value:
                    cell.font = BLUE_BOLD

        # ── Freeze header + auto-filter ────────────────────────────────────────
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(max_col)}{max_row}"

        # ── Native conditional formatting (live auto-update in Excel) ─────────
        cf_range = f"A2:{get_column_letter(max_col)}{max_row}"
        ws.conditional_formatting.add(cf_range, FormulaRule(
            formula=[f'${status_col_ltr}2="Completed"'], fill=GREEN, stopIfTrue=True,
        ))
        ws.conditional_formatting.add(cf_range, FormulaRule(
            formula=[f'${status_col_ltr}2="In progress"'], fill=YELLOW, stopIfTrue=True,
        ))
        ws.conditional_formatting.add(cf_range, FormulaRule(
            formula=[f'${status_col_ltr}2="Open"'], fill=GRAY, stopIfTrue=True,
        ))
        ws.conditional_formatting.add(cf_range, FormulaRule(
            formula=[f'${status_col_ltr}2="Not Ok"'], fill=RED, stopIfTrue=True,
        ))

        # ── Data-validation dropdown on Status column ──────────────────────────
        dv = DataValidation(
            type="list",
            formula1=f'"{VALID_STATUSES_DROPDOWN}"',
            allow_blank=True,
            showDropDown=False,
            showErrorMessage=True,
            errorTitle="Invalid Status",
            error=f"Please select one of: {VALID_STATUSES_DROPDOWN}",
        )
        dv.add(f"{status_col_ltr}2:{status_col_ltr}{max_row}")
        ws.add_data_validation(dv)

        # ── Status counts for chart ────────────────────────────────────────────
        counts = Counter()
        for row_idx in range(2, max_row + 1):
            val = ws.cell(row=row_idx, column=status_col).value
            if val:
                counts[str(val).strip()] += 1

        if "Summary" in wb.sheetnames:
            del wb["Summary"]
        ws_sum = wb.create_sheet("Summary")
        ws_sum.append(["Status", "Count"])
        ordered = [
            ("Completed",   counts.get("Completed",   0)),
            ("In progress", counts.get("In progress", 0)),
            ("Open",        counts.get("Open",        0)),
            ("Not Ok",      counts.get("Not Ok",      0)),
        ]
        for status, count in ordered:
            ws_sum.append([status, count])

        labels = Reference(ws_sum, min_col=1, min_row=2, max_row=5)
        data   = Reference(ws_sum, min_col=2, min_row=1, max_row=5)

        # ── Pie chart (Completed=green, In progress=yellow, Open=gray, Not Ok=red)
        pie = PieChart()
        pie.title  = "Task Distribution by Status"
        pie.style  = 10
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        pie.width  = 14
        pie.height = 12
        slice_colors = ["21AD30", "EDE653", "9AA69A", "E04843"]
        for idx, hex_color in enumerate(slice_colors):
            pt = DataPoint(idx=idx)
            pt.graphicalProperties.solidFill = hex_color
            pie.series[0].dPt.append(pt)

        chart_row = max_row + 4
        ws.add_chart(pie, f"A{chart_row}")

        wb.save(save_path)
        wb.close()

        logger.info("Excel colored: %d rows, saved to %s", len(colored), save_path)
        return {
            "success": True,
            "output_file": save_path,
            "colored_rows_count": len(colored),
            "status_counts": dict(counts),
            "enhancements": [
                f"Manual row color coding: {len(colored)} rows colored",
                "Frozen header row (A2)",
                f"Auto-filter on all {max_col} columns",
                f"Conditional formatting on {cf_range} (auto-updates on Status edit)",
                f"Data-validation dropdown on {status_col_ltr}2:{status_col_ltr}{max_row}",
                f"Pie chart placed at A{chart_row}",
            ],
            "legend": {
                "Green  (#21AD30)": "Completed",
                "Yellow (#EDE653)": "In progress",
                "Gray   (#9AA69A)": "Open",
                "Red    (#E04843)": "Not Ok",
            },
        }

    except Exception as exc:
        logger.error("color_excel failed: %s", exc)
        return {"success": False, "error": f"Excel coloring failed: {exc}", "output_file": None}
