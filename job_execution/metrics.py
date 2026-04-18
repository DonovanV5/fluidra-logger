from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from job_execution.models import JobContext


def coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def calculate_remaining_quantity(
    target_quantity: int | None,
    actual_quantity: int | None,
    reported_remaining: int | None = None,
) -> int | None:
    if reported_remaining is not None:
        return max(0, int(reported_remaining))
    if target_quantity is None or actual_quantity is None:
        return None
    return max(0, int(target_quantity) - int(actual_quantity))


def calculate_percent_complete(target_quantity: int | None, actual_quantity: int | None) -> float | None:
    if target_quantity in (None, 0) or actual_quantity is None:
        return None
    return max(0.0, min(100.0, (float(actual_quantity) / float(target_quantity)) * 100.0))


def calculate_projected_finish_time(
    started_at: datetime | None,
    actual_quantity: int | None,
    target_quantity: int | None,
    now: datetime | None = None,
) -> datetime | None:
    if started_at is None or actual_quantity in (None, 0) or target_quantity in (None, 0):
        return None
    now = now if isinstance(now, datetime) else datetime.now()
    elapsed = (now - started_at).total_seconds()
    if elapsed <= 0:
        return None
    seconds_per_unit = elapsed / float(actual_quantity)
    remaining_units = max(0, int(target_quantity) - int(actual_quantity))
    return now + timedelta(seconds=seconds_per_unit * remaining_units)


def calculate_behind_ahead_status(
    projected_finish_time: datetime | None,
    scheduled_end: datetime | None,
) -> str:
    if projected_finish_time is None or scheduled_end is None:
        return "Unknown"
    if projected_finish_time > scheduled_end:
        return "Behind"
    if projected_finish_time < scheduled_end:
        return "Ahead"
    return "On Track"


def apply_job_metrics(
    job: JobContext,
    *,
    reported_remaining: int | None = None,
    started_at: datetime | None = None,
    now: datetime | None = None,
) -> JobContext:
    remaining = calculate_remaining_quantity(job.target_quantity, job.actual_quantity, reported_remaining)
    percent = calculate_percent_complete(job.target_quantity, job.actual_quantity)
    projected_finish = calculate_projected_finish_time(started_at, job.actual_quantity, job.target_quantity, now)
    behind_ahead = calculate_behind_ahead_status(projected_finish, job.scheduled_end)
    return replace(
        job,
        remaining_quantity=remaining,
        percent_complete=percent,
        projected_finish_time=projected_finish,
        behind_ahead_status=behind_ahead,
    )
