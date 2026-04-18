from __future__ import annotations

from datetime import datetime
from typing import Any


def normalize_barcode(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def calculate_scan_cycle_time(previous_scan_time: Any, now: datetime) -> float:
    if not isinstance(previous_scan_time, datetime):
        return 0.0
    return max(0.0, (now - previous_scan_time).total_seconds())
