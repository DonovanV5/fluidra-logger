from __future__ import annotations

from datetime import datetime
from typing import Any


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

SHEET_SCANS = "Scans"
SHEET_SCANS_LEGACY = "Sheet1"
SHEET_PRODUCTION = "Production"
SHEET_DOWNTIME = "Downtime"
SHEET_PRODUCTS = "Products"

SCAN_STATUS_SCANNED = "Scanned"
SCAN_STATUS_REWORKED = "Reworked"
SCAN_STATUS_VALUES = {SCAN_STATUS_SCANNED, SCAN_STATUS_REWORKED}

PRODUCTION_EVENT_START = "PRODUCTION_START"
PRODUCTION_EVENT_END = "PRODUCTION_END"
PRODUCTION_EVENT_VALUES = {PRODUCTION_EVENT_START, PRODUCTION_EVENT_END}

SCAN_HEADERS = [
    "Timestamp",
    "Product Code",
    "Barcode",
    "Batch",
    "Cycle time",
    "Status",
    "Description",
    "Operator",
    "Notes",
    "Is_Rework",
    "Workcenter",
]

PRODUCTION_HEADERS = [
    "Timestamp",
    "Event Type",
    "Product Code",
    "Duration (sec)",
    "Production Count",
    "Operator",
    "Workcenter",
]

DOWNTIME_HEADERS = [
    "Timestamp",
    "Duration (sec)",
    "Reason",
    "Description",
    "Operator",
    "Workcenter",
]

SCAN_COMPATIBILITY_ALIASES = {
    "Product_Code": "Product Code",
}

SCAN_REQUIRED_FIELDS = [
    "Timestamp",
    "Product Code",
    "Barcode",
    "Cycle time",
    "Status",
]

SCAN_OPTIONAL_FIELDS = [
    "Batch",
    "Description",
    "Operator",
    "Notes",
    "Is_Rework",
    "Workcenter",
]

PRODUCTION_REQUIRED_FIELDS = [
    "Timestamp",
    "Event Type",
    "Product Code",
    "Duration (sec)",
    "Production Count",
]

PRODUCTION_OPTIONAL_FIELDS = [
    "Operator",
    "Workcenter",
]

DOWNTIME_REQUIRED_FIELDS = [
    "Timestamp",
    "Duration (sec)",
    "Reason",
]

DOWNTIME_OPTIONAL_FIELDS = [
    "Description",
    "Operator",
    "Workcenter",
]

PRODUCT_REQUIRED_FIELDS = [
    "Product Code",
    "Expected Cycle",
]

PRODUCT_OPTIONAL_FIELDS = [
    "Description",
    "Barcode Display",
]

PRODUCT_LOOKUP_COLUMNS = {
    "Product Code": 0,
    "Description": 1,
    "Expected Cycle": 4,
    "Barcode Display": 8,
}


def format_contract_timestamp(value: datetime) -> str:
    return value.strftime(TIMESTAMP_FORMAT)


def normalize_scan_status(status: str | None, is_rework: bool = False) -> str:
    value = str(status or "").strip().lower()
    if is_rework or value in {"rework", "reworked"}:
        return SCAN_STATUS_REWORKED
    return SCAN_STATUS_SCANNED


def ensure_alias_fields(data: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    result = dict(data)
    for alias, canonical in aliases.items():
        if alias not in result and canonical in result:
            result[alias] = result[canonical]
        if canonical not in result and alias in result:
            result[canonical] = result[alias]
    return result


def normalize_scan_row(data: dict[str, Any]) -> dict[str, Any]:
    row = ensure_alias_fields(dict(data), SCAN_COMPATIBILITY_ALIASES)
    row["Status"] = normalize_scan_status(row.get("Status"), bool(row.get("Is_Rework")))
    row["Is_Rework"] = bool(row.get("Is_Rework"))
    for header in SCAN_HEADERS:
        row.setdefault(header, "")
    return row


def build_scan_row(
    *,
    timestamp: datetime,
    product_code: str,
    barcode: str,
    batch: str,
    cycle_time_seconds: float,
    status: str,
    description: str,
    operator: str,
    notes: str,
    is_rework: bool,
    workcenter: str,
) -> dict[str, Any]:
    return normalize_scan_row(
        {
            "Timestamp": format_contract_timestamp(timestamp),
            "Product Code": product_code,
            "Barcode": barcode,
            "Batch": batch,
            "Cycle time": f"{float(cycle_time_seconds):.2f}",
            "Status": status,
            "Description": description,
            "Operator": operator or "Unknown",
            "Notes": notes,
            "Is_Rework": bool(is_rework),
            "Workcenter": workcenter or "",
        }
    )


def build_production_row(
    *,
    timestamp: datetime,
    event_type: str,
    product_code: str,
    duration_seconds: float,
    production_count: int,
    operator: str,
    workcenter: str,
) -> dict[str, Any]:
    value = str(event_type or "").strip().upper()
    if value not in PRODUCTION_EVENT_VALUES:
        value = PRODUCTION_EVENT_START if duration_seconds <= 0 else PRODUCTION_EVENT_END
    return {
        "Timestamp": format_contract_timestamp(timestamp),
        "Event Type": value,
        "Product Code": product_code or "N/A",
        "Duration (sec)": f"{float(duration_seconds):.2f}",
        "Production Count": str(int(production_count)),
        "Operator": operator or "Unknown",
        "Workcenter": workcenter or "",
    }


def build_downtime_row(
    *,
    timestamp: datetime,
    duration_seconds: float,
    reason: str,
    description: str,
    operator: str,
    workcenter: str,
) -> dict[str, Any]:
    return {
        "Timestamp": format_contract_timestamp(timestamp),
        "Duration (sec)": f"{float(duration_seconds):.2f}",
        "Reason": (reason or "Unknown").strip() or "Unknown",
        "Description": description or "",
        "Operator": operator or "",
        "Workcenter": workcenter or "",
    }


def normalize_scan_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_scan_row(record) for record in records]
