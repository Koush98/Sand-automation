# Local Session Manager API

This service manages one persistent Chromium profile per portal account and prevents unsafe duplicate sessions.

## What it solves

- Reuses the same managed browser/profile for the same account.
- Detects whether the portal is already logged in.
- Prevents immediate relogin after an unclean close.
- Enforces a 20-minute cooldown when the browser/tab is closed without logout.
- Avoids launching a second managed browser for the same account.

## Run

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## Auth

Send a header on every protected request:

`X-Service-Token: change-me`

Replace the token in `session_service/settings.py` before real use.

## Endpoints

### Open or reuse a managed session

`POST /api/v1/sessions/open`

```json
{
  "account_id": "customer-001",
  "phone": "7283005200"
}
```

### Get current session state

`GET /api/v1/sessions/{account_id}`

### Re-check login state from the live page

`POST /api/v1/sessions/{account_id}/login-check`

### Check whether the session is safe to use for challan work

`POST /api/v1/sessions/{account_id}/challan-eligibility`

## Lifecycle

Typical states:

- `launching`
- `needs_login`
- `logged_in`
- `busy`
- `cooldown`

When the managed page or browser context closes unexpectedly, the service marks the session as `cooldown` for 20 minutes because the portal may still consider that account logged in.
