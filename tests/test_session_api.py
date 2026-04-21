from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from session_service import api
from session_service.domain import PortalSessionRecord, SessionOpenResult, SessionStatus


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_record(
    *,
    account_id: str = "customer-001",
    phone: str = "7283005200",
    status: SessionStatus = SessionStatus.needs_login,
    portal_state: str = "login_screen",
    cooldown_until: str = None,
    last_error: str = None,
    active_operation: str = None,
    browser_pid: int = None,
) -> PortalSessionRecord:
    return PortalSessionRecord(
        account_id=account_id,
        phone=phone,
        profile_dir=rf"runtime\profiles\{account_id}",
        status=status,
        portal_state=portal_state,
        cooldown_until=cooldown_until,
        last_seen_at=iso_now(),
        last_error=last_error,
        active_operation=active_operation,
        browser_pid=browser_pid,
    )


class FakeSessionManager:
    def __init__(self) -> None:
        self.record = make_record()
        self.open_result = SessionOpenResult(
            record=self.record,
            reused_existing=False,
            login_required=True,
        )
        self.get_result = self.record
        self.refresh_result = self.record
        self.eligible_result = replace(
            self.record,
            status=SessionStatus.logged_in,
            portal_state="dashboard",
        )
        self.eligible_error = None
        self.close_result = replace(
            self.record,
            status=SessionStatus.idle,
            portal_state="logged_out",
        )
        self.draft_result = replace(
            self.record,
            status=SessionStatus.idle,
            portal_state="logged_out",
        )
        self.draft_error = None

    async def open_session(self, account_id: str, phone: str, secret: str = None) -> SessionOpenResult:
        record = replace(self.open_result.record, account_id=account_id, phone=phone)
        self.record = record
        self.open_result = SessionOpenResult(
            record=record,
            reused_existing=self.open_result.reused_existing,
            login_required=self.open_result.login_required,
        )
        return self.open_result

    async def get_session(self, account_id: str):
        return self.get_result

    async def refresh_session_state(self, account_id: str):
        return self.refresh_result

    async def assert_challan_eligible(self, account_id: str):
        if self.eligible_error:
            raise ValueError(self.eligible_error)
        return self.eligible_result

    async def close_session(self, account_id: str, *, expected: bool):
        return self.close_result

    async def create_draft_challan(self, account_id: str, payload):
        if self.draft_error:
            raise ValueError(self.draft_error)
        return self.draft_result


class DummyServiceContext(AbstractAsyncContextManager):
    def __init__(self, manager: FakeSessionManager) -> None:
        self.manager = manager

    async def __aenter__(self):
        return self.manager

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.fixture
def client(monkeypatch):
    manager = FakeSessionManager()
    monkeypatch.setattr(api, "build_service", lambda: DummyServiceContext(manager))

    with TestClient(api.app) as test_client:
        yield test_client, manager


def auth_headers():
    return {"X-Service-Token": "change-me"}


def test_healthcheck(client):
    test_client, _ = client
    response = test_client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_open_session_requires_auth(client):
    test_client, _ = client
    response = test_client.post(
        "/api/v1/sessions/open",
        json={"account_id": "customer-001", "phone": "7283005200", "secret": "769810"},
    )

    assert response.status_code == 401


def test_open_session_returns_session_details(client):
    test_client, manager = client
    manager.open_result = SessionOpenResult(
        record=make_record(status=SessionStatus.needs_login, portal_state="pin_required"),
        reused_existing=False,
        login_required=True,
    )

    response = test_client.post(
        "/api/v1/sessions/open",
        headers=auth_headers(),
        json={"account_id": "customer-123", "phone": "7283005200", "secret": "769810"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reused_existing"] is False
    assert body["login_required"] is True
    assert body["session"]["account_id"] == "customer-123"
    assert body["session"]["status"] == "needs_login"
    assert body["session"]["portal_state"] == "pin_required"


def test_get_session_returns_404_when_missing(client):
    test_client, manager = client
    manager.get_result = None

    response = test_client.get(
        "/api/v1/sessions/customer-404",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_get_session_returns_existing_state(client):
    test_client, manager = client
    manager.get_result = make_record(status=SessionStatus.logged_in, portal_state="dashboard")

    response = test_client.get(
        "/api/v1/sessions/customer-001",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "logged_in"
    assert response.json()["portal_state"] == "dashboard"


def test_login_check_reports_logged_in(client):
    test_client, manager = client
    manager.refresh_result = make_record(status=SessionStatus.logged_in, portal_state="dashboard")

    response = test_client.post(
        "/api/v1/sessions/customer-001/login-check",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["logged_in"] is True
    assert body["login_screen_visible"] is False
    assert body["session"]["status"] == "logged_in"


def test_login_check_reports_404_when_missing(client):
    test_client, manager = client
    manager.refresh_result = None

    response = test_client.post(
        "/api/v1/sessions/customer-001/login-check",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_challan_eligibility_returns_true_for_logged_in_session(client):
    test_client, manager = client
    manager.get_result = make_record(status=SessionStatus.logged_in, portal_state="dashboard")
    manager.eligible_result = manager.get_result

    response = test_client.post(
        "/api/v1/sessions/customer-001/challan-eligibility",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is True
    assert body["session"]["status"] == "logged_in"


def test_challan_eligibility_returns_false_with_reason(client):
    test_client, manager = client
    manager.get_result = make_record(status=SessionStatus.cooldown, portal_state="portal_cooldown_message")
    manager.eligible_error = "Session is in cooldown due to an unclean browser close."

    response = test_client.post(
        "/api/v1/sessions/customer-001/challan-eligibility",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible"] is False
    assert "cooldown" in body["reason"]


def test_challan_eligibility_returns_404_when_session_missing(client):
    test_client, manager = client
    manager.get_result = None

    response = test_client.post(
        "/api/v1/sessions/customer-001/challan-eligibility",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_close_session_returns_logged_out_when_successful(client):
    test_client, manager = client
    manager.close_result = make_record(status=SessionStatus.idle, portal_state="logged_out")

    response = test_client.post(
        "/api/v1/sessions/customer-001/close",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["logged_out"] is True
    assert body["closed"] is True


def test_close_session_returns_open_when_logout_fails(client):
    test_client, manager = client
    manager.close_result = make_record(
        status=SessionStatus.logged_in,
        portal_state="dashboard",
        last_error="Logout failed, so the browser was left open intentionally.",
    )

    response = test_client.post(
        "/api/v1/sessions/customer-001/close",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["logged_out"] is False
    assert body["closed"] is False
    assert "left open" in body["message"]


def test_close_session_returns_404_when_missing(client):
    test_client, manager = client
    manager.close_result = None

    response = test_client.post(
        "/api/v1/sessions/customer-001/close",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_draft_challan_returns_success(client):
    test_client, manager = client
    manager.draft_result = make_record(status=SessionStatus.idle, portal_state="logged_out")

    response = test_client.post(
        "/api/v1/sessions/customer-001/draft-challan",
        headers=auth_headers(),
        json={
            "phone": "7283005200",
            "secret": "769810",
            "vehicle": "WB25L0920",
            "district": "uttar 24 pargana",
            "ps": "basirhat",
            "qty": "620",
            "purchaser_name": "A",
            "purchaser_mobile": "0000000000",
            "rate": "18",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["session"]["portal_state"] == "logged_out"


def test_draft_challan_returns_400_for_invalid_session_state(client):
    test_client, manager = client
    manager.draft_error = "Session is not logged in on the portal."

    response = test_client.post(
        "/api/v1/sessions/customer-001/draft-challan",
        headers=auth_headers(),
        json={
            "phone": "7283005200",
            "secret": "769810",
            "vehicle": "WB25L0920",
            "district": "uttar 24 pargana",
            "ps": "basirhat",
            "qty": "620",
            "purchaser_name": "A",
            "purchaser_mobile": "0000000000",
            "rate": "18",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Session is not logged in on the portal."
