import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from session_service.domain import PortalSessionRecord, SessionStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portal_sessions (
                    account_id TEXT PRIMARY KEY,
                    phone TEXT NOT NULL,
                    profile_dir TEXT NOT NULL,
                    status TEXT NOT NULL,
                    portal_state TEXT NOT NULL,
                    cooldown_until TEXT,
                    last_seen_at TEXT NOT NULL,
                    last_error TEXT,
                    active_operation TEXT,
                    browser_pid INTEGER
                )
                """
            )
            connection.commit()

    def get(self, account_id: str) -> Optional[PortalSessionRecord]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM portal_sessions WHERE account_id = ?",
                (account_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def upsert(self, record: PortalSessionRecord) -> PortalSessionRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO portal_sessions (
                    account_id, phone, profile_dir, status, portal_state,
                    cooldown_until, last_seen_at, last_error, active_operation, browser_pid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    phone = excluded.phone,
                    profile_dir = excluded.profile_dir,
                    status = excluded.status,
                    portal_state = excluded.portal_state,
                    cooldown_until = excluded.cooldown_until,
                    last_seen_at = excluded.last_seen_at,
                    last_error = excluded.last_error,
                    active_operation = excluded.active_operation,
                    browser_pid = excluded.browser_pid
                """,
                (
                    record.account_id,
                    record.phone,
                    record.profile_dir,
                    record.status.value,
                    record.portal_state,
                    record.cooldown_until,
                    record.last_seen_at,
                    record.last_error,
                    record.active_operation,
                    record.browser_pid,
                ),
            )
            connection.commit()
        return record

    def _row_to_record(self, row: sqlite3.Row) -> PortalSessionRecord:
        return PortalSessionRecord(
            account_id=row["account_id"],
            phone=row["phone"],
            profile_dir=row["profile_dir"],
            status=SessionStatus(row["status"]),
            portal_state=row["portal_state"],
            cooldown_until=row["cooldown_until"],
            last_seen_at=row["last_seen_at"],
            last_error=row["last_error"],
            active_operation=row["active_operation"],
            browser_pid=row["browser_pid"],
        )
