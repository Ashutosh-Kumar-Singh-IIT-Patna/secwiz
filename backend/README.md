# Security Alerts Copilot — Backend (V1)

Real-time breach and vulnerability alerting for a user-declared dependency
stack, built on FastAPI + Anakin's APIs.

This implements [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) with two
hackathon-friendly tweaks:

- **No Redis required.** Celery is configured in `task_always_eager=True`
  mode; the same task code runs synchronously in-process. APScheduler
  triggers the hourly fan-out from inside the FastAPI lifespan.
- **Wire is dynamic.** Per enabled platform slug we hit
  `GET /v1/holocron/search` and pick the first non-auth, async action — so
  Anakin's evolving catalog doesn't need a hand-maintained allowlist.

`EMAIL_DRY_RUN=true` is the default, so alerts log instead of send. Flip
that off plus add `SENDGRID_API_KEY` + `EMAIL_FROM` when you want real
email. SendGrid's Web API is used because most cloud free tiers (Render,
Heroku, Vercel) block outbound SMTP.

---

## 1. Stack

| Layer        | Choice                                                        |
|--------------|---------------------------------------------------------------|
| API          | FastAPI 0.119 (uvicorn ASGI)                                  |
| "Database"   | `data/store.json` via `JsonStore` (file-locked, atomic write) |
| Queue        | Celery 5.6 in `task_always_eager` mode                        |
| Scheduler    | APScheduler `BackgroundScheduler`, hourly                     |
| Anakin SDK   | `httpx.AsyncClient` wrappers in `app/services/anakin/`        |
| Email        | SendGrid Web API via `httpx` (dry-run by default)             |
| Structured   | OSV.dev + NVD direct REST calls (no key required)             |

---

## 2. Local setup (Windows + macOS / Linux)

```powershell
# from the repo root
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1     # macOS / Linux: source .venv/bin/activate
pip install -r backend\requirements.txt

copy backend\.env.example backend\.env   # cp on macOS/Linux
# then edit backend\.env and set ANAKIN_API_KEY=...
```

---

## 3. Run the API

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

A single uvicorn process now hosts:

- HTTP API (`/v1/healthz`, `/v1/wire-catalog`, `/v1/onboard`, `/v1/runs/trigger`)
- Eager Celery worker (tasks run inline)
- APScheduler hourly trigger (configurable via `RUN_INTERVAL_MINUTES`)

OpenAPI docs at `http://localhost:8000/docs`.

---

## 4. End-to-end smoke

With the server running:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
.\.venv\Scripts\python.exe backend\scripts\smoke.py            # OSV + NVD only (no Anakin credits)
.\.venv\Scripts\python.exe backend\scripts\smoke.py --with-wire # includes Wire ingest
```

Expected output for the structured-intel run (using `npm:lodash` +
`pypi:requests`):

```
--- run ---
{
  "stats": { "docs": 41, "candidates": 41, "events": 2, "alerts_sent": 1 }
}

--- store summary ---
{ "users": 1, "watch_items": 2, "source_documents": 41,
  "security_events": 2, "alerts": 1, "runs": 1 }
```

The dry-run alert body is printed in the uvicorn log — look for the
`EMAIL DRY-RUN` line.

---

## 5. Public API (V1)

| Method | Path                  | Purpose                                                |
|--------|-----------------------|--------------------------------------------------------|
| GET    | `/v1/healthz`         | Liveness probe.                                        |
| GET    | `/v1/wire-catalog`    | Proxy of Anakin `GET /v1/holocron/catalog`, 24 h cache.|
| POST   | `/v1/onboard`         | Upsert user + replace watchlist + replace source cfg.  |
| POST   | `/v1/runs/trigger`    | Force a run for one user (`X-Demo-Token` required).    |

### `POST /v1/onboard`

```json
{
  "email": "ash@example.com",
  "dependencies": [
    { "ecosystem": "npm",  "name": "lodash" },
    { "ecosystem": "pypi", "name": "requests" }
  ],
  "source_config": {
    "families": {
      "structured_intel": { "enabled": true,  "sources": ["osv", "nvd"] },
      "high_value_urls":  { "enabled": false, "urls": [] },
      "agentic_search":   { "enabled": false },
      "social_media":     { "enabled": false, "wire_platform_slugs": [] },
      "news":             { "enabled": false, "wire_platform_slugs": [] },
      "blogs":            { "enabled": false, "wire_platform_slugs": [] }
    },
    "wire_defaults": "all_enabled_except_auth_required"
  }
}
```

### `POST /v1/runs/trigger`

```bash
curl -X POST http://localhost:8000/v1/runs/trigger \
  -H "Content-Type: application/json" \
  -H "X-Demo-Token: changeme" \
  -d '{ "user_id": "u_01..." }'
```

Returns the freshly-written `runs[]` record (incl. `stats` and `error`).

---

## 6. Config (`backend/.env`)

| Key                              | Default                       | Purpose                                  |
|----------------------------------|-------------------------------|------------------------------------------|
| `ANAKIN_API_KEY`                 | _empty_                       | Required to hit any Anakin endpoint.     |
| `ANAKIN_BASE_URL`                | `https://api.anakin.io/v1`    | Override only for staging.               |
| `EMAIL_DRY_RUN`                  | `true`                        | Log alerts instead of sending.           |
| `SENDGRID_API_KEY`               | _empty_                       | Required if dry-run is off. "Mail Send" scope. |
| `EMAIL_FROM`                     | _empty_                       | Required if dry-run is off. Verified Single Sender / domain identity in SendGrid. |
| `DEMO_TRIGGER_TOKEN`             | `changeme`                    | Header on `/v1/runs/trigger`.            |
| `DATA_FILE`                      | `backend/data/store.json`     | JsonStore path.                          |
| `RUN_INTERVAL_MINUTES`           | `60`                          | APScheduler interval.                    |
| `INGEST_CONCURRENCY`             | `5`                           | httpx semaphore for Anakin calls.        |
| `ANAKIN_POLL_INTERVAL_SECONDS`   | `3.0`                         | Wire / URL Scraper poll cadence.         |
| `ANAKIN_POLL_MAX_SECONDS`        | `120.0`                       | Max wait per Anakin job.                 |
| `WIRE_CATALOG_TTL_SECONDS`       | `86400`                       | Wire catalog cache TTL.                  |

---

## 7. Layout

```
backend/
  app/
    main.py                # FastAPI + APScheduler lifespan
    config.py              # pydantic-settings
    api/
      health.py
      onboard.py
      wire_catalog.py
      runs.py
    schemas/               # Pydantic request/response models
    services/
      anakin/              # client.py + wire / url_scraper / agentic / search / crawl / structured_intel
      pipeline/            # ingest -> normalize -> match -> cluster -> score -> alert
      email_sender.py
    store/
      json_store.py        # file-locked atomic JSON repo (the migration boundary)
      models.py            # Pydantic record models
      ids.py               # ULID helpers
    queue/
      celery_app.py        # eager Celery
      tasks.py             # run_for_user, enqueue_hourly_runs
      scheduler.py         # APScheduler bootstrap
  data/
    store.json             # the dummy DB
  scripts/
    smoke.py               # end-to-end smoke test
```

---

## 8. The pipeline (per-user, hourly)

```
ingest_all  ->  normalize_docs  ->  match_to_watchlist  ->
cluster_into_events  ->  score_events  ->  dispatch_alerts
```

1. **Ingest** — fan-out across enabled families.
   - Structured intel (OSV / NVD) — free, deterministic, the V1 workhorse.
   - URL Scraper — batch up to 10 of `high_value_urls.urls`.
   - Agentic search — one prompt per run scoped to the watchlist.
   - Wire — dynamic action discovery via `/v1/holocron/search`.
2. **Normalize** — write to `source_documents`; dedupe on
   `sha256(text)` over the last 24 h.
3. **Match** — case-insensitive word-boundary regex on watch item name +
   aliases; ecosystem-tag bonus.
4. **Cluster** — deterministic event id `se_<sha256(canonical_dep|day)[:24]>`;
   one event per `(dep, day)` bucket.
5. **Score** — severity 0-100 (RCE / auth bypass / supply chain / CVE
   regex bumps); confidence 0-100 (source family weight + corroboration).
6. **Alert** — Critical & confidence ≥ 70 OR High & confidence ≥ 75 →
   email (or dry-run log). Idempotent on `(user_id, event_id)`.

All steps persist their outputs to `store.json`, so a run is fully
inspectable after the fact:

```powershell
.\.venv\Scripts\python.exe -c @"
import json
print(json.dumps(json.load(open(r'backend\data\store.json'))['security_events'], indent=2))
"@
```

---

## 9. Out of scope (V1)

- Auth, teams, API keys (V2 per PRD §17).
- Slack / SMS / on-call channels.
- Hashed watchlists / aggregated telemetry (V2 / V3 in PRD §17).
- Per-action toggles inside a Wire catalog.
- Real database. **JSON file is intentional**; `JsonStore` is the
  migration boundary to Postgres.

---

## 10. Sibling docs

- [`SECURITY_ALERTS_PRD.md`](../SECURITY_ALERTS_PRD.md)
- [`PLATFORM_FLOW.md`](../PLATFORM_FLOW.md)
- [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md)
- [`wire-platforms.txt`](../wire-platforms.txt)

Doc bundle `1.0` — bump together when shapes change.
