from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    manual_action_required = "manual_action_required"
    succeeded = "succeeded"
    failed = "failed"


@dataclass(slots=True)
class ChallanJob:
    phone: str
    secret: str
    vehicle: str
    district: str
    ps: str
    qty: str
    purchaser_name: str
    purchaser_mobile: str
    rate: str
    metadata: dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: f"CH-{uuid4().hex[:12].upper()}")
    status: JobStatus = JobStatus.queued
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def mark_status(
        self,
        status: JobStatus,
        *,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.updated_at = utc_now()
        if status == JobStatus.running and self.started_at is None:
            self.started_at = self.updated_at
        if status in {JobStatus.succeeded, JobStatus.failed, JobStatus.manual_action_required}:
            self.finished_at = self.updated_at
        if error_message is not None:
            self.error_message = error_message
        if result is not None:
            self.result = result
