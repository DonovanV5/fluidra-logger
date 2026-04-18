from __future__ import annotations

from typing import Any

from job_execution.metrics import apply_job_metrics, coerce_optional_int
from job_execution.models import JobContext


def job_from_teraoka_status(status: dict[str, Any], workcenter: str) -> JobContext | None:
    if not status or not status.get("connected") or not status.get("job"):
        return None

    job_id = str(status.get("job") or "").strip()
    if not job_id:
        return None

    product_code = str(status.get("product_code") or "").strip()
    target_quantity = coerce_optional_int(status.get("total_quantity"))
    outstanding_quantity = coerce_optional_int(status.get("required_quantity"))
    actual_quantity = coerce_optional_int(status.get("qty_made"))

    if target_quantity is None:
        if actual_quantity is not None and outstanding_quantity is not None:
            target_quantity = actual_quantity + outstanding_quantity
        else:
            target_quantity = outstanding_quantity

    job = JobContext(
        source="Teraoka",
        job_id=job_id,
        sequence=str(status.get("sequence") or job_id).strip(),
        product_code=product_code,
        workcenter=str(workcenter or "").strip(),
        target_quantity=target_quantity,
        actual_quantity=actual_quantity,
        raw=dict(status),
    )
    return apply_job_metrics(job, reported_remaining=outstanding_quantity)
