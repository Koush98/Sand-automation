from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crm_service.domain import JobStatus


class ChallanRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    secret: str = Field(min_length=4, max_length=20)
    vehicle: str = Field(min_length=4, max_length=20)
    district: str = Field(min_length=2, max_length=100)
    ps: str = Field(min_length=2, max_length=100)
    qty: str = Field(min_length=1, max_length=20)
    purchaser_name: str = Field(min_length=1, max_length=120)
    purchaser_mobile: str = Field(min_length=5, max_length=20)
    rate: str = Field(min_length=1, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChallanJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str


class JobListResponse(BaseModel):
    items: list[ChallanJobResponse]
    total: int
