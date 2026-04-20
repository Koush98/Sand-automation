import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Sand Portal Session Service"
    api_prefix: str = "/api/v1"
    service_token: str = os.getenv("SESSION_SERVICE_TOKEN", "change-me")
    state_dir: Path = Path(os.getenv("SESSION_STATE_DIR", "runtime"))
    profiles_dir: Path = Path(os.getenv("SESSION_PROFILES_DIR", "runtime/profiles"))
    sqlite_path: Path = Path(os.getenv("SESSION_SQLITE_PATH", "runtime/session_state.db"))
    base_url: str = os.getenv("SESSION_BASE_URL", "https://mdtcl.wb.gov.in/")
    cooldown_minutes: int = int(os.getenv("SESSION_COOLDOWN_MINUTES", "20"))
    headless: bool = os.getenv("SESSION_HEADLESS", "false").lower() == "true"


settings = Settings()
