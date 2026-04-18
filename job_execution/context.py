from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from job_execution.models import JobContext


class JobContextManager:
    def __init__(self):
        self.proposed_job: JobContext | None = None
        self.active_job: JobContext | None = None

    def propose_job(self, job: JobContext | None) -> JobContext | None:
        self.proposed_job = job
        if job is not None and self.is_active_for(job):
            self.active_job = replace(job, accepted_at=self.active_job.accepted_at)
        return self.proposed_job

    def clear_proposed_job(self) -> None:
        self.proposed_job = None

    def clear_active_job(self) -> None:
        self.active_job = None

    def accept_proposed_job(self, accepted_at: datetime | None = None) -> JobContext | None:
        if self.proposed_job is None:
            return None
        accepted_at = accepted_at if isinstance(accepted_at, datetime) else datetime.now()
        self.active_job = replace(self.proposed_job, accepted_at=accepted_at)
        return self.active_job

    def is_active_for(self, job: JobContext | None) -> bool:
        return bool(job and self.active_job and self.active_job.key == job.key)

    def requires_acceptance(self, job: JobContext | None = None) -> bool:
        candidate = job or self.proposed_job
        return bool(candidate and not self.is_active_for(candidate))
