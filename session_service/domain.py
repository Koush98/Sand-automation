from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    idle = "idle"
    launching = "launching"
    needs_login = "needs_login"
    logged_in = "logged_in"
    busy = "busy"
    cooldown = "cooldown"
    closed_unexpectedly = "closed_unexpectedly"
    error = "error"


@dataclass
class PortalSessionRecord:
    account_id: str
    phone: str
    profile_dir: str
    status: SessionStatus
    portal_state: str
    cooldown_until: Optional[str]
    last_seen_at: str
    last_error: Optional[str]
    active_operation: Optional[str]
    browser_pid: Optional[int]


@dataclass
class SessionOpenResult:
    record: PortalSessionRecord
    reused_existing: bool
    login_required: bool
