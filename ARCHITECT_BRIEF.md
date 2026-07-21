# Architect Brief — Productionizing CNC Plan & Process Pro

**Prepared by:** Vinayak Panchaman (developer/founder)
**Date:** 14 July 2026 (rev. 3 — 21 July 2026: goals list, data inventory incl. thumbnails, starter user-DB schema, module entitlements, admin expansion)
**Purpose:** Everything you need to design the production deployment, subscription system, and release pipeline. I built the application; I need you to design how it runs as a commercial SaaS.

---

## 0. Goals — the checklist this design must satisfy

1. **Trial cohort now:** give the product to ~10 trial companies with login + password. Admin provisions accounts (email) or issues an invite code the company registers with.
2. **Three environments:** dev (my machine) → test/staging (deployed, testers verify) → production (paying users), with CI running the regression suite between them and manual promote to prod.
3. **Real databases:** Postgres (or your recommendation) for all account/business data; object storage for CAD files. Nothing user-generated may live only in the browser or on one disk.
4. **A clear data home for every category** — see the Data Inventory (Section 4). Every row must have a designed home, retention rule, and owner.
5. **STEP files persist:** a customer re-sending the same drawing a month later must open instantly from the user's stored files — no re-upload needed.
6. **Nothing that worked disappears:** produced plans/quotes/estimates are immutable history — dated, reproducible, linked to the exact file version they priced.
7. **Per-user storage quota:** each account stores at least 15–20 STEP files (you propose the MB cap and eviction/upgrade policy).
8. **Operator history:** who did what, when — every analysis, quote, edit, login, device change in a queryable audit log with timestamps.

---

## 1. What the product is

A CNC machining quoting tool for small/medium job-shops. A user uploads a 3D CAD file (STEP format), the engine analyzes the geometry (features, setups, workholding), produces a machining process plan, and prices the job (time estimate × machine/labour rates). Think "DFM + process planning + quoting," India-first (Bengaluru/Chennai/Coimbatore machining clusters), later Europe.

- **Launch target:** 1 August 2026 (tester phase running now).
- **Competitor benchmark:** toolpath.com (Pro $1,500/yr). We undercut ~10× for India SMEs.
- **Companies:** sold in India via Datadelimited (proprietorship, India), later in Europe via Antutive AB (Sweden). Payment/tax setup must eventually support both, India first.
- **Product name:** being finalized (working candidate "QuoteKar"); domain not yet purchased.

## 2. Current architecture (what exists today)

**Monorepo**, branch `v4-web-ui`, GitHub private repo (`vinayakcerti/CNC_codegen-and-Estimation`).

| Layer | Tech | Notes |
|---|---|---|
| Frontend | React 19 + Vite + TypeScript + react-three-fiber (three.js) | SPA, 3D viewer for the part model. Production build ~1.3 MB JS (360 KB gzip), currently one bundle. |
| Backend | Python FastAPI + uvicorn (port 8000) | ~15 endpoints. The heavy ones: `POST /api/analyze`, `/api/strategy`, `/api/weldment` — each takes a STEP file upload and runs CAD analysis. |
| CAD engine | CadQuery / OpenCASCADE (OCCT) | **Hard constraint:** must run inside a conda env (`cnc-cadquery`, via miniforge). Outside `conda run`, OCCT crashes the Python process (DLL context). This dictates how the backend is containerized/serviced. |
| AI assistant | Claude API (Anthropic) | Paid-tier differentiator. Needs an API key server-side; per-user metering eventually. |
| Data | JSON library files (machines/tools/materials) + SQLite (`cnc_planner.db`, legacy) | **No real database on the API path yet.** User accounts, projects, subscriptions all need a proper DB (assume Postgres). Today user-created machines/rate-cards live in browser localStorage — they need to move server-side for accounts to work. |
| Current tester deploy | One small DigitalOcean droplet: nginx (static frontend + `/api` proxy + **HTTP basic auth**) + uvicorn (2 workers) via systemd, conda env, certbot TLS | Files in `deploy/`: `setup-server.sh`, `nginx-cnc.conf`, `cnc-api.service`, `deploy.sh` (git pull + rebuild + restart). This is the entire current "auth" and "deployment" story. |

## 3. Workload profile (why this isn't a normal CRUD app)

This is the most important section for capacity planning:

- **CPU-bound, long requests.** STEP analysis takes seconds on a fast desktop, **~90–120 s on the current small droplet** for real parts. It is synchronous Python/C++ (OpenCASCADE); it does not parallelize within one request.
- **Memory spikes.** OCCT can spike several GB on big STEP files. The systemd unit caps at 3 GB to protect the box. Uploads are capped at 200 MB.
- **Large responses.** 3D meshes are sent as JSON float arrays — 1–20 MB per response today, currently uncompressed (gzip is a known pending fix on our side).
- **Bursty concurrency.** A handful of concurrent analyses can saturate a small box. Blocking work currently runs on the async event loop (known defect — a fix on our side is planned), so one user's analysis stalls others.
- **A July 2026 performance audit** (available on request) found the same file re-parsed up to ~9× per page load with no caching; we will fix the redundancy in app code, but the architecture should still assume: *long-running CPU jobs that must not run inside the web request path*. The audit's recommendation, and my ask to you: **job queue + worker processes** (e.g. Redis + RQ/Celery/arq, or equivalent) with the API returning job status, and the frontend polling or using SSE/WebSocket. Please validate or propose better.

## 4. Data inventory — where everything lives today vs. where it must live

The uncomfortable truth first: **today almost nothing is stored server-side.** The current app is stateless — that's why it works for solo testing and why it cannot onboard 10 companies without your design.

| Data category | Where it is TODAY | Where it must live in PRODUCTION |
|---|---|---|
| **STEP files (customer CAD)** | **Not stored at all.** Uploaded per request, written to a temp file for analysis, discarded. Every re-open = re-upload; every tab switch re-sends the file. | Object storage (S3-compatible — DO Spaces / R2 / MinIO), per-account prefix, quota 15–20 files (Goal 7). Commercially sensitive: private bucket, signed URLs, India-region preference, retention policy needed. |
| **Analysis results / plans / quotes** | Browser memory only — gone on refresh. Nothing is reproducible after the session. | Postgres. Quotes/estimates become **immutable dated records** (Goal 6) linked to the stored STEP file hash, the machine/material/rate-card used, and the user who ran it. |
| **Machine / tool / material libraries** (global content) | JSON files in the git repo (`backend/machines_library.json` ~28 market machines with maker/controller data, `data/default_*.json`), read at request time. Updating = code deploy. | Postgres, **admin-managed and versioned**. Admin adds a machine (e.g. a Micromatic partnership feed) → every subscriber sees it without a release. Needs custom-field flexibility (JSONB) so new attributes don't require migrations. |
| **User's custom machines, rate cards, materials, settings** | **Browser localStorage** (`cnc.customMachines`, `cnc.rateCard…`, currency, costing model). One browser, one PC; clearing browser data destroys it; invisible to us for support. | Postgres, keyed to the account. Rate cards: global **defaults** managed by admin, each account's own rate card is theirs. This migration is mandatory for single-device licensing to make sense. |
| **Per-part UI state** (feature exclusions, route steps, assembly mode) | localStorage keyed by filename (`cnc.excluded.<file>`, `cnc.customRouteSteps.byPart`, `cnc.assyMode.<file>`) | Postgres rows on the stored part/project, so it follows the login. |
| **Part thumbnails** (card preview images) | localStorage (`cnc.thumbs.v1`, small PNGs rendered client-side after analysis) | Object storage next to the STEP file, generated server-side on ingest — so a user's project cards look right on any device. |
| **Users / devices / sessions / subscriptions / invite codes** | **Do not exist.** Tester gate is one shared nginx basic-auth password. | Postgres: users, orgs (a company may have several logins later), device bindings (R2), subscriptions + entitlements (R3/R8), invite codes (R1). |
| **Operator history / audit log** | Does not exist. | Postgres append-only events: login, device change, upload, analysis, quote produced, admin action — timestamped (Goal 8). |
| **Legacy** | `cnc_planner.db` (SQLite) — unused by the web API; Streamlit leftover. | Drop. Do not migrate. |

## 5. Requirements — what I need designed

### R1. Accounts & authentication
- Email + password login (no social login needed for launch).
- **Phase 1 (now, ~10 trial companies):** two provisioning paths, both admin-initiated:
  1. Admin creates the account with the company's email and hands over credentials.
  2. Admin issues an **invite code**; the company self-registers with the code (sets their own password, email verified). Codes are single-use, expiring, tied to a plan (e.g. "trial-90-days").
- **Phase 2 (launch):** open self-service signup from the public website, email verification, password reset.
- Sessions must be server-side revocable (needed for R2).

### R2. Single-device licensing (per-seat enforcement) — key business rule
- **One login = one machine.** A subscription covers use on one machine; a second machine requires paying for another seat.
- When a login is attempted from a second device, the design must handle it deliberately. My preferred UX (open to your recommendation): block the new device with a message "this account is active on another machine — buy another seat or deactivate the old machine," with a self-service "move to this machine" allowed some limited number of times (so a laptop upgrade doesn't need support tickets).
- Needs some device identity mechanism (browser fingerprint + refresh-token binding, or similar — your call on what is robust enough vs. spoofable; this is a web app, no installer, so a hardware lock isn't possible).
- Admin panel must show device bindings per account and allow me to reset them.

### R3. Subscription plans & payments
Planned tiers (INR, monthly; annual ≈ 2 months free):

| Tier | Price | What it gates |
|---|---|---|
| Free | ₹0 | 3 quotes/month, watermarked/limited export |
| Workshop | ~₹1,999/mo | Unlimited quotes, no AI assistant |
| Pro | ~₹4,999/mo | AI assistant (Claude) + everything |

- Additional machine seat = paid add-on (price TBD).
- **India first:** UPI + cards → Razorpay is my assumption (validate; recurring UPI/e-mandate support matters at these price points).
- Europe later via Antutive AB (Stripe presumably) — don't build it now, but don't design it out.
- Trials: competitor uses paid trials; we may do a 14-day trial or the Free tier serves that purpose — recommend one.
- I need: plan enforcement in the backend (quota counting, feature flags per tier), dunning/failed-payment handling, invoices (GST for India — Datadelimited proprietorship).

### R4. Public website
- Marketing/landing page + pricing page + signup + subscribe (checkout) + login into the app.
- Can be static/simple at launch; the app itself stays behind login.
- Domain purchase pending brand-name finalization ("QuoteKar" leading candidate).

### R5. Admin panel
- Create/enable/disable/suspend users; set plan manually (comped accounts for testers); issue/revoke invite codes (R1).
- See device bindings (R2) and reset them.
- See usage per account (quotes run, analyses run, AI calls, storage used) — doubles as metering for quotas.
- **Troubleshooting view:** an account's recent activity and errors (from the audit log + server logs) so I can support a stuck tester without screen-sharing; device reset; password reset.
- **Global library management:** add/edit/version machine, tool, and material library entries that propagate to **all** subscribers (the scenario: Micromatic partners with us and supplies official machine data — I enter it once, every user worldwide gets it). Library edits are versioned/auditable.
- **Custom fields:** I must be able to add new attributes to library entries without a schema migration (JSONB-style flexible columns) — e.g. a partner supplies "spindle taper" tomorrow.
- **Rate-card defaults:** system default rate cards are admin-managed; each account's own rate card stays their private copy (they start from the default).
- Basic revenue/subscription status view (or just link out to Razorpay dashboard).

### R6. Environments & release pipeline — my dev workflow
I develop continuously and need to ship safely while users are live:
- **Dev:** my Windows machine (already works).
- **Staging:** a deployed environment where I push a branch, testers/I verify against real infrastructure.
- **Production:** the paying-user environment. Deploys must not lose in-flight analyses or corrupt data; DB migrations must be managed (Alembic or similar).
- I want: push to GitHub → CI runs the regression suite (exists: `tests/`, 18 gate tests; needs the conda env to run) → deploy to staging automatically → **manual promote to production** (one command or one click). Zero-downtime preferred; a 1-minute maintenance window is acceptable at this stage if it simplifies things.
- Secrets management for: Anthropic API key, Razorpay keys, DB credentials, SMTP.

### R7. Data & multi-tenancy
- Postgres (or your recommendation) for: users, sessions/devices, subscriptions/invoices, projects (uploaded parts + saved plans/quotes), usage counters, custom machines/tools/rate-cards (migrating out of localStorage).
- Uploaded STEP files: where do they live (object storage? disk?), retention policy, and privacy — customers' CAD files are commercially sensitive; India data-residency preferences apply.
- Backups + restore procedure.

**Starter schema — my sketch of the user database (refine/replace as you see fit; it exists so nothing in Section 4 is left homeless):**

| Table | Holds | Notes |
|---|---|---|
| `users` | email, password hash, name, status | one row per login |
| `orgs` | company name, GST no. | a company may get multiple logins later |
| `devices` | user, device fingerprint, bound_at, last_seen | R2 single-device enforcement; admin-resettable |
| `sessions` | user, device, token, revoked_at | server-side revocable |
| `invite_codes` | code, plan, expires_at, used_by | R1 trial provisioning |
| `entitlements` | account, module, plan, expiry | R3/R8 — one row per owned module |
| `parts` | owner, filename, sha256, object-storage key, size, thumbnail key, uploaded_at | the user's stored STEP files (quota counts these) |
| `part_state` | part, exclusions, route steps, assembly mode | today's per-part localStorage |
| `quotes` | part (+file sha), machine/material/rate-card snapshot, itemised ledger JSON, total, created_by, created_at | **immutable** — Goal 6 |
| `rate_cards` / `machines` / `tools` / `materials` | admin-managed global libraries (JSONB attrs) + per-account copies | R5 global push + custom fields |
| `audit_events` | who, action, entity, timestamp, detail JSON | append-only — Goal 8 |
| `usage_counters` | account, month, quotes/analyses/AI calls/storage bytes | quota + metering |

### R8. Module entitlements — the platform vision (design in from day one)
The product is becoming a multi-discipline manufacturing quoting platform, expanding both vertically (deeper CNC features) and horizontally (new disciplines). The UI already ships a module launcher:

| Module | Status | Engine reality |
|---|---|---|
| **CNC Machining** | Live | The current product (milling + turning) |
| **Fabrication & Welding** | Coming soon (~3-4 mo) | Weldment analyzer largely exists (multi-body splitting, per-plate plans, welding route block) |
| **Sheet Metal & Laser** | Coming soon (~4-6 mo) | Cut-length × thickness costing; DXF first, 3D unfold later |
| **3D Printing** | Coming soon (~1-2 mo) | Mesh volume/support/machine-hour quoting |

What this means for YOUR design:
- **Entitlements are per-module**: a user may own one module, several, or the "full suite" bundle. Locked modules render grayed with a lock; purchase unlocks without redeploy.
- The subscriptions schema (R3) must model `entitlements(account, module, plan, expiry)` from day one — adding a module later must be a data row, not a migration.
- Pricing page must support per-module and bundle SKUs (exact prices TBD — my decision).
- Do not build the other modules' backends now; just make sure nothing in auth/billing/DB assumes "one product".

## 6. Constraints & preferences

- **Budget-conscious:** pre-revenue, founder-funded. Prefer one or two VPS/droplets or modest cloud over anything with idle cost. GPU never needed. But size the analysis workers realistically (the current small droplet is too slow — testers complain about loading today).
- **Hosting region:** India or nearby for launch-market latency (uploads are multi-MB, so proximity matters).
- **The conda/OCCT constraint** (Section 2) must survive containerization — a Docker image built on miniforge/mambaforge with the `cnc-cadquery` env is the expected shape; the app must be launched through that env's context.
- **Windows dev / Linux prod** is the current reality and fine.
- Team = me alone for now. Ops burden must be low; managed services are welcome where cheap (managed Postgres, managed Redis).
- Timeline: tester-phase hardening now; subscription + public site by **1 August 2026** launch.

## 7. Open decisions (I own these — flag anything that blocks you)

1. Final product/brand name + domain (blocks website, email sender, invoice header).
2. Exact seat/add-on pricing and trial policy.
3. Payment provider confirmation (Razorpay vs alternatives) — need your input on recurring-billing fit.
4. Legal entity on invoices: Datadelimited (India) — GST registration status to confirm.
5. How much of the performance-fix list we complete before launch (gzip, parse cache, off-loop workers are committed; payload slimming may slip).

## 8. What I'd like back from you

1. Target architecture diagram (web tier, worker tier, queue, DB, storage, CDN if any) with sizing and monthly cost estimate at 10 / 50 / 200 users.
2. Auth + single-device-enforcement design (R1/R2) with the token/session mechanics spelled out, including the invite-code flow.
3. Subscription/billing integration design (R3) including webhook flows, quota enforcement points, and the per-module entitlement model (R8).
4. **Data architecture** matching Section 4: schema sketch (users/orgs/devices/entitlements/parts/quotes/audit/libraries), object-storage layout + quota/retention mechanics for STEP files, and the localStorage→server migration plan.
5. CI/CD + environment plan (R6) including how DB migrations and the conda-based image are handled.
6. A phased rollout: what ships for the 10-company trial (admin-provisioned accounts, storage, audit) vs. what ships 1 Aug (self-service + payments + module store).

**Access I can give you:** GitHub repo (read), the current droplet (SSH), the performance audit findings, and a demo login.
