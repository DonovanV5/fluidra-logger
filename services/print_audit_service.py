from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

from schema_contract import format_contract_timestamp


def build_print_audit_record(
    *,
    job_type: Any,
    barcode: Any = "",
    status: Any = "",
    quantity: Any = 0,
    printer_name: Any = "",
    preset_name: Any = "",
    product_code: Any = "",
    workcenter: Any = "",
    outcome: Any = "",
    error: Any = "",
) -> dict[str, str]:
    return {
        "Timestamp": format_contract_timestamp(datetime.now()),
        "Job Type": str(job_type or ""),
        "Barcode": str(barcode or ""),
        "Status": str(status or ""),
        "Quantity": str(quantity or ""),
        "Printer": str(printer_name or ""),
        "Preset": str(preset_name or ""),
        "Product Code": str(product_code or ""),
        "Workcenter": str(workcenter or ""),
        "Outcome": str(outcome or ""),
        "Error": str(error or ""),
    }


def append_print_audit_record(audit_path: str, headers: list[str], record: dict[str, Any], lock: Any) -> None:
    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    with lock:
        needs_header = not os.path.exists(audit_path) or os.path.getsize(audit_path) == 0
        with open(audit_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            if needs_header:
                writer.writeheader()
            writer.writerow(record)


def read_recent_print_audit(audit_path: str, limit: int = 20) -> list[dict[str, str]]:
    if not os.path.exists(audit_path):
        return []
    with open(audit_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-int(limit):]


def format_print_audit_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No print audit records yet."
    lines = []
    for row in rows:
        error_text = str(row.get("Error", "") or "").strip()
        suffix = f" | {error_text}" if error_text else ""
        lines.append(
            (
                f"{row.get('Timestamp', '')} | {row.get('Outcome', '')} | "
                f"{row.get('Job Type', '')} | Qty {row.get('Quantity', '')} | "
                f"{row.get('Barcode', '')} | {row.get('Status', '')} | "
                f"{row.get('Preset', '')} | {row.get('Printer', '')}{suffix}"
            )
        )
    return "\n".join(lines)


def print_audit_outcome_is_success(outcome: Any) -> bool:
    return str(outcome).lower() in {"queued", "success"}
