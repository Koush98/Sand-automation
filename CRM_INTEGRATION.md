# CRM Integration Service

This project now includes a CRM-facing API service around the sand challan automation.

## Run

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

## API

### Create a job

`POST /api/v1/challans/jobs`

Example body:

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
  "rate": "18",
  "metadata": {
    "crm_lead_id": "LEAD-101",
    "crm_user_id": "USR-7"
  }
}
```

### Get a job

`GET /api/v1/challans/jobs/{job_id}`

### List jobs

`GET /api/v1/challans/jobs`

## Scalability Model

The API is intentionally asynchronous and queue-backed so CRM traffic is decoupled from browser automation.

For true production scale:

- Keep FastAPI stateless behind a load balancer.
- Replace `InMemoryJobStore` with Redis/Postgres.
- Replace the in-process queue with Redis Streams, RabbitMQ, Kafka, or SQS.
- Run browser workers as a separate deployment pool.
- Use autoscaling workers with strict browser-session concurrency limits.
- Persist logs and screenshots to object storage.

## Important Constraint

The target portal includes CAPTCHA and manual verification steps. That means 5k concurrent CRM users can submit jobs, but 5k live browser executions is not realistic or safe. The service therefore supports:

- High-concurrency job intake.
- Controlled worker execution.
- Explicit `manual_action_required` status when human verification is needed.

Set `AUTOMATION_MODE=live` only for trusted environments where human-operated browser workers are available.
