from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from session_service.domain import SessionStatus


class SessionOpenRequest(BaseModel):
    account_id: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=20)
    secret: Optional[str] = Field(default=None, min_length=4, max_length=20)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    phone: str
    profile_dir: str
    status: SessionStatus
    portal_state: str
    cooldown_until: Optional[datetime]
    last_seen_at: datetime
    last_error: Optional[str] = None
    active_operation: Optional[str] = None
    browser_pid: Optional[int] = None


class SessionOpenResponse(BaseModel):
    session: SessionResponse
    reused_existing: bool
    login_required: bool


class LoginCheckResponse(BaseModel):
    session: SessionResponse
    logged_in: bool
    login_screen_visible: bool


class ChallanEligibilityResponse(BaseModel):
    session: SessionResponse
    eligible: bool
    reason: str


class SessionCloseResponse(BaseModel):
    session: SessionResponse
    logged_out: bool
    closed: bool
    message: str


class DraftChallanRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    secret: str = Field(min_length=4, max_length=20)
    vehicle: str = Field(min_length=4, max_length=20)
    district: str = Field(min_length=2, max_length=100)
    ps: str = Field(min_length=2, max_length=100)
    qty: str = Field(min_length=1, max_length=20)
    purchaser_name: str = Field(min_length=1, max_length=120)
    purchaser_mobile: str = Field(min_length=5, max_length=20)
    rate: str = Field(min_length=1, max_length=20)


class DraftChallanResponse(BaseModel):
    session: SessionResponse
    success: bool
    message: str
