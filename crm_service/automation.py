import asyncio
from typing import Protocol

from crm_service.domain import ChallanJob, JobStatus

from sand_app import Config, load_mapping, run as run_portal_job


class AutomationExecutor(Protocol):
    async def execute(self, job: ChallanJob) -> tuple[JobStatus, dict]:
        """Return final status and result payload."""


class ManualGatedExecutor:
    async def execute(self, job: ChallanJob) -> tuple[JobStatus, dict]:
        return (
            JobStatus.manual_action_required,
            {
                "message": (
                    "Portal automation is gated by CAPTCHA/manual verification. "
                    "Use a human-operated worker session to continue this job."
                ),
                "next_action": "dispatch_to_human_worker",
            },
        )


class LocalPortalExecutor:
    def __init__(self) -> None:
        self._mapping = load_mapping()

    async def execute(self, job: ChallanJob) -> tuple[JobStatus, dict]:
        config = Config(
            phone=job.phone,
            secret=job.secret,
            vehicle=job.vehicle,
            district=job.district,
            ps=job.ps,
            qty=job.qty,
            purchaser_name=job.purchaser_name,
            purchaser_mobile=job.purchaser_mobile,
            rate=job.rate,
        )

        await asyncio.to_thread(run_portal_job, config=config, mapping=self._mapping)
        return JobStatus.succeeded, {"message": "Portal automation completed successfully."}


def build_executor(mode: str) -> AutomationExecutor:
    if mode == "live":
        return LocalPortalExecutor()
    return ManualGatedExecutor()
