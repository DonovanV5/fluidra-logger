from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

from schema_contract import format_contract_timestamp


def default_production_schedule() -> dict[str, str]:
    return {
        "shift_start": "07:30",
        "shift_end": "15:30",
        "tea1_start": "09:00",
        "tea1_end": "09:15",
        "lunch_start": "12:00",
        "lunch_end": "12:30",
        "tea2_start": "14:00",
        "tea2_end": "14:15",
    }


def normalize_production_schedule(data: Any) -> dict[str, str]:
    defaults = default_production_schedule()
    raw = data if isinstance(data, dict) else {}
    normalized = {}
    for key, default_value in defaults.items():
        value = str(raw.get(key, default_value) or default_value).strip()
        normalized[key] = value if len(value) == 5 and ":" in value else default_value
    return normalized


def normalize_production_schedule_config(data: Any) -> dict[str, Any]:
    defaults = default_production_schedule()
    normalized = {
        "defaults": default_production_schedule(),
        "workcenters": {},
    }
    raw = data if isinstance(data, dict) else {}

    if any(key in raw for key in defaults):
        normalized["defaults"] = normalize_production_schedule(raw)

    defaults_raw = raw.get("defaults")
    if isinstance(defaults_raw, dict):
        normalized["defaults"] = normalize_production_schedule(defaults_raw)

    workcenters_raw = raw.get("workcenters")
    if isinstance(workcenters_raw, dict):
        for wc_key, schedule in workcenters_raw.items():
            wc_id = str(wc_key or "").strip()
            if not wc_id:
                continue
            normalized["workcenters"][wc_id] = normalize_production_schedule(
                schedule if isinstance(schedule, dict) else None
            )

    return normalized


def load_production_schedule_config(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize_production_schedule_config(json.load(f))
    except Exception:
        return {
            "defaults": default_production_schedule(),
            "workcenters": {},
        }


def get_schedule_for_workcenter(schedule_config: Any, workcenter: Any) -> dict[str, str]:
    normalized_config = normalize_production_schedule_config(schedule_config)
    base_schedule = normalize_production_schedule(normalized_config.get("defaults"))
    wc_key = str(workcenter or "").strip()
    wc_schedule = normalized_config.get("workcenters", {}).get(wc_key)
    if isinstance(wc_schedule, dict):
        return normalize_production_schedule({**base_schedule, **wc_schedule})
    return base_schedule


def get_production_schedule_mtime(path: str) -> float | None:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def active_planned_break_window(
    schedule_config: Any,
    workcenter: Any,
    break_definitions: tuple[tuple[str, str, str], ...],
    now: datetime | None = None,
) -> dict[str, Any] | None:
    now = now if isinstance(now, datetime) else datetime.now()
    schedule = get_schedule_for_workcenter(schedule_config, workcenter)

    for day_offset in (-1, 0):
        base_day = now.date() + timedelta(days=day_offset)
        shift_start = datetime.combine(base_day, datetime.min.time()).replace(
            hour=int(str(schedule.get("shift_start", "07:30")).split(":")[0]),
            minute=int(str(schedule.get("shift_start", "07:30")).split(":")[1]),
        )
        shift_end = datetime.combine(base_day, datetime.min.time()).replace(
            hour=int(str(schedule.get("shift_end", "15:30")).split(":")[0]),
            minute=int(str(schedule.get("shift_end", "15:30")).split(":")[1]),
        )
        if shift_end <= shift_start:
            shift_end += timedelta(days=1)

        for label, break_start_key, break_end_key in break_definitions:
            break_start = datetime.combine(base_day, datetime.min.time()).replace(
                hour=int(str(schedule.get(break_start_key, "00:00")).split(":")[0]),
                minute=int(str(schedule.get(break_start_key, "00:00")).split(":")[1]),
            )
            break_end = datetime.combine(base_day, datetime.min.time()).replace(
                hour=int(str(schedule.get(break_end_key, "00:00")).split(":")[0]),
                minute=int(str(schedule.get(break_end_key, "00:00")).split(":")[1]),
            )
            if shift_end.date() > shift_start.date() and break_start < shift_start:
                break_start += timedelta(days=1)
                break_end += timedelta(days=1)
            if break_end <= break_start:
                break_end += timedelta(days=1)
            if break_start <= now < break_end:
                return {
                    "key": f"{workcenter}|{format_contract_timestamp(break_start)}|{label}",
                    "label": label,
                    "start": break_start,
                    "end": break_end,
                    "workcenter": workcenter,
                }
    return None


def normalize_workcenter_selection(
    workcenters: list[dict[str, Any]],
    current_workcenter: Any,
    fallback_workcenter: str,
) -> tuple[list[dict[str, str]], str, str, bool, int]:
    normalized_workcenters = workcenters
    valid_workcenters = [
        str(wc.get("id", "")).strip()
        for wc in normalized_workcenters
        if str(wc.get("id", "")).strip()
    ]
    if not valid_workcenters:
        normalized_workcenters = [{"id": fallback_workcenter, "name": fallback_workcenter}]
        valid_workcenters = [fallback_workcenter]

    previous = str(current_workcenter or "").strip()
    selected = previous if previous in valid_workcenters else valid_workcenters[0]
    return normalized_workcenters, selected, previous, selected != previous, len(valid_workcenters)
