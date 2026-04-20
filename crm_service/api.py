from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status

from crm_service.automation import build_executor
from crm_service.manager import JobManager
from crm_service.schemas import (
    ChallanJobResponse,
    ChallanRequest,
    JobCreatedResponse,
    JobListResponse,
)
from crm_service.settings import settings
from crm_service.store import InMemoryJobStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = InMemoryJobStore()
    manager = JobManager(
        store=store,
        executor=build_executor(settings.automation_mode),
        worker_concurrency=settings.worker_concurrency,
        queue_max_size=settings.queue_max_size,
    )
    await manager.start()
    app.state.job_manager = manager
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


def get_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}


@app.post(
    f"{settings.api_prefix}/challans/jobs",
    response_model=JobCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(payload: ChallanRequest, request: Request) -> JobCreatedResponse:
    manager = get_manager(request)
    job = await manager.submit(payload)
    return JobCreatedResponse(
        job_id=job.job_id,
        status=job.status,
        status_url=f"{settings.api_prefix}/challans/jobs/{job.job_id}",
    )


@app.get(
    f"{settings.api_prefix}/challans/jobs/{{job_id}}",
    response_model=ChallanJobResponse,
)
async def get_job(job_id: str, request: Request) -> ChallanJobResponse:
    manager = get_manager(request)
    job = await manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return ChallanJobResponse.model_validate(job)


@app.get(
    f"{settings.api_prefix}/challans/jobs",
    response_model=JobListResponse,
)
async def list_jobs(request: Request) -> JobListResponse:
    manager = get_manager(request)
    jobs = await manager.list()
    items = [ChallanJobResponse.model_validate(job) for job in jobs]
    return JobListResponse(items=items, total=len(items))
