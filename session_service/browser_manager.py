import asyncio
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Dict, Optional

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from sand_app import find_ps_code, load_mapping, normalize
from session_service.domain import PortalSessionRecord, SessionOpenResult, SessionStatus
from session_service.portal_probe import (
    detect_portal_state,
    dismiss_portal_popups,
    logout_portal,
    prepare_portal_entry,
    prime_login_flow,
    slow_type,
)
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
        self._playwright: Optional[Playwright] = None
        self._active: Dict[str, ManagedSession] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._mapping = load_mapping()

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

    async def open_session(self, account_id: str, phone: str, secret: Optional[str] = None) -> SessionOpenResult:
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
            await prepare_portal_entry(page)
            await prime_login_flow(page, phone=phone, secret=secret)

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

    async def get_session(self, account_id: str) -> Optional[PortalSessionRecord]:
        managed = self._active.get(account_id)
        if managed and managed.page.is_closed():
            await self._mark_cooldown(account_id, reason="Managed browser was closed unexpectedly.")
        return self.store.get(account_id)

    async def refresh_session_state(self, account_id: str) -> Optional[PortalSessionRecord]:
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

    async def mark_idle(self, account_id: str) -> Optional[PortalSessionRecord]:
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

    async def close_session(self, account_id: str, *, expected: bool) -> Optional[PortalSessionRecord]:
        async with self._lock_for(account_id):
            managed = self._active.get(account_id)
            record = self.store.get(account_id)
            logged_out = False
            if managed:
                if expected and not managed.page.is_closed():
                    try:
                        logged_out = await logout_portal(managed.page)
                    except Exception:
                        logged_out = False
                if not expected or logged_out:
                    self._active.pop(account_id, None)
                    await managed.context.close()
            if record is None:
                return None
            if expected:
                if managed and not logged_out:
                    updated = replace(
                        record,
                        status=SessionStatus.logged_in,
                        portal_state=record.portal_state,
                        cooldown_until=None,
                        last_error="Logout failed, so the browser was left open intentionally.",
                        active_operation=None,
                        browser_pid=managed.record.browser_pid,
                        last_seen_at=utc_now().isoformat(),
                    )
                    self.store.upsert(updated)
                    managed.record = updated
                    return updated
                updated = replace(
                    record,
                    status=SessionStatus.idle,
                    portal_state="logged_out" if logged_out else "closed",
                    cooldown_until=None,
                    last_error=None if logged_out else record.last_error,
                    active_operation=None,
                    browser_pid=None,
                    last_seen_at=utc_now().isoformat(),
                )
            else:
                updated = self._cooldown_record(record, "Browser closed without logout.")
            self.store.upsert(updated)
            return updated

    async def create_draft_challan(self, account_id: str, payload) -> PortalSessionRecord:
        session_result = await self.open_session(
            account_id=account_id,
            phone=payload.phone,
            secret=payload.secret,
        )

        async with self._lock_for(account_id):
            managed = self._active.get(account_id)
            if managed is None:
                record = session_result.record
                if self._is_cooling_down(record) or record.status == SessionStatus.cooldown:
                    raise ValueError("Session is in cooldown due to an unclean browser close.")
                if record.portal_state == "portal_cooldown_message":
                    raise ValueError("Portal is blocking login for this account due to the 20-minute session lock.")
                if record.status == SessionStatus.needs_login:
                    raise ValueError("Login is not complete yet. Solve CAPTCHA/login first, then retry.")
                raise ValueError("Failed to create or reuse a managed browser session for this account.")

            record = await self._update_from_page(
                account_id=account_id,
                phone=payload.phone,
                profile_dir=Path(managed.record.profile_dir),
                page=managed.page,
                browser_pid=managed.record.browser_pid,
                last_error=None,
                active_operation=managed.record.active_operation,
                context=managed.context,
            )
            if record is None:
                raise ValueError("Session does not exist for this account.")
            if self._is_cooling_down(record):
                raise ValueError("Session is in cooldown due to an unclean browser close.")
            if record.portal_state == "portal_cooldown_message":
                raise ValueError("Portal is blocking login for this account due to the 20-minute session lock.")
            if record.status != SessionStatus.logged_in:
                raise ValueError("Session is not logged in on the portal.")
            if record.active_operation:
                raise ValueError("Session is busy with another operation.")

            busy_record = replace(
                record,
                status=SessionStatus.busy,
                active_operation="draft_challan",
                last_seen_at=utc_now().isoformat(),
            )
            self.store.upsert(busy_record)
            managed.record = busy_record

            try:
                await self._run_draft_challan_flow(managed.page, payload)
                logged_out = await logout_portal(managed.page)
                if not logged_out:
                    updated = replace(
                        managed.record,
                        status=SessionStatus.logged_in,
                        active_operation=None,
                        last_error="Logout failed, so the browser was left open intentionally.",
                        last_seen_at=utc_now().isoformat(),
                    )
                    self.store.upsert(updated)
                    managed.record = updated
                    raise ValueError("Draft challan was created, but logout/close did not complete safely.")

                self._active.pop(account_id, None)
                await managed.context.close()
                closed_record = replace(
                    managed.record,
                    status=SessionStatus.idle,
                    portal_state="logged_out",
                    cooldown_until=None,
                    last_error=None,
                    active_operation=None,
                    browser_pid=None,
                    last_seen_at=utc_now().isoformat(),
                )
                self.store.upsert(closed_record)
                if closed_record.portal_state != "logged_out":
                    raise ValueError("Draft challan was created, but logout/close did not complete safely.")
                return closed_record
            except Exception:
                if account_id in self._active:
                    updated = replace(
                        managed.record,
                        status=SessionStatus.logged_in if managed.record.portal_state in {"dashboard", "draft_page"} else managed.record.status,
                        active_operation=None,
                        last_seen_at=utc_now().isoformat(),
                    )
                    self.store.upsert(updated)
                    managed.record = updated
                raise

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
        browser_pid: Optional[int],
        last_error: Optional[str],
        active_operation: Optional[str],
        context: BrowserContext,
    ) -> PortalSessionRecord:
        await prepare_portal_entry(page)
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
        last_error: Optional[str],
        active_operation: Optional[str],
        browser_pid: Optional[int],
        cooldown_until: Optional[str],
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

    async def _mark_cooldown(self, account_id: str, reason: str) -> Optional[PortalSessionRecord]:
        record = self.store.get(account_id)
        if record is None:
            return None
        self._active.pop(account_id, None)
        if self._should_enforce_cooldown(record):
            updated = self._cooldown_record(record, reason)
        else:
            updated = replace(
                record,
                status=SessionStatus.needs_login,
                portal_state="closed_before_login",
                cooldown_until=None,
                last_error="Browser closed before the portal session was authenticated.",
                active_operation=None,
                browser_pid=None,
                last_seen_at=utc_now().isoformat(),
            )
        self.store.upsert(updated)
        return updated

    def _is_cooling_down(self, record: PortalSessionRecord) -> bool:
        if not record.cooldown_until:
            return False
        return utc_now() < _parse_dt(record.cooldown_until)

    def _should_enforce_cooldown(self, record: PortalSessionRecord) -> bool:
        return record.status in {SessionStatus.logged_in, SessionStatus.busy} or record.portal_state in {
            "dashboard",
            "draft_page",
        }

    async def _run_draft_challan_flow(self, page: Page, payload) -> None:
        district_key = normalize(payload.district)
        if district_key not in self._mapping:
            raise ValueError(f"Invalid district: {payload.district}")

        district_data = self._mapping[district_key]
        district_code = district_data["code"]
        ps_code = find_ps_code(payload.ps, district_data["ps"])

        await self._safe_click(page, "a:has-text('Road Challan')", "Road Challan")
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)
        await self._safe_click(
            page,
            "a[href*='WBMDTCL_TP_Prepare_Draft_Pass.aspx']",
            "Prepare Draft Challan",
        )
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)

        vehicle_input = await self._wait_for_visible(
            page,
            "#ctl00_ContentPlaceHolder1_txtVehicleRegNo",
            "Vehicle field",
            timeout=60000,
        )
        await slow_type(vehicle_input, payload.vehicle)

        await page.locator("#ctl00_ContentPlaceHolder1_ddl_Purchaser_District").select_option(district_code)
        proceed_button = page.get_by_role("button", name="Proceed")
        await proceed_button.click()
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)

        ps_dropdown = await self._wait_for_select_value(
            page,
            "#ctl00_ContentPlaceHolder1_ddl_PS",
            ps_code,
            "Police Station dropdown",
        )
        await ps_dropdown.select_option(ps_code)

        await self._ensure_records_available(page)

        qty_input = await self._wait_for_visible(
            page,
            "[id$='txt_pass_qty']",
            "Quantity input",
            timeout=60000,
        )
        await slow_type(qty_input, payload.qty)

        qty_checkbox = await self._wait_for_visible(
            page,
            "[id$='chkselect']",
            "Row checkbox",
            timeout=60000,
        )
        await qty_checkbox.check()

        purchaser_name = page.get_by_role("textbox", name="Enter Purchaser Name")
        await slow_type(purchaser_name, payload.purchaser_name)
        purchaser_mobile = page.get_by_role("textbox", name="Enter Purchaser Mobile No")
        await slow_type(purchaser_mobile, payload.purchaser_mobile)
        rate_input = page.locator("#ctl00_ContentPlaceHolder1_txt_sand_rate")
        await slow_type(rate_input, payload.rate)

        save_draft = page.get_by_role("button", name="Save Draft")
        await save_draft.click()
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)

        await self._safe_click(
            page,
            "#ctl00_ContentPlaceHolder1_btn_Proceed",
            "Proceed To Generate Pass",
            timeout=15000,
        )
        await page.wait_for_load_state("networkidle")
        await dismiss_portal_popups(page)

    async def _safe_click(self, page: Page, selector: str, name: str, timeout: int = 10000):
        matches = page.locator(selector)
        await matches.first.wait_for(state="attached", timeout=timeout)

        deadline = await page.evaluate("Date.now()") + timeout
        last_error = None

        while await page.evaluate("Date.now()") < deadline:
            count = await matches.count()
            for index in range(count):
                locator = matches.nth(index)
                try:
                    if not await locator.is_visible():
                        continue
                    await locator.scroll_into_view_if_needed()
                    await locator.click()
                    return locator
                except Exception as exc:
                    last_error = exc
            await page.wait_for_timeout(250)

        raise TimeoutError(f"Could not click {name}. Last error: {last_error}")

    async def _wait_for_visible(self, page: Page, selector: str, name: str, timeout: int = 45000):
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout)
        except Exception as exc:
            raise TimeoutError(f"{name} did not become visible in time.") from exc
        return locator

    async def _wait_for_select_value(self, page: Page, selector: str, value: str, name: str, timeout: int = 45000):
        dropdown = page.locator(selector)
        await dropdown.wait_for(state="visible", timeout=timeout)
        deadline = await page.evaluate("Date.now()") + timeout
        last_values = []

        while await page.evaluate("Date.now()") < deadline:
            options = dropdown.locator("option")
            count = await options.count()
            last_values = []
            for index in range(count):
                last_values.append(await options.nth(index).get_attribute("value") or "")
            if value in last_values:
                return dropdown
            await page.wait_for_timeout(500)

        raise TimeoutError(f"{name} did not load value {value}. Available values: {last_values}")

    async def _ensure_records_available(self, page: Page) -> None:
        no_records = page.get_by_text("No Records Found", exact=True)
        if await no_records.count() and await no_records.first.is_visible():
            raise ValueError("No records found for the selected vehicle, district, and police station.")

        qty_count = await page.locator("[id$='txt_pass_qty']").count()
        checkbox_count = await page.locator("[id$='chkselect']").count()
        if qty_count == 0 or checkbox_count == 0:
            raise ValueError("No selectable quantity rows were loaded on the page.")


def _parse_dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)
