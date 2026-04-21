# Deploying On Render

## Important Reality First

This codebase can be deployed to Render, but the current `session_service` is a browser-session manager with portal login state and persistent Chromium profiles.

That means:

- Render can host the API.
- Render can run Playwright in headless mode.
- Render can persist profile/session files only if you attach a persistent disk.
- This service should run as a **single instance** if you depend on local Chromium profiles and SQLite state.
- Manual CAPTCHA-solving and visible browser interaction are **not a good fit** for Render web services.

So the best short-term Render deployment is:

- Host the API on Render.
- Use it for status, orchestration, and controlled automation attempts.
- Do not treat Render as the final home for a human-operated browser session workflow.

## Render Settings

Render docs say web services must listen on `0.0.0.0` and the `PORT` environment variable:

- [Web Services](https://render.com/docs/web-services)
- [Blueprint YAML Reference](https://render.com/docs/blueprint-spec)
- [Persistent Disks](https://render.com/docs/disks)

This repo now includes `render.yaml`.

## Recommended Setup

1. Push the repo to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo.
3. Use the `render.yaml` in the repo root.
4. Set a real value for `SESSION_SERVICE_TOKEN`.
5. Attach a **persistent disk** and mount it at:

`/opt/render/project/src/runtime`

Without a persistent disk, profile/session files are lost on restart or redeploy.

## Build And Start

Build command:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Start command:

```bash
python main.py
```

## Environment Variables

- `SESSION_SERVICE_TOKEN`: required secret for API access
- `SESSION_HEADLESS=true`: recommended on Render
- `SESSION_STATE_DIR=/opt/render/project/src/runtime`
- `SESSION_PROFILES_DIR=/opt/render/project/src/runtime/profiles`
- `SESSION_SQLITE_PATH=/opt/render/project/src/runtime/session_state.db`

## Best-Practice Recommendation

For production, keep this split in mind:

- Render: API layer, health checks, orchestration, possibly headless workers
- Separate dedicated worker host/VM: visible browser sessions and human CAPTCHA/manual-login handling

That split is safer because Render persistent disks are single-instance only, and this session-profile design is inherently stateful.
