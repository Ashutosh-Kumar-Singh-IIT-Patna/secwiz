# Security Alerts Copilot — Platform Flow

**Doc bundle:** `1.0` (keep in sync with [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md) and [`wire-platforms.txt`](./wire-platforms.txt)).

| Artifact | Role |
|----------|------|
| [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md) | Scope, FR/NFR, scoring, alert policy, roadmap. |
| This file | User journey, source families, Wire checklist wiring, hourly pipeline, future privacy & telemetry. |
| [`wire-platforms.txt`](./wire-platforms.txt) | Human index of Wire **display names, domains, categories**; production catalog slugs from Wire API. **Importers: skip any line whose first non-whitespace character is `#`.** |

This document describes the end-to-end user journey, configurable **trusted sources**, how **Wire** fits in (platform index: [`wire-platforms.txt`](./wire-platforms.txt)), the **scheduled check** loop, and **future extensions**.

---

## 1) Onboarding: identity + dependency watchlist

**Inputs**

| Field | Description |
|--------|-------------|
| **Email** | Primary contact for alerts (V1). |
| **Dependencies** | Mixed list the user cares about: software products, CLI tools, SaaS names, and packages across ecosystems (npm, PyPI, Go modules, etc.). Optional: paste `package.json` / `requirements.txt` / lockfile snippets for bulk import. |
| **Aliases (optional)** | Map alternate names to one canonical entity (e.g. `lodash` ↔ package display name) to improve matching. |

**Behavior**

- Validate email format; send one-time confirmation if you add double opt-in later (not required for hackathon MVP).
- Normalize dependency strings (ecosystem tag, canonical name, optional version constraint).
- Store watchlist server-side keyed by user/session until auth exists.

---

## 2) Source configuration: what we monitor

The user chooses **which source families** to enable. **Default: all families ON** and, within Wire-backed subsections, **all platforms ON** unless the user opts out.

Wire-backed sources use Anakin **Wire (Holocron)** actions where available — **higher structured accuracy** than generic crawl-only paths for those domains.

### 2.1 Source families (top level)

| Family | Role in product | Implementation notes |
|--------|------------------|----------------------|
| **Social media** | Early chatter, influencer posts, maintainer threads | Wire where catalog exists; otherwise Browser API / URL Scraper for public pages you allow. |
| **News channels** | Wire services, press, trade publications | Wire for listed outlets; optional generic news URLs or RSS in “custom feeds” (future). |
| **Blog / long-form** | Deep dives, postmortems, vendor blogs | Wire (e.g. Medium, Substack, DEV) + user-added blog URLs. |
| **Official & high-value URLs** | Advisories, changelogs, registry pages, GitHub Security tab | User-pinned URLs + system-suggested defaults per dependency (PyPI/npm/GitHub project pages). Wire where platform is in catalog. |
| **Agentic search** | Cross-web research when a signal fires or on schedule | `POST /v1/agentic-search` with prompts scoped to watchlist + time window; results feed correlation, not raw spam. |
| **CVE / advisory feeds (recommended add)** | Ground truth when available | OSV, NVD, vendor RSS — often **not** Wire; use Crawl / URL Scraper / scheduled fetch. List under “Structured intel” in UI even if not Wire. |
| **Package registries (metadata)** | New versions, yanked packages, maintainer changes | **npm** and **PyPI** appear in Wire catalog; also use registry APIs directly for freshness where cheap. |

*Anything missed above can be folded into **“Custom URLs & feeds”** (user-supplied list) in a later iteration.*

### 2.2 Wire subsection (per family)

When a family supports Wire, the UI shows a **checklist of platforms** loaded from [`wire-platforms.txt`](./wire-platforms.txt) (name, domain, category). User toggles per platform. **Default: all selected.**

**Relevance hint for this product:** not every Wire platform is security-relevant. Recommended **default subgrouping in the UI** (still backed by the same file):

| UI group | Typical Wire examples (see full file) | Why it matters for vuln/breach alerts |
|----------|----------------------------------------|--------------------------------------|
| **Developer & supply chain** | GitHub, PyPI, npm, Stack Overflow, Product Hunt, AlternativeTo, Hacker News, DEV Community | Direct package/repo signals and community noise. |
| **News & wire services** | Reuters, AP News, BBC, CNBC, The Guardian, TechCrunch, Google News, Nikkei Asia, South China Morning Post, Al Jazeera, Economic Times | Fast, credible reporting. |
| **Social & forums** | Reddit, YouTube, Waalaxy (auth), Substack (content), Medium | Early discussion; higher noise — tune confidence down unless corroborated. |
| **Research & reference** | arXiv, Semantic Scholar, PubMed, Wikipedia | Lower priority unless dependency is research/science stack. |

**Auth-required Wire catalogs:** some entries in [`wire-platforms.txt`](./wire-platforms.txt) are marked for authentication flows. For Security Alerts V1, either hide them, show as “connect identity in Wire dashboard,” or disable by default.

**Accuracy note (product copy for users):**  
*“Sources backed by Wire typically return higher-accuracy structured data for supported sites. Other sources use general web collection and may have more false positives.”*

---

## 3) Save and exit

- User clicks **Save preferences**.
- Persist: `email`, normalized `watchlist`, `source_config` (families + Wire platform IDs/slugs + custom URLs).
- User can **close the site**; no session required to stay open.

---

## 4) Backend: scheduled checks and alerting

### 4.1 Cadence

- **Cron (or queue scheduler): every 1 hour** per user (or per global ingest with per-user fan-out — implementation detail).
- Stagger jobs to respect API rate limits (Anakin + registries).

### 4.2 Per-run pipeline (conceptual)

1. **Ingest** — For each enabled source family:
   - Wire: dispatch allowed actions for enabled platforms (search/list/read patterns per catalog).
   - High-value URLs: Crawl or URL Scraper (and Browser API if blocked).
   - Agentic search: bounded prompts (e.g. “incidents in last 24h affecting: …”) on a subset of runs to control cost.
2. **Normalize** — Extract plain text, URLs, timestamps, publisher.
3. **Match** — Link content to watchlist items (names, aliases, ecosystems).
4. **Correlate** — Cluster duplicates; merge Wire signals with non-Wire signals.
5. **Score** — Confidence + severity (see PRD [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md)).
6. **Notify** — If **high confidence** (threshold from PRD, e.g. Critical/High with confidence ≥ threshold), **send email** immediately. Lower confidence: optional digest or in-app only (V1 can be email-only for simplicity).

### 4.3 Email content (minimum)

- Title + one-line impact  
- Affected dependency names  
- Severity + confidence  
- 2–3 source links (Wire + official if available)  
- Suggested next steps (upgrade, isolate, verify)

---

## 5) Configuration artifact (example shape)

Illustrative JSON for stored `source_config` (adjust to your DB):

```json
{
  "families": {
    "social_media": { "enabled": true, "wire_platform_slugs": ["reddit", "youtube"] },
    "news": { "enabled": true, "wire_platform_slugs": ["reuters", "techcrunch", "hackernews"] },
    "blogs": { "enabled": true, "wire_platform_slugs": ["medium", "substack", "dev-community"] },
    "high_value_urls": {
      "enabled": true,
      "urls": ["https://github.com/org/repo/security", "https://pypi.org/p/mylib/"]
    },
    "agentic_search": { "enabled": true, "max_runs_per_day": 4 },
    "structured_intel": { "enabled": true, "sources": ["osv", "nvd"] }
  },
  "wire_defaults": "all_enabled_except_auth_required"
}
```

Slug names above are illustrative; **map from** [`wire-platforms.txt`](./wire-platforms.txt) to your internal IDs (e.g. catalog slug from Wire API `GET /v1/holocron/catalog`).

---

## 6) Future extensions

| Extension | Description |
|-----------|-------------|
| **Auth on platform** | User accounts, teams, API keys; **enterprise isolation** (tenant-scoped watchlists, audit logs, SSO). |
| **More alert channels** | Slack, Microsoft Teams, Discord, **phone/SMS/on-call** paging (PagerDuty, Opsgenie, Twilio). |
| **Reporting / on-call routing** | Configure **who** gets which severity (rotation, escalation policy, backup contact). |
| **Finer Wire granularity** | Per-action toggles inside a catalog after discovery via `GET /v1/holocron/catalog/{slug}`. |
| **Feedback loop** | “Useful / not useful” on alerts to tune confidence by source family. |
| **Hashed dependencies at rest** | Store watchlist identifiers as **cryptographic hashes** (not reversible plaintext in the primary DB). Reduces exposure if the DB is copied or mis-scoped. See note below. |
| **Aggregated dependency intelligence** | Over time, the platform accumulates a **rich signal of which dependencies are watched, how often they appear in incidents, and regional / industry cohorts** (when disclosed). Properly aggregated and governed, this becomes a **strategic dataset**: adoption proxies, “blast radius” heatmaps, and early-warning baselines — see note below. |

### Future: aggregated dependency usage intelligence

**Opportunity:** Many users subscribing to the same package names, ecosystems, and version bands produces **population-level** insight: what the ecosystem actually runs, what gets alerted on first, and how severity correlates with source type (Wire vs generic crawl).

**Product directions (examples):**

- **Public or licensed benchmarks** — “Top 500 npm packages by watchlist frequency,” “Time-to-first-alert after advisory publish,” co-occurrence graphs (packages often watched together).  
- **Risk research** — cohort-level correlation between dependency X and incident class Y (never individual customer attribution without contract).  
- **Better defaults** — suggest watchlists, source bundles, and confidence thresholds from aggregate behavior.

**Governance (non-negotiable):**

- Ship **only aggregated or k-anonymized** statistics; enforce **minimum cohort size** before publishing a metric.  
- Clear **terms + opt-in** for any commercial reuse of telemetry; enterprise **opt-out** for telemetry that leaves the tenant boundary.  
- Align with **hashed watchlist at rest**: aggregation keys can be **global hash of canonical dependency** (no tenant secret) for cross-tenant counts, or tenant-scoped analytics only — pick one model and document it in security reviews.

---

### Future: hashed dependencies in the database

**Goal:** Limit how much of a user’s stack is readable from a database dump alone.

**Approach (conceptual):**

- Normalize each dependency to a canonical string (e.g. `ecosystem:name@version_constraint` or stable JSON canonicalization).
- Persist **`HMAC-SHA256(tenant_secret, canonical_string)`** per watch item (or per user + item) so hashes are not comparable across tenants without the key.
- Matching pipeline: when ingesting external text, compute the same HMAC over candidate extractions (normalized the same way) and join on hash — or use a **separate encrypted store / KMS** for plaintext only where matching requires it, with strict access boundaries (enterprise).

**Trade-offs:** Duplicates detection, admin support (“what did I subscribe to?”), and some analytics become harder without a companion **encrypted** column or envelope encryption — document as an **enterprise** toggle, not required for V1 hackathon MVP.

---

## 7) Related documents

- [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md) — product requirements, scoring, non-goals, Anakin capability mapping.  
- [`wire-platforms.txt`](./wire-platforms.txt) — **canonical human index** of Wire-supported platforms for checklist UI; **resolve slugs** via Wire `GET /v1/holocron/catalog` in production (names in the `.txt` file are display labels, not guaranteed API slugs).

---

*Doc bundle `1.0` — Security Alerts Copilot platform flow (see [`SECURITY_ALERTS_PRD.md`](./SECURITY_ALERTS_PRD.md), [`wire-platforms.txt`](./wire-platforms.txt))*
