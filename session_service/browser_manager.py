import asyncio
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from session_service.domain import PortalSessionRecord, SessionOpenResult, SessionStatus
from session_service.portal_probe import detect_portal_state
from session_service.settings import settings
from session_service.store import SessionStore, utc_now


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return cleaned.strip("-") or "session"


class ManagedSession:
    def __init__(self, record: PortalSessionRecord, context: BrowserContext, page: Page) -> None:
        self.record = record
        self.context = context
        self.page = page


class BrowserSessionManager:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._playwright: Playwright | None = None
        self._active: dict[str, ManagedSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        settings.profiles_dir.mkdir(parents=True, exist_ok=True)
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def stop(self) -> None:
        for account_id in list(self._active):
            try:
                await self.close_session(account_id, expected=True)
            except Exception:
                pass
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _lock_for(self, account_id: str) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def open_session(self, account_id: str, phone: str) -> SessionOpenResult:
        async with self._lock_for(account_id):
            existing = self.store.get(account_id)
            if existing and self._is_cooling_down(existing):
                return SessionOpenResult(record=existing, reused_existing=True, login_required=False)

            managed = self._active.get(account_id)
            if managed and not managed.page.is_closed():
                refreshed = await self.refresh_session_state(account_id)
                assert refreshed is not None
                return SessionOpenResult(
                    record=refreshed,
                    reused_existing=True,
                    login_required=refreshed.status != SessionStatus.logged_in,
                )

            profile_dir = settings.profiles_dir / slugify(account_id)
            profile_dir.mkdir(parents=True, exist_ok=True)
            launching = self._build_record(
                account_id=account_id,
                phone=phone,
                profile_dir=profile_dir,
                status=SessionStatus.launching,
                portal_state="launching",
                last_error=None,
                active_operation=None,
                browser_pid=None,
                cooldown_until=None,
            )
            self.store.upsert(launching)

            context = await self._launch_context(profile_dir)
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(settings.base_url, wait_until="domcontentloaded", timeout=60000)

            pid = None
            browser = context.browser
            if browser is not None:
                impl = getattr(browser, "_impl_obj", None)
                proc = getattr(impl, "_browser_process", None)
                pid = getattr(proc, "pid", None)

            record = await self._update_from_page(
                account_id=account_id,
                phone=phone,
                profile_dir=profile_dir,
                page=page,
                browser_pid=pid,
                last_error=None,
                active_operation=None,
                context=context,
            )
            self._active[account_id] = ManagedSession(record=record, context=context, page=page)
            self._bind_close_handlers(account_id, context, page)

            return SessionOpenResult(
                record=record,
                reused_existing=False,
                login_required=record.status != SessionStatus.logged_in,
            )

    async def get_session(self, account_id: str) -> PortalSessionRecord | None:
        managed = self._active.get(account_id)
        if managed and managed.page.is_closed():
            await self._mark_cooldown(account_id, reason="Managed browser was closed unexpectedly.")
        return self.store.get(account_id)

    async def refresh_session_state(self, account_id: str) -> PortalSessionRecord | None:
        async with self._lock_for(account_id):
            managed = self._active.get(account_id)
            persisted = self.store.get(account_id)
            if managed is None:
                return persisted
            if managed.page.is_closed():
                return await self._mark_cooldown(
                    account_id,
                    reason="Managed browser page was closed unexpectedly.",
                )

            phone = persisted.phone if persisted else managed.record.phone
            profile_dir = Path(persisted.profile_dir if persisted else managed.record.profile_dir)
            record = await self._update_from_page(
                account_id=account_id,
                phone=phone,
                profile_dir=profile_dir,
                page=managed.page,
                browser_pid=managed.record.browser_pid,
                last_error=None,
                active_operation=managed.record.active_operation,
                context=managed.context,
            )
            self._active[account_id].record = record
            return record

    async def assert_challan_eligible(self, account_id: str) -> PortalSessionRecord:
        record = await self.refresh_session_state(account_id)
        if record is None:
            raise ValueError("Session does not exist for this account.")
        if self._is_cooling_down(record):
            raise ValueError("Session is in cooldown due to an unclean browser close.")
        if record.status != SessionStatus.logged_in:
            raise ValueError("Session is not logged in on the portal.")
        if record.active_operation:
            raise ValueError("Session is busy with another operation.")
        return record

    async def mark_busy(self, account_id: str, operation: str) -> PortalSessionRecord:
        async with self._lock_for(account_id):
            record = await self.assert_challan_eligible(account_id)
            updated = replace(
                record,
                status=SessionStatus.busy,
                active_operation=operation,
                last_seen_at=utc_now().isoformat(),
            )
            self.store.upsert(updated)
            managed = self._active.get(account_id)
            if managed:
                managed.record = updated
            return updated

    async def mark_idle(self, account_id: str) -> PortalSessionRecord | None:
        async with self._lock_for(account_id):
            record = await self.refresh_session_state(account_id)
            if record is None:
                return None
            status = SessionStatus.logged_in if record.portal_state in {"dashboard", "draft_page"} else record.status
            updated = replace(
                record,
                status=status,
                active_operation=None,
                last_seen_at=utc_now().isoformat(),
            )
            self.store.upsert(updated)
            managed = self._active.get(account_id)
            if managed:
                managed.record = updated
            return updated

    async def close_session(self, account_id: str, *, expected: bool) -> PortalSessionRecord | None:
        async with self._lock_for(account_id):
            managed = self._active.pop(account_id, None)
            record = self.store.get(account_id)
            if managed:
                await managed.context.close()
            if record is None:
                return None
            if expected:
                updated = replace(
                    record,
                    status=SessionStatus.idle,
                    portal_state="closed",
                    cooldown_until=None,
                    last_error=None,
                    active_operation=None,
                    browser_pid=None,
                    last_seen_at=utc_now().isoformat(),
                )
            else:
                updated = self._cooldown_record(record, "Browser closed without logout.")
            self.store.upsert(updated)
            return updated

    async def _launch_context(self, profile_dir: Path) -> BrowserContext:
        if self._playwright is None:
            raise RuntimeError("Playwright has not been started.")
        return await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=settings.headless,
            slow_mo=50,
        )

    async def _update_from_page(
        self,
        *,
        account_id: str,
        phone: str,
        profile_dir: Path,
        page: Page,
        browser_pid: int | None,
        last_error: str | None,
        active_operation: str | None,
        context: BrowserContext,
    ) -> PortalSessionRecord:
        status, portal_state, _, _ = await detect_portal_state(page)
        record = self._build_record(
            account_id=account_id,
            phone=phone,
            profile_dir=profile_dir,
            status=status,
            portal_state=portal_state,
            last_error=last_error,
            active_operation=active_operation,
            browser_pid=browser_pid,
            cooldown_until=None,
        )
        self.store.upsert(record)
        return record

    def _build_record(
        self,
        *,
        account_id: str,
        phone: str,
        profile_dir: Path,
        status: SessionStatus,
        portal_state: str,
        last_error: str | None,
        active_operation: str | None,
        browser_pid: int | None,
        cooldown_until: str | None,
    ) -> PortalSessionRecord:
        return PortalSessionRecord(
            account_id=account_id,
            phone=phone,
            profile_dir=str(profile_dir),
            status=status,
            portal_state=portal_state,
            cooldown_until=cooldown_until,
            last_seen_at=utc_now().isoformat(),
            last_error=last_error,
            active_operation=active_operation,
            browser_pid=browser_pid,
        )

    def _bind_close_handlers(self, account_id: str, context: BrowserContext, page: Page) -> None:
        page.on("close", lambda _: asyncio.create_task(self._mark_cooldown(account_id, reason="Page closed unexpectedly.")))
        context.on("close", lambda _: asyncio.create_task(self._mark_cooldown(account_id, reason="Browser context closed unexpectedly.")))

    def _cooldown_record(self, record: PortalSessionRecord, reason: str) -> PortalSessionRecord:
        cooldown_until = (utc_now() + timedelta(minutes=settings.cooldown_minutes)).isoformat()
        return replace(
            record,
            status=SessionStatus.cooldown,
            portal_state="cooldown",
            cooldown_until=cooldown_until,
            last_error=reason,
            active_operation=None,
            browser_pid=None,
            last_seen_at=utc_now().isoformat(),
        )

    async def _mark_cooldown(self, account_id: str, reason: str) -> PortalSessionRecord | None:
        record = self.store.get(account_id)
        if record is None:
            return None
        self._active.pop(account_id, None)
        updated = self._cooldown_record(record, reason)
        self.store.upsert(updated)
        return updated

    def _is_cooling_down(self, record: PortalSessionRecord) -> bool:
        if not record.cooldown_until:
            return False
        return utc_now() < _parse_dt(record.cooldown_until)


def _parse_dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)
