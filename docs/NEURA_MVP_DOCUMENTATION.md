# Neura MVP – Technical Documentation

## 1) Project Overview

- **Project Name:** Neura (MVP – Cash Flow Intelligence)
- **Completion Date:** Jan 7, 2026
- **Tech Stack:** FastAPI (Python 3.10+), Async SQLAlchemy, Alembic, HTTPX/AIOHTTP, SlowAPI (rate limiting)
- **Database:** PostgreSQL 14+ (async driver: `asyncpg`)
- **Integrations:** Xero (official SDK), OpenAI (text-first insights)
- **Summary:**
  - Neura connects to a company’s Xero data, computes core cash metrics (runway, pressure) and generates plain-English insights with concrete next steps. The MVP focuses on clarity and action: a user connects Xero and quickly sees cash runway, a traffic-light cash pressure, and top 1–3 insights they can acknowledge or mark done.

---

## 2) Features

- **User Authentication**
  - Signup, Login, Refresh, Logout, Change Password
  - JWT access/refresh tokens with rotation and blacklist on logout
  - Rate limiting for sensitive endpoints

- **Admin Role for Feedback Visibility**
  - Admin-only access to view organization feedback summaries and details

- **Xero Integration**
  - OAuth 2.0 connect/callback/status/disconnect
  - Stable token lifecycle: auto refresh/rotation and validation
  - Financial data sync with caching and fetchers (Balance Sheet, P&L, AR/AP, Trial Balance)

- **Insights & Metrics**
  - Calculations for: Cash Runway (months), Cash Pressure (GREEN/AMBER/RED with confidence), Leading Indicators (AR/AP), Profitability, Upcoming Commitments
  - AI layer to produce insight text: title, summary, why it matters, recommended actions, confidence level
  - Insight engagement: acknowledge / mark as done
  - Top insights (default 1–3) with deterministic ranking

- **Dashboard Snapshot**
  - Persisted `CalculatedMetrics` snapshot for fast loads
  - Includes `calculated_at` for trust (“Last updated”)

- **Settings**
  - Account email, Xero integration status (validated), last sync time, logout

- **Global Error Handling & Rate Limiting**
  - Consistent error responses and safe messaging
  - Endpoint-level limits via SlowAPI

---

## 3) Architecture Overview

- **Workflow (High-Level)**

```mermaid
flowchart TD
    A[User Authenticates] --> B[Connect Xero]
    B --> C[OAuth Callback -> Store Tokens]
    C --> D[Trigger Sync]
    D --> E[Fetch Financial Data (SDK + Cache)]
    E --> F[Calculate Metrics (Runway, Pressure, etc.)]
    F --> G[Persist Snapshot (CalculatedMetrics)]
    G --> H[Generate AI Insights]
    H --> I[Upsert Insights + Engagement State]
    I --> J[Dashboard/API Returns Snapshot + Top Insights]
```

- **Module Structure**
  - `app/auth/`: JWT authentication, rate limits, user profile
  - `app/integrations/xero/`: OAuth flow, token service, SDK client, data fetchers/cache
  - `app/insights/`: Calculators, services, AI generator, sync background task, routers/schemas
  - `app/settings/`: Aggregated settings endpoint (account + integration + last sync)
  - `app/core/`: Global error handling, shared utilities
  - `app/models/`: SQLAlchemy ORM models for users, orgs, insights, metrics, tokens, feedback

- **Folder Structure** (key items)
```
Neura-MVP/
├── app/
│   ├── main.py                 # FastAPI app/routers
│   ├── config.py               # Settings
│   ├── auth/                   # Auth & rate limit
│   ├── insights/               # Calculations, AI, routers, sync
│   ├── integrations/xero/      # OAuth, SDK, fetchers, cache
│   ├── settings/               # Settings router/schemas
│   ├── models/                 # ORM models
│   └── database/               # Async engine/session, Alembic glue
├── alembic/                    # DB migrations
├── docs/                       # Documentation
└── requirements.txt
```

---

## 4) Database Design (Primary Tables)

- **users**
  - `id (UUID)`, `email (unique)`, `password_hash`, `is_active`, `is_verified`, `role`, timestamps
  - Relationships: `organization_id` (one user ↔ one org in MVP)

- **organizations**
  - `id (UUID)`, `name`, sync status fields (`sync_status`, `sync_step`, `last_sync_error`), timestamps
  - Relationships: `users`, `xero_tokens`, `calculated_metrics`, `insights`

- **xero_tokens**
  - `id (UUID)`, `organization_id`, `access_token`, `refresh_token`, `expires_at`, `xero_tenant_id`, `scope`
  - Used by SDK client to auto-refresh; persisted deterministically

- **calculated_metrics** (one snapshot per org)
  - `id (UUID)`, `organization_id`, `metrics_payload (JSONB)`, `calculated_at`, `data_period_start`, `data_period_end`
  - Convenience numeric columns (e.g., `runway_months`) may be present for querying

- **insights** (current insight set)
  - `id (UUID)`, `organization_id`, `insight_id (unique)`, `insight_type`, `title`, `severity`, `confidence_level`, `summary`, `why_it_matters`, `recommended_actions (JSON)`, `supporting_numbers (JSON)`, `data_notes`, `generated_at`, engagement fields (`is_acknowledged`, `is_marked_done`, timestamps, user refs)
  - Upsert by `(organization_id, insight_id)` to keep the latest version per insight

- **insight_feedback**
  - `id (UUID)`, `organization_id`, `insight_id (nullable)`, `user_id`, `type`, `rating`, `comments`, timestamps
  - Used for admin review and quality iteration

- **token_blacklist / refresh_tokens** (if present)
  - Support secure logout and refresh rotation mechanics

---

## 5) API Documentation (Summary)

- **Auth (`/auth/*`)**
  - `POST /auth/signup` – Create account + org; returns JWTs
  - `POST /auth/login` – Login; returns JWTs
  - `POST /auth/refresh` – Rotate/refresh access token
  - `POST /auth/logout` – Revoke tokens (blacklist); 204
  - `POST /auth/change-password` – Change password; 204
  - `GET /auth/me` – Current user profile

- **Xero Integration (`/integrations/xero/*`)**
  - `GET /integrations/xero/connect` – Start OAuth (auth URL + state)
  - `GET /integrations/xero/callback` – Handle OAuth callback, store tokens
  - `GET /integrations/xero/status` – Validate connection status
  - `POST /integrations/xero/disconnect` – Revoke tokens, clear state
  - `POST /integrations/xero/refresh` – Manual refresh
  - `GET /integrations/xero/sync` – Fetch/cached financial data for a period

- **Insights (`/api/insights/*`)**
  - `GET /api/insights` – Return dashboard payload:
    - `cash_runway` (with `confidence_level`), `cash_pressure`, `leading_indicators`, `profitability`, `upcoming_commitments`
    - Paginated `insights[]` with engagement state (default `limit=3`)
  - `GET /api/insights/{insight_id}` – Single insight detail (regenerates to locate ID)
  - `PATCH /api/insights/{insight_id}` – Update `is_acknowledged` / `is_marked_done`
  - `POST /api/insights/trigger` – Trigger async sync + generation
  - `GET /api/insights/status` – Current sync status/step

- **Settings (`/settings/*`)**
  - `GET /settings` – Aggregated settings: email, Xero status, last sync time

- **Feedback (`/feedback/*` and admin variants)**
  - Submit and list feedback, with admin-only visibility for org-level summaries

---

## 6) Future Improvements (Strategic Roadmap)

- **Historical Insight Timeline & Trends**
  - Persist multiple versions per `insight_id` (or time-series by category) to show change over time.
  - User value: see progress (e.g., runway improving), build trust and habit.
  - Business impact: increases engagement and retention via visible momentum.

- **Lightweight Deltas on Dashboard**
  - Display “Since last sync” deltas (e.g., `Runway: 3.2 months (↑0.3)`).
  - User value: immediate sense of improvement or risk.
  - Low complexity—can leverage `CalculatedMetrics` snapshots.

- **Impact-Aware Insight Ranking**
  - Introduce an `impact_score` to rank by severity → impact → confidence consistently.
  - User value: sharper prioritization; Business: better action rates.

- **Data Quality Signals**
  - Surface “Data quality: Good/Mixed/Low” badges with brief explanations.
  - User value: expectations set without blame; Business: fewer support queries.

- **Two-Factor Authentication (2FA)**
  - Add TOTP-based 2FA to strengthen account security with minimal friction.
  - User value: increased trust; Business: enterprise readiness.

- **Digest Emails**
  - Weekly plain-text summary: runway, pressure, top action.
  - User value: triggers return visits; Business: improves retention.

- **Admin Quality Dashboard**
  - Aggregated feedback metrics and insight performance.
  - User value: internal QA & iteration; Business: faster improvement cycles.

- **Multi-Entity & Team Access (Phase 2)**
  - Support multiple Xero orgs per account and team roles/permissions.
  - User value: scale to accountants or multi-entity SMEs; Business: larger TAM.

- **Deeper Data Ingest (Phase 2)**
  - Deterministic parsing of executive/cashflow reports or bank feeds to improve burn and runway accuracy.
  - User value: improved precision; Business: credibility with finance-savvy users.

- **Performance & Observability**
  - Structured logging with correlation IDs, metrics, tracing.
  - User value: faster, more reliable service; Business: simpler ops at scale.

---

## Appendix – Known Limitations (MVP)

- Runway burn approximates `cash_received`/`cash_spent` from balance sheet deltas (documented in `docs/CALCULATION_LIMITATIONS.md`).
- Insight storage overwrites by `insight_id` (no historical versions).
- Ranking is severity + confidence; impact scoring deferred to keep MVP lean.
- No charts/history; text-first insights per MVP scope.
