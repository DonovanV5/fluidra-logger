from __future__ import annotations

from datetime import datetime

from schema_contract import build_downtime_row


def build_downtime_event_row(
    timestamp: datetime,
    duration_seconds: float,
    reason: str,
    description: str,
    operator: str,
    workcenter: str,
) -> dict[str, str]:
    return build_downtime_row(
        timestamp=timestamp,
        duration_seconds=duration_seconds,
        reason=reason,
        description=description,
        operator=operator,
        workcenter=workcenter,
    )


def format_auto_downtime_multiplier(value: float) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def coerce_auto_downtime_multiplier(value: object, default: float = 2.5) -> float:
    try:
        multiplier = float(str(value).strip())
    except (TypeError, ValueError):
        multiplier = default
    if not 1.0 <= multiplier <= 20.0:
        raise ValueError("Auto downtime multiplier must be between 1 and 20.")
    return multiplier


def resume_button_enabled(operator_name: str, downtime_reason: object, description: str) -> bool:
    name_ok = bool(str(operator_name or "").strip())
    reason_ok = bool(downtime_reason and str(downtime_reason).strip() and downtime_reason != "Select Reason")
    desc_ok = bool(str(description or "").strip())
    return name_ok and reason_ok and desc_ok
