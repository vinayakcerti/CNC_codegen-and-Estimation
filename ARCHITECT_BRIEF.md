# Architect Brief — Productionizing CNC Plan & Process Pro

**Prepared by:** Vinayak Panchaman (developer/founder)
**Date:** 14 July 2026
**Purpose:** Everything you need to design the production deployment, subscription system, and release pipeline. I built the application; I need you to design how it runs as a commercial SaaS.

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

## 4. Requirements — what I need designed

### R1. Accounts & authentication
- Email + password login (no social login needed for launch).
- **Phase 1 (now, testers):** an **admin panel** where I create/enable/disable accounts and hand credentials to testers. No self-service.
- **Phase 2 (launch):** self-service signup from the public website, email verification, password reset.
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
- Create/enable/disable/suspend users; set plan manually (comped accounts for testers).
- See device bindings (R2) and reset them.
- See usage per account (quotes run, analyses run, AI calls) — this doubles as metering for quotas.
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

## 5. Constraints & preferences

- **Budget-conscious:** pre-revenue, founder-funded. Prefer one or two VPS/droplets or modest cloud over anything with idle cost. GPU never needed. But size the analysis workers realistically (the current small droplet is too slow — testers complain about loading today).
- **Hosting region:** India or nearby for launch-market latency (uploads are multi-MB, so proximity matters).
- **The conda/OCCT constraint** (Section 2) must survive containerization — a Docker image built on miniforge/mambaforge with the `cnc-cadquery` env is the expected shape; the app must be launched through that env's context.
- **Windows dev / Linux prod** is the current reality and fine.
- Team = me alone for now. Ops burden must be low; managed services are welcome where cheap (managed Postgres, managed Redis).
- Timeline: tester-phase hardening now; subscription + public site by **1 August 2026** launch.

## 6. Open decisions (I own these — flag anything that blocks you)

1. Final product/brand name + domain (blocks website, email sender, invoice header).
2. Exact seat/add-on pricing and trial policy.
3. Payment provider confirmation (Razorpay vs alternatives) — need your input on recurring-billing fit.
4. Legal entity on invoices: Datadelimited (India) — GST registration status to confirm.
5. How much of the performance-fix list we complete before launch (gzip, parse cache, off-loop workers are committed; payload slimming may slip).

## 7. What I'd like back from you

1. Target architecture diagram (web tier, worker tier, queue, DB, storage, CDN if any) with sizing and monthly cost estimate at 10 / 50 / 200 users.
2. Auth + single-device-enforcement design (R1/R2) with the token/session mechanics spelled out.
3. Subscription/billing integration design (R3) including webhook flows and quota enforcement points.
4. CI/CD + environment plan (R6) including how DB migrations and the conda-based image are handled.
5. A phased rollout: what ships for the tester phase (admin-provisioned accounts) vs. what ships 1 Aug (self-service + payments).

**Access I can give you:** GitHub repo (read), the current droplet (SSH), the performance audit findings, and a demo login.
