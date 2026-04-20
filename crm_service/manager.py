import asyncio
import logging

from crm_service.automation import AutomationExecutor
from crm_service.domain import ChallanJob, JobStatus
from crm_service.schemas import ChallanRequest
from crm_service.store import JobStore


logger = logging.getLogger(__name__)


class JobManager:
    def __init__(
        self,
        store: JobStore,
        executor: AutomationExecutor,
        *,
        worker_concurrency: int,
        queue_max_size: int,
    ) -> None:
        self.store = store
        self.executor = executor
        self.worker_concurrency = worker_concurrency
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_max_size)
        self._workers: list[asyncio.Task] = []
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        if self._workers:
            return
        for index in range(self.worker_concurrency):
            task = asyncio.create_task(self._worker_loop(index + 1))
            self._workers.append(task)

    async def stop(self) -> None:
        self._shutdown.set()
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def submit(self, payload: ChallanRequest) -> ChallanJob:
        job = ChallanJob(**payload.model_dump())
        await self.store.create(job)
        await self.queue.put(job.job_id)
        return job

    async def get(self, job_id: str) -> ChallanJob | None:
        return await self.store.get(job_id)

    async def list(self) -> list[ChallanJob]:
        return await self.store.list()

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info("Worker %s started", worker_id)
        while not self._shutdown.is_set():
            try:
                job_id = await self.queue.get()
                try:
                    job = await self.store.get(job_id)
                    if job is None:
                        continue

                    job.mark_status(JobStatus.running)
                    await self.store.update(job)

                    try:
                        status, result = await self.executor.execute(job)
                        job.mark_status(status, result=result)
                    except Exception as exc:
                        logger.exception("Job %s failed", job.job_id)
                        job.mark_status(
                            JobStatus.failed,
                            error_message=str(exc),
                            result={"message": "Job execution failed."},
                        )

                    await self.store.update(job)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                raise
