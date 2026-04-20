from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, status

from session_service.auth import require_service_token
from session_service.browser_manager import BrowserSessionManager
from session_service.domain import SessionStatus
from session_service.schemas import (
    ChallanEligibilityResponse,
    LoginCheckResponse,
    SessionOpenRequest,
    SessionOpenResponse,
    SessionResponse,
)
from session_service.service import build_service
from session_service.settings import settings


app = FastAPI(title=settings.app_name)


@app.on_event("startup")
async def startup() -> None:
    app.state.service_context = build_service()
    app.state.session_manager = await app.state.service_context.__aenter__()


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.service_context.__aexit__(None, None, None)


def get_manager(request: Request) -> BrowserSessionManager:
    return request.app.state.session_manager


def to_response(record) -> SessionResponse:
    return SessionResponse(
        account_id=record.account_id,
        phone=record.phone,
        profile_dir=record.profile_dir,
        status=record.status,
        portal_state=record.portal_state,
        cooldown_until=datetime.fromisoformat(record.cooldown_until) if record.cooldown_until else None,
        last_seen_at=datetime.fromisoformat(record.last_seen_at),
        last_error=record.last_error,
        active_operation=record.active_operation,
        browser_pid=record.browser_pid,
    )


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    f"{settings.api_prefix}/sessions/open",
    response_model=SessionOpenResponse,
    dependencies=[Depends(require_service_token)],
)
async def open_session(
    payload: SessionOpenRequest,
    request: Request,
) -> SessionOpenResponse:
    manager = get_manager(request)
    result = await manager.open_session(payload.account_id, payload.phone)
    return SessionOpenResponse(
        session=to_response(result.record),
        reused_existing=result.reused_existing,
        login_required=result.login_required,
    )


@app.get(
    f"{settings.api_prefix}/sessions/{{account_id}}",
    response_model=SessionResponse,
    dependencies=[Depends(require_service_token)],
)
async def get_session(account_id: str, request: Request) -> SessionResponse:
    manager = get_manager(request)
    record = await manager.get_session(account_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return to_response(record)


@app.post(
    f"{settings.api_prefix}/sessions/{{account_id}}/login-check",
    response_model=LoginCheckResponse,
    dependencies=[Depends(require_service_token)],
)
async def login_check(account_id: str, request: Request) -> LoginCheckResponse:
    manager = get_manager(request)
    record = await manager.refresh_session_state(account_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return LoginCheckResponse(
        session=to_response(record),
        logged_in=record.status == SessionStatus.logged_in,
        login_screen_visible=record.status == SessionStatus.needs_login,
    )


@app.post(
    f"{settings.api_prefix}/sessions/{{account_id}}/challan-eligibility",
    response_model=ChallanEligibilityResponse,
    dependencies=[Depends(require_service_token)],
)
async def challan_eligibility(account_id: str, request: Request) -> ChallanEligibilityResponse:
    manager = get_manager(request)
    record = await manager.get_session(account_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        eligible_record = await manager.assert_challan_eligible(account_id)
        return ChallanEligibilityResponse(
            session=to_response(eligible_record),
            eligible=True,
            reason="Session is logged in and safe to use for challan work.",
        )
    except ValueError as exc:
        latest = await manager.get_session(account_id)
        assert latest is not None
        return ChallanEligibilityResponse(
            session=to_response(latest),
            eligible=False,
            reason=str(exc),
        )
