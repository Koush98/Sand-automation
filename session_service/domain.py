from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SessionStatus(str, Enum):
    idle = "idle"
    launching = "launching"
    needs_login = "needs_login"
    logged_in = "logged_in"
    busy = "busy"
    cooldown = "cooldown"
    closed_unexpectedly = "closed_unexpectedly"
    error = "error"


@dataclass(slots=True)
class PortalSessionRecord:
    account_id: str
    phone: str
    profile_dir: str
    status: SessionStatus
    portal_state: str
    cooldown_until: str | None
    last_seen_at: str
    last_error: str | None
    active_operation: str | None
    browser_pid: int | None


@dataclass(slots=True)
class SessionOpenResult:
    record: PortalSessionRecord
    reused_existing: bool
    login_required: bool
