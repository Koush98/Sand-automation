# Sand Automation Backend

Backend service for managing WB sand portal sessions and automating challan generation with Playwright.

## What This Project Does

This project started as a standalone Playwright script and is now structured as a backend service with:

- managed browser sessions per account
- login/session state tracking
- safe logout-before-close handling
- single-entry draft challan generation flow for frontend use
- local API testing with pytest

## Main Files

### Current backend entrypoint

- `main.py`

### Primary API/service code

- `session_service/api.py`
- `session_service/browser_manager.py`
- `session_service/portal_probe.py`
- `session_service/schemas.py`
- `session_service/store.py`

### Core standalone automation

- `sand_app.py`
- `sand_debug.py`

### Tests

- `tests/test_session_api.py`

### Data/config

- `dist_ps_map.json`
- `.env`

## Project Structure

```text
Sand/
├─ main.py
├─ requirements.txt
├─ README.md
├─ dist_ps_map.json
├─ sand_app.py
├─ sand_debug.py
├─ session_service/
│  ├─ api.py
│  ├─ browser_manager.py
│  ├─ portal_probe.py
│  ├─ schemas.py
│  ├─ settings.py
│  └─ store.py
├─ tests/
│  └─ test_session_api.py
├─ .github/workflows/
├─ render.yaml
└─ docs:
   ├─ SESSION_API.md
   ├─ CRM_INTEGRATION.md
   └─ RENDER_DEPLOY.md
```

## Prerequisites

- Python 3.9+
- Chromium installed through Playwright
- Windows PowerShell for the local flow used here

## Installation

```powershell
cd D:\Sand
pip install -r requirements.txt
python -m playwright install chromium
```

## Environment

Create/update `.env` with the values used by the standalone scripts:

```env
PHONE=7283005200
SECRET=769810
VEHICLE=WB25L0920
PURCHASER_NAME=A
PURCHASER_MOBILE=0000000000
QTY=620
RATE=18
DISTRICT=uttar 24 pargana
PS=basirhat
```

For API mode, set the service token:

```powershell
$env:SESSION_SERVICE_TOKEN="test-token"
```

## Run The API

```powershell
python main.py
```

Server:

- `http://127.0.0.1:8000`

Health check:

```powershell
curl http://127.0.0.1:8000/healthz
```

## Main API Endpoints

### Production entrypoint

`POST /api/v1/sessions/{account_id}/draft-challan`

This is the main endpoint the frontend should call. It now handles:

- opening or reusing the session
- login flow
- session validation
- draft challan creation
- proceed-to-generate-pass click
- logout and safe close

```json
{
  "phone": "7283005200",
  "secret": "769810",
  "vehicle": "WB25L0920",
  "district": "uttar 24 pargana",
  "ps": "basirhat",
  "qty": "620",
  "purchaser_name": "A",
  "purchaser_mobile": "0000000000",
  "rate": "18"
}
```

### Debug/admin session endpoints

These are still useful for testing and troubleshooting.

### Open or reuse session

`POST /api/v1/sessions/open`

```json
{
  "account_id": "customer_001",
  "phone": "7283005200",
  "secret": "769810"
}
```

### Get session state

`GET /api/v1/sessions/{account_id}`

### Check login state

`POST /api/v1/sessions/{account_id}/login-check`

### Check challan eligibility

`POST /api/v1/sessions/{account_id}/challan-eligibility`

### Close session safely

`POST /api/v1/sessions/{account_id}/close`

This endpoint attempts logout first. If logout does not happen, the browser should remain open.

## Run Tests

```powershell
pytest -q
```

## Manual Testing Flow

1. Start the API.
2. Call the `draft-challan` endpoint with full payload.
3. Solve CAPTCHA manually if the portal requires it.
4. Confirm the flow logs in, fills the form, saves the draft, clicks `Proceed To Generate Pass`, logs out, and only then closes safely.
5. Use the session endpoints only if you need debugging or manual inspection.

## Important Notes

- Do not manually close the managed browser if you want to avoid portal login lock issues.
- `runtime/` stores local session state and browser profile data and is intentionally ignored in git.
- `logs/` stores screenshots and HTML debug artifacts.

## Status

Current focus:

- stable session handling
- safe logout-before-close
- draft challan API flow
- improving portal-specific selectors and live testing
