# Security Alerts Copilot — Implementation Plan (V1)

**Doc bundle:** `1.0` (peers: [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md), [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md), [`wire-platforms.txt`](./wire-platforms.txt)).

Goal: a **clean, minimal** V1 that fulfils the flow in [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) — user submits email + dependencies + source preferences → cron every hour → email on high-confidence matches. Frontend is **flow-only**; backend carries the weight.

---

## 1) Tech stack (locked, hackathon-grade)

| Layer | Choice | Why |
|------|--------|-----|
| Backend runtime | **Python 3.11 + FastAPI** | Simple, async, batteries-included, fastest to ship. |
| “Database” (V1) | **JSON file in repo** (`backend/data/store.json`), accessed via a tiny repo layer with a file lock. | Zero infra. Swap for Postgres later behind the same repo interface. |
| Job queue | **Celery + Redis** (Celery worker + Celery Beat for scheduling) | Standard Python stack; clean retries/backoff and hourly cron. |
| Cron / scheduler | **Celery Beat**, single hourly task that fans out one job per user. | No OS cron needed. |
| Email | **Gmail SMTP** via `smtplib` + a **Gmail App Password** (free) | No paid provider, no domain setup; perfect for demo. |
| Anakin | **HTTP client (`httpx`)** wrappers for Wire / Agentic Search / Crawl / URL Scraper / Browser API | Single API key, async-friendly. |
| Frontend | **Next.js (App Router) + Tailwind**, no auth in V1 | Quick wizard; flow-only. |
| Hosting (optional) | Backend on **Render / Fly.io / Railway**; frontend on **Vercel**; **Redis** as managed add-on. Locally: `redis-server` + `uvicorn` + `celery` + `next dev`. | Zero-ops for hackathon. |
| Secrets | Single `.env` per environment | Simplicity. |

> When V1 grows up, the only meaningful migrations are **JSON → Postgres** and **Gmail SMTP → Resend/Postmark**. Everything else stays.

---

## 2) Backend — system shape

```
                      +-----------------------------+
                      |       Frontend (Next)       |
                      |   Onboarding / Save flow    |
                      +--------------+--------------+
                                     |
                                     v
+------------------------------------------------------------------+
|                       FastAPI service                            |
|  POST  /v1/onboard         upsert user + watchlist + source_cfg  |
|  GET   /v1/wire-catalog    cached list for UI checklist          |
|  POST  /v1/runs/trigger    (demo) force a run for one user       |
|  GET   /v1/healthz                                               |
+--------+--------------------------------+------------------------+
         |                                |
         |                                v
         |                  +--------------------------------+
         |                  |   Celery Beat (every 1 hour)   |
         |                  |   enqueues run jobs per user   |
         |                  +----------------+---------------+
         |                                   |
         v                                   v
+------------------+              +----------------------------+
|  store.json      |<------------>|     Celery Worker(s)       |
|  (file-locked)   |              |  ingest -> normalize ->    |
|                  |              |  match -> cluster -> score |
+------------------+              |  -> email alert            |
                                  +--------------+-------------+
                                                 |
                                                 v
                                +--------------------------------+
                                |  Anakin: Wire / Crawl / URL    |
                                |  Scraper / Browser / Agentic   |
                                +--------------------------------+
                                                 |
                                                 v
                                  +-----------------------------+
                                  |   Gmail SMTP (smtplib)      |
                                  +-----------------------------+
```

---

## 3) “Data model” — JSON-as-DB (V1)

One file: `backend/data/store.json`. Loaded into a Pydantic-typed in-memory model on startup, written back atomically (temp file + `os.replace`) under a lock.

```json
{
  "users": {
    "u_01HXY...": {
      "id": "u_01HXY...",
      "email": "ash@example.com",
      "created_at": "2026-05-10T07:00:00Z"
    }
  },
  "watch_items": {
    "wi_01HXY...": {
      "id": "wi_01HXY...",
      "user_id": "u_01HXY...",
      "ecosystem": "npm",
      "name": "lodash",
      "raw_input": "lodash@^4.17.21",
      "aliases": [],
      "version_spec": "^4.17.21",
      "created_at": "2026-05-10T07:00:00Z"
    }
  },
  "source_configs": {
    "u_01HXY...": {
      "user_id": "u_01HXY...",
      "config": { "...": "shape from PLATFORM_FLOW §5" },
      "updated_at": "2026-05-10T07:00:00Z"
    }
  },
  "source_documents": {
    "sd_01HXY...": {
      "id": "sd_01HXY...",
      "url": "https://...",
      "publisher": "GitHub",
      "fetched_at": "2026-05-10T07:05:00Z",
      "content_hash": "sha256:...",
      "text": "...",
      "meta": { "family": "wire" }
    }
  },
  "security_events": {
    "se_01HXY...": {
      "id": "se_01HXY...",
      "title": "Critical vuln in lodash X.Y.Z",
      "summary": "...",
      "status": "confirmed",
      "severity": 86,
      "confidence": 78,
      "first_seen": "2026-05-10T07:05:00Z",
      "last_updated": "2026-05-10T07:10:00Z"
    }
  },
  "event_signals": [
    {
      "event_id": "se_01HXY...",
      "source_document_id": "sd_01HXY...",
      "family": "wire",
      "weight": 80
    }
  ],
  "relevance_matches": [
    {
      "event_id": "se_01HXY...",
      "watch_item_id": "wi_01HXY...",
      "score": 92,
      "reason": "exact name match + version overlap"
    }
  ],
  "alerts": {
    "al_01HXY...": {
      "id": "al_01HXY...",
      "user_id": "u_01HXY...",
      "event_id": "se_01HXY...",
      "severity": 86,
      "confidence": 78,
      "channel": "email",
      "state": "sent",
      "payload": { "subject": "...", "body": "..." },
      "created_at": "2026-05-10T07:11:00Z"
    }
  },
  "runs": [
    {
      "id": "rn_01HXY...",
      "user_id": "u_01HXY...",
      "started_at": "...",
      "finished_at": "...",
      "stats": { "docs": 12, "events": 3, "alerts_sent": 1 },
      "error": null
    }
  ],
  "wire_catalog_cache": {
    "fetched_at": "2026-05-10T00:00:00Z",
    "items": [{ "slug": "github", "name": "GitHub", "domain": "github.com", "category": "developer-tools", "auth_required": false }]
  }
}
```

**Repo layer (single class):** `JsonStore` exposes `users.upsert(...)`, `watch_items.replace_for_user(...)`, `events.upsert(...)`, etc. All mutations go through one `with self._lock:` block then `flush()`.

> Future (V2): swap `JsonStore` for `PostgresStore` implementing the same methods. PRD §17 + [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) **Future: hashed dependencies** still apply.

---

## 4) Backend — public API (V1)

FastAPI, JSON in/out, Pydantic models for validation.

### `POST /v1/onboard`

Request:
```json
{
  "email": "ash@example.com",
  "dependencies": [
    { "ecosystem": "npm",      "name": "lodash" },
    { "ecosystem": "pypi",     "name": "requests" },
    { "ecosystem": "software", "name": "nginx" }
  ],
  "source_config": { "...": "shape from PLATFORM_FLOW §5" }
}
```
Response:
```json
{ "ok": true, "user_id": "u_01HXY..." }
```
Behavior:
- Upsert user by email.
- **Replace** watch items for that user (simple V1 strategy).
- **Replace** the user’s `source_config`.

### `GET /v1/wire-catalog`

- Returns `{ items: [{ slug, name, domain, category, auth_required }] }`.
- Server-side **24 h cache** of Anakin `GET /v1/holocron/catalog`.
- Display labels in [`wire-platforms.txt`](./wire-platforms.txt) are advisory; **slugs are authoritative from the API**.

### `POST /v1/runs/trigger`

- Body: `{ "user_id": "u_..." }`. Header: `X-Demo-Token: <DEMO_TRIGGER_TOKEN>`.
- Enqueues a Celery `run_for_user` task immediately. Used in the demo.

### `GET /v1/healthz`

- Returns `{ ok: true }`.

> No auth in V1. Real auth lands in V2 (PRD §17, [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) §6).

---

## 5) Backend — pipeline (per user, hourly)

Each hourly tick is **one Celery task per user**, fanning out to per-family ingest sub-tasks.

1. **Plan** — load that user’s `source_config` and `watch_items`.
2. **Ingest** — call Anakin per enabled family:
   - **Wire actions** for enabled platform slugs.
   - **Crawl / URL Scraper** for `high_value_urls`. Use `useBrowser: true` if flagged or after a 403/timeout.
   - **Agentic search** rate-capped (`max_runs_per_day`) with a watchlist-scoped prompt.
   - **Structured intel** (OSV / NVD) via plain `httpx` GETs.
3. **Normalize** — write to `source_documents` (URL, publisher, timestamp, text, hash). Skip if `content_hash` already seen recently.
4. **Match** — for each new doc, candidate-match against `watch_items`:
   - exact + alias match on tokenized text
   - simple fuzzy / edit-distance fallback
   - V1 stays deterministic — no embeddings.
5. **Cluster into events** — same matched dependency + close in time + overlapping titles → same event id.
6. **Score** — severity + confidence using rules in [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md) §13:
   - severity bumped by impact keywords (RCE, auth bypass, leak, supply chain), CVE presence
   - confidence boosted by independent corroborating sources and high-weight families (Wire, official advisories)
7. **Alert** — apply policy in PRD §14:
   - **Critical** & confidence ≥ 70 → email immediately
   - **High** & confidence ≥ 75 → email immediately
   - Lower → write to JSON, no email in V1
8. **Persist** — events, signals, matches, alerts, run stats.

### Pseudocode (Python)

```python
@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def run_for_user(self, user_id: str) -> dict:
    user  = store.users.get(user_id)
    watch = store.watch_items.by_user(user_id)
    cfg   = store.source_configs.by_user(user_id)

    docs       = ingest_all(cfg, watch)             # async fan-out under the hood
    candidates = match_to_watchlist(docs, watch)
    events     = cluster_into_events(candidates)
    scored     = score_events(events)

    sent = 0
    for ev in scored:
        store.events.upsert(ev)
        if should_alert(ev):
            send_email_alert(user, ev)
            sent += 1

    return {"docs": len(docs), "events": len(scored), "alerts_sent": sent}
```

---

## 6) Backend — scheduling (Celery)

- **Celery Beat** schedule:
  - `enqueue_hourly_runs` — every 60 min:
    ```python
    for u in store.users.all():
        run_for_user.delay(u.id)
    ```
- Worker concurrency: start with **5**.
- Retries: **3**, exponential backoff (Celery defaults are fine).
- Persistent failures: capture in `runs[].error`.
- Respect Anakin rate limits inside the ingest layer (e.g. `httpx` semaphore + simple bucket).

---

## 7) Backend — email (Gmail SMTP, free)

V1 uses a personal/throwaway Gmail with an **App Password** (works with 2FA on, no domain or paid provider needed).

```python
import smtplib, ssl
from email.message import EmailMessage

def send_email(to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM            # e.g. "alerts.demo@gmail.com"
    msg["To"]   = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
        s.send_message(msg)
```

- Subject: `[CRITICAL] <package> — <short title>`.
- Body: title, severity, confidence, affected items, 3 source links, suggested action.
- Update `alerts.state` to `sent` / `failed`.

> Demo fallback: if `EMAIL_DRY_RUN=true`, print the rendered email to logs instead of sending — useful when you don’t want to spam during recording.

---

## 8) Config & secrets

`.env` (loaded via `pydantic-settings`):

```
ANAKIN_API_KEY=...
REDIS_URL=redis://localhost:6379/0
GMAIL_USER=alerts.demo@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_FROM=alerts.demo@gmail.com
EMAIL_DRY_RUN=false
DEMO_TRIGGER_TOKEN=changeme
DATA_FILE=backend/data/store.json
```

---

## 9) Backend — folder layout (Python)

```
backend/
  app/
    main.py                # FastAPI factory + uvicorn entrypoint
    api/
      onboard.py
      wire_catalog.py
      runs.py
      health.py
    schemas/               # Pydantic request/response models
      onboard.py
      catalog.py
    services/
      anakin/
        client.py          # shared httpx client + auth header
        wire.py
        crawl.py
        url_scraper.py
        browser.py
        agentic.py
      pipeline/
        ingest.py
        normalize.py
        match.py
        cluster.py
        score.py
        alert.py
      email_sender.py      # Gmail SMTP wrapper
    store/
      json_store.py        # JsonStore class (file-locked I/O)
      models.py            # Pydantic record models
    queue/
      celery_app.py        # Celery init + Beat schedule
      tasks.py             # run_for_user, enqueue_hourly_runs
    config.py              # pydantic-settings
  data/
    store.json             # the dummy DB (gitignored or seeded)
  pyproject.toml           # or requirements.txt
  .env.example
  README.md
```

**Run locally:**
```
# 1. Redis (separate terminal)
redis-server

# 2. API
uvicorn app.main:app --reload --port 8000

# 3. Worker
celery -A app.queue.celery_app worker --loglevel=INFO --concurrency=5

# 4. Beat (hourly scheduler)
celery -A app.queue.celery_app beat --loglevel=INFO
```

---

## 10) Frontend — flow only (no polish)

Single-page wizard, 3 steps. Tailwind only, no design system.

### Step 1 — Email + dependencies
- Email input.
- Textarea for raw dependencies (one per line) **or** paste of `package.json` / `requirements.txt`.
- Client-side parse → `[{ ecosystem, name }]` (default `software` if unknown).

### Step 2 — Source preferences
- Top-level toggles: Social, News, Blogs, High-value URLs, Agentic search, Structured intel — **all on**.
- Below each (when expanded), a **Wire platforms checklist** fed by `GET /v1/wire-catalog`. **All checked by default.**
- Free-text **Add custom URLs** inside *High-value URLs*.
- Save → `POST /v1/onboard`.

### Step 3 — Confirmation
- “You’re all set. We’ll check every hour and email **{email}** on high-confidence matches.”
- **Send me a test alert** button → `POST /v1/runs/trigger` for demo.

### Pages

```
/            -> /onboard
/onboard     -> 3-step wizard
/onboarded   -> confirmation + test trigger
```

No login, no dashboard in V1.

---

## 11) Build order (suggested)

1. **Bootstrap repo** — `pyproject.toml`, FastAPI app, `JsonStore`, `data/store.json`.
2. `POST /v1/onboard` end-to-end (no pipeline yet).
3. Frontend wizard talking to onboard API.
4. **Anakin client wrappers** (Wire, agentic, crawl, URL scraper) using `httpx`.
5. **Pipeline** (ingest → match → cluster → score) for **one user, one source family** — start with structured intel (OSV/NVD) + Wire dev-tools (GitHub/PyPI/npm).
6. Gmail SMTP `send_email` + alert policy.
7. **Celery worker** + `run_for_user` task.
8. **Celery Beat** hourly schedule.
9. `GET /v1/wire-catalog` proxy with 24 h cache.
10. `POST /v1/runs/trigger` + “Send me a test alert” button.
11. Logging, lightweight metrics counters in `runs[].stats`.

---

## 12) Out of scope (V1)

- Auth, teams, API keys (V2 per PRD §17).
- Slack / Teams / SMS / on-call channels.
- Hashed watchlists / aggregated telemetry (V2/V3 in PRD §17).
- Per-action toggles inside a Wire catalog.
- Dashboard / alert history UI.
- Real database. **JSON file is intentional for V1**; the `JsonStore` interface is the migration boundary to Postgres.

---

*Doc bundle `1.0` — Implementation plan (peers: [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md), [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md), [`wire-platforms.txt`](./wire-platforms.txt))*
