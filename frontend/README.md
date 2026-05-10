# Security Alerts Copilot — Frontend

Next.js 14 (App Router) + Tailwind. Single 3-step onboarding wizard
talking to the FastAPI backend. No auth (V1).

## Quickstart

```bash
cd frontend
npm install
cp .env.example .env.local       # adjust if backend isn't on :8000
npm run dev
# → http://localhost:3000
```

The backend must be running:

```bash
cd ../backend
.venv\Scripts\activate          # Windows
python -m uvicorn app.main:app --reload --port 8000
```

## Pages

| Route          | Notes                                                      |
| -------------- | ---------------------------------------------------------- |
| `/`            | Server-side redirect → `/onboard`                          |
| `/onboard`     | Step 1 (email + deps) → Step 2 (sources) → POST /v1/onboard|
| `/onboarded`   | Confirmation + "Send me a test alert" button               |
| `/api/trigger` | Server-only proxy that forwards to `POST /v1/runs/trigger` |

## API integration

| Frontend call               | Backend endpoint                     | Where                      |
| --------------------------- | ------------------------------------ | -------------------------- |
| `api.healthz()`             | `GET  /v1/healthz`                   | (badge / smoke test)       |
| `api.wireCatalog()`         | `GET  /v1/wire-catalog`              | Step 2 platform checklist  |
| `api.onboard(payload)`      | `POST /v1/onboard`                   | Save & finish              |
| `triggerRun(userId)`        | `POST /v1/runs/trigger`              | Onboarded → test trigger   |

CORS is wide-open on the backend (`allow_origins=["*"]`), so direct
browser calls work for the first three. The trigger goes through
`/api/trigger` so the `X-Demo-Token` header lives only on the Next.js
server — never shipped in the browser bundle.

## Env

| Var                      | Used in           | Notes                                    |
| ------------------------ | ----------------- | ---------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | browser           | Where the FastAPI backend is reachable.  |
| `BACKEND_URL`            | server (route)    | Same backend, accessed from Next server. |
| `DEMO_TRIGGER_TOKEN`     | server (route)    | Must match backend's `DEMO_TRIGGER_TOKEN`.|

## Layout

```
frontend/
  app/
    layout.tsx          # shell + backend badge
    page.tsx            # → /onboard
    onboard/page.tsx    # 3-step wizard orchestrator
    onboarded/page.tsx  # confirmation + test trigger
    api/
      trigger/route.ts  # server-only POST /api/trigger proxy
    globals.css
  components/
    Stepper.tsx
    Step1EmailDeps.tsx
    Step2Sources.tsx
  lib/
    api.ts              # typed fetch helpers + ApiError
    parse-deps.ts       # package.json / requirements.txt / freeform parser
    types.ts            # shapes mirroring FastAPI schemas
```
