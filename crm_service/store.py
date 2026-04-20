import asyncio
from typing import Protocol

from crm_service.domain import ChallanJob, JobStatus, utc_now


class JobStore(Protocol):
    async def create(self, job: ChallanJob) -> ChallanJob: ...
    async def get(self, job_id: str) -> ChallanJob | None: ...
    async def list(self) -> list[ChallanJob]: ...
    async def update(self, job: ChallanJob) -> ChallanJob: ...


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ChallanJob] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: ChallanJob) -> ChallanJob:
        async with self._lock:
            self._jobs[job.job_id] = job
            return job

    async def get(self, job_id: str) -> ChallanJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list(self) -> list[ChallanJob]:
        async with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)

    async def update(self, job: ChallanJob) -> ChallanJob:
        job.updated_at = utc_now()
        async with self._lock:
            self._jobs[job.job_id] = job
            return job

    async def mark_running(self, job_id: str) -> ChallanJob | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.mark_status(JobStatus.running)
            return job
