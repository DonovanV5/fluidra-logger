from __future__ import annotations

from datetime import datetime

from schema_contract import build_production_row


def build_production_event_row(
    timestamp: datetime,
    event_type: str,
    product_code: str,
    duration_seconds: float,
    production_count: int,
    operator: str,
    workcenter: str,
) -> dict[str, str]:
    return build_production_row(
        timestamp=timestamp,
        event_type=event_type,
        product_code=product_code,
        duration_seconds=duration_seconds,
        production_count=production_count,
        operator=operator,
        workcenter=workcenter,
    )


def calculate_production_duration(start_time: datetime, end_time: datetime) -> float:
    return (end_time - start_time).total_seconds()


def calculate_pcs_per_min(production_count: int, total_runtime_seconds: float) -> float:
    if total_runtime_seconds <= 0:
        return 0.0
    return (production_count / total_runtime_seconds) * 60
