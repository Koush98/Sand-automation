from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from session_service.domain import SessionStatus


class SessionOpenRequest(BaseModel):
    account_id: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=20)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    phone: str
    profile_dir: str
    status: SessionStatus
    portal_state: str
    cooldown_until: datetime | None
    last_seen_at: datetime
    last_error: str | None = None
    active_operation: str | None = None
    browser_pid: int | None = None


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
