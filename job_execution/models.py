from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class JobContext:
    source: str
    job_id: str
    sequence: str = ""
    product_code: str = ""
    workcenter: str = ""
    target_quantity: int | None = None
    actual_quantity: int | None = None
    remaining_quantity: int | None = None
    percent_complete: float | None = None
    projected_finish_time: datetime | None = None
    behind_ahead_status: str = "Unknown"
    priority: str = ""
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    accepted_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        parts = [
            self.source,
            self.job_id,
            self.sequence,
            self.product_code,
            self.workcenter,
        ]
        return "|".join(str(part or "").strip().upper() for part in parts)

    @property
    def display_job_id(self) -> str:
        return self.job_id or "-"

    @property
    def display_sequence(self) -> str:
        return self.sequence or "-"

    @property
    def display_product_code(self) -> str:
        return self.product_code or "-"

    @property
    def display_target_quantity(self) -> str:
        return str(self.target_quantity) if self.target_quantity is not None else "-"
