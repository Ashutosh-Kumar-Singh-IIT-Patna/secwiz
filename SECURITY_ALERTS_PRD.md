# Security Alerts Copilot — PRD

**Doc bundle:** `1.0` (keep in sync with [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) and [`wire-platforms.txt`](./wire-platforms.txt)).

| Artifact | Role |
|----------|------|
| This PRD | Scope, requirements, scoring, roadmap. |
| [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) | User journey, source families, Wire UI checklist, hourly pipeline, future privacy & telemetry. |
| [`wire-platforms.txt`](./wire-platforms.txt) | Human index of Wire platform **display names, domains, categories**; production slugs come from Wire API `GET /v1/holocron/catalog`. Lines starting with `#` are metadata — importers must skip them. |

---

## 1) Product Overview

**Product name:** Security Alerts Copilot  
**One-liner:** Real-time breach and vulnerability intelligence for your exact software stack, with immediate remediation suggestions.

Teams lose critical time between incident disclosure and internal action. Security Alerts Copilot continuously monitors trusted and fast-moving sources, detects relevance to your dependencies, and sends high-confidence, actionable alerts within minutes.

---

## 2) Problem Statement

When a package or software is breached (e.g., token leak, RCE, supply-chain compromise), information appears across scattered channels:

- Official advisories  
- Package registries (PyPI, npm, etc.)  
- Vendor blogs and changelogs  
- Security news  
- Social media chatter  

Teams often track these manually or learn too late. Delay increases blast radius.

---

## 3) Goals

- Detect security-critical events quickly for user-declared software and dependencies.  
- Minimize false positives while still alerting early.  
- Provide **actionable suggestions** (upgrade path, mitigations, priority).  
- Compress MTTA (mean time to awareness).

### Success criteria

- Alert latency: median &lt; 10 minutes from first credible signal.  
- Precision: &gt; 80% “useful alert” rating (user feedback).  
- Time-to-action: user can decide within ~2 minutes using the alert payload.

---

## 4) Non-goals (V1)

- Full SBOM generation or deep scanning from arbitrary source repos.  
- Automated patch deployment.  
- Legal or compliance reporting workflows.  
- Deep malware reverse engineering.

---

## 5) Target users

- Indie hackers / startup CTOs  
- DevOps / SRE engineers  
- Security teams in SMBs  
- Open-source maintainers  

---

## 6) Core use cases

1. User adds packages and services they rely on (watchlist / allowlist).  
2. System detects a breach or vulnerability mention relevant to those items.  
3. User receives an immediate alert with severity and confidence.  
4. User sees suggested remediation and version guidance.  
5. User marks status: acknowledged, in progress, resolved, ignored.

---

## 7) V1 feature scope

### 7.1 Watchlist management

- Add software / package names manually.  
- Bulk import from `requirements.txt` or `package.json` content.  
- Optional aliases (e.g., `requests` ↔ `python-requests`).

### 7.2 Multi-source monitoring

- Official vendor and security pages.  
- Package registry pages and metadata.  
- Security news feeds.  
- Social posts (high-signal accounts / keywords).  
- **Configurable source families** (social, news, blogs, high-value URLs, agentic search, structured intel such as OSV/NVD) — default **all on**; Wire-backed platforms from [`wire-platforms.txt`](./wire-platforms.txt) with higher structured accuracy where applicable. See [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) §2.

**Operational cadence (V1):** scheduled checks **every 1 hour**; email on high-confidence matches — see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) §4.

### 7.3 Event detection and correlation

- Normalize mentions into candidate events.  
- Cluster duplicates from multiple sources.  
- Track event lifecycle: rumor → confirmed advisory → patch released.

### 7.4 Relevance matching

- Match events to the user watchlist (exact, alias, fuzzy / semantic where needed).  
- Version-aware relevance where data is available.

### 7.5 Alerting

- Channels: email and webhook (V1).  
- Severity tiers: Critical / High / Medium / Low.  
- Confidence score and source count on every alert.

### 7.6 Suggested corrections

For each alert:

- Recommended safe version (if known).  
- Immediate mitigations or workarounds.  
- Verify / triage checklist.  
- Suggested urgency SLA.

---

## 8) Why Anakin (capability mapping)

- **Wire (Holocron):** structured actions for supported sites (catalog discovery via `GET /v1/holocron/catalog`); checklist names/domains align with [`wire-platforms.txt`](./wire-platforms.txt).  
- **Agentic search:** investigate and synthesize emerging events quickly (`POST /v1/agentic-search`, poll results).  
- **Crawl API:** multi-page monitoring (docs, changelogs, advisory hubs).  
- **URL Scraper:** single canonical URLs (registry pages, advisories); `useBrowser` / `sessionId` when needed.  
- **Browser API:** full Playwright/Puppeteer control for JS-heavy or protected flows; optional geo, saved sessions, session recording.  
- **Geo / stealth / sessions:** resilience when sources block simple HTTP.  
- **Async jobs and polling:** scalable ingestion and analysis across jobs.

---

## 9) User experience (V1)

### Primary screens

1. **Onboarding** — watchlist entry, alert channel selection.  
2. **Alerts feed** — sorted by severity and recency; confidence badge.  
3. **Alert detail** — what happened, why it affects you, suggested fixes, sources, timeline.  
4. **Watchlist** — add/remove items, alias management.

### Alert card (conceptual schema)

- Headline  
- Affected package or service  
- Severity  
- Confidence  
- Impact summary  
- Suggested fix  
- Sources (clickable)  
- Timestamp  

---

## 10) Functional requirements

| ID | Requirement |
|----|-------------|
| FR1 | User can add, edit, and delete watchlist items. |
| FR2 | System ingests source updates on defined polling intervals (V1 default: **1 hour** — see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) §4). |
| FR3 | System deduplicates and clusters event mentions. |
| FR4 | System scores severity and confidence. |
| FR5 | System generates actionable remediation suggestions. |
| FR6 | System dispatches alerts per user preferences. |
| FR7 | System stores event history and user state transitions. |

---

## 11) Non-functional requirements

- Availability: 99.5% target for MVP (best effort).  
- End-to-end alert latency: &lt; 10 minutes median.  
- Scalable asynchronous processing.  
- Auditability: every alert cites sources.  
- Security: encrypted secrets, minimal PII, signed webhooks where applicable.  
- **Future:** optional storage of dependency identifiers as **HMAC-SHA256 (per-tenant secret, canonical dependency string)** in the primary database so a dump does not reveal plaintext package names; see roadmap **V2** and [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) **Future: hashed dependencies in the database**.

---

## 12) Data model (high level)

- **User**  
- **WatchItem** — name, ecosystem, aliases, optional version constraints *(V1 plaintext or encrypted-at-rest; future: hash-only in primary DB with HMAC + tenant secret, see Platform Flow doc)*  
- **SourceDocument** — URL, publisher, timestamp, content hash  
- **SecurityEvent** — canonical ID, title, summary, status  
- **EventSignal** — source-level evidence linked to an event  
- **RelevanceMatch** — event ↔ watch item with score  
- **Alert** — severity, confidence, channel status, user state  

---

## 13) Scoring framework (V1)

### Severity (0–100)

Inputs: impact language (RCE, auth bypass, credential leak, etc.), exploitability mentions, breadth of affected surface, presence of official advisory or CVE.

| Range | Tier |
|-------|------|
| 80–100 | Critical |
| 60–79 | High |
| 35–59 | Medium |
| &lt; 35 | Low |

### Confidence (0–100)

Inputs: number of independent credible sources, source reputation weighting, agreement across signals, official confirmation flag.

---

## 14) Alert policy

- **Critical** and confidence ≥ 70 → immediate push.  
- **High** and confidence ≥ 75 → immediate push.  
- **Medium** → digest every N hours unless confidence spikes.  
- **Low** → in-app feed only by default (no push).

---

## 15) Risks and mitigations

| Risk | Mitigation |
|------|------------|
| False positives | Source weighting, confidence thresholds, user feedback loop. |
| Missed events | Broaden sources, adaptive keyword expansion. |
| Ambiguous package names | Ecosystem context + aliases. |
| Rate limits / blocks | Retries, backoff, browser fallback (Anakin Browser API). |
| Advice liability | Label as assistant guidance; always attach source proof. |

---

## 16) Metrics

- Detection latency (signal → alert).  
- Alert precision (thumbs up / down).  
- Alerts by severity.  
- MTTA proxy (time to first user open).  
- Watchlist coverage (% of items with active monitoring).  
- **Future (internal / product):** aggregate signals — watchlist frequency per canonical dependency, alert→ack latency by severity — subject to privacy policy and cohort rules (see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) **Future: aggregated dependency usage intelligence**).

---

## 17) Roadmap

**V1 (hackathon)** — Watchlist, ingestion, correlation, scoring, email/webhook alerts, basic remediation text.

**V1.5** — Slack/Discord, richer version intelligence, feedback-driven tuning.

**V2** — Repo-aware dependency sync, incident playbooks, team workflows, policy controls, and **hashed watchlist at rest** (HMAC-SHA256 with per-tenant secret over a canonical dependency string; optional envelope encryption for matching paths that need plaintext — see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md)).

**V3 (data & intelligence)** — **Aggregated dependency usage dataset** (watch frequency, incident co-occurrence, time-to-alert baselines) for benchmarks, research, and product tuning — **k-anonymity / cohort minimums**, explicit consent, enterprise opt-out; see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md) **Future: aggregated dependency usage intelligence**.

---

## 18) Demo narrative (judges)

1. Add a small dependency list.  
2. Ingest or simulate a known recent security event.  
3. Show auto-detected relevance, severity, and confidence.  
4. Open alert detail: suggested fix + source traceability.  
5. Show channel delivery and acknowledgement.  
6. Close: **time-to-awareness compressed from hours to minutes.**

---

*Doc bundle `1.0` — Security Alerts Copilot PRD (see [`PLATFORM_FLOW.md`](./PLATFORM_FLOW.md), [`wire-platforms.txt`](./wire-platforms.txt))*
