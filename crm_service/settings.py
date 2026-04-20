import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "Sand Challan CRM Service"
    api_prefix: str = "/api/v1"
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "2"))
    queue_max_size: int = int(os.getenv("QUEUE_MAX_SIZE", "10000"))
    automation_mode: str = os.getenv("AUTOMATION_MODE", "manual-gated")


settings = Settings()
