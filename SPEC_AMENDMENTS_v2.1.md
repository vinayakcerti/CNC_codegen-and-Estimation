# Specification Amendments — v2.1

**Amends:** DataDelimited CNC Estimator Platform — Product Specification v2.0 (DDL-CNC-SPEC-001)
**Date:** 21 July 2026 · **Author:** Vinayak Panchaman (Product Owner)
**Status:** Binding on v2.0 — where an amendment conflicts with the base document, the amendment wins. Everything not amended stands as written.

The base specification is approved as the working baseline. It is well-constructed — the account state machine (§7.1), webhook idempotency (§8.4), coupon channel (§6.6), estimate immutability (§9.4) and the Product Review Recommendations are adopted as-is. The following seven amendments correct positioning, pricing and the licensing model, and align the spec with the Architect Brief (ARCHITECT_BRIEF.md in the product repo).

---

## A1 — Positioning: the platform is NOT "AI-powered" (supersedes §1.1, §6.1 hero, Appendix A)

The estimation pipeline is **deterministic, geometry-driven CAD analysis** — feature recognition, strategy generation and costing are computed from the STEP model's actual geometry by algorithmic rules. No AI/ML model produces or influences an estimate.

- Replace every instance of "AI-powered / AI-driven analysis" with **"automated feature recognition"** or **"geometry-driven estimation"**.
- Landing hero (§6.1) becomes: **"Automated CNC Estimation Platform"** — sub-heading: "Upload a STEP file — get features, machining strategy and a defensible estimate in minutes."
- The **AI Assistant** (a conversational copilot that answers questions about a generated plan, powered by a third-party LLM) exists in the product but is an **optional, separately-priced add-on** (see A5). It never generates or modifies estimates. Marketing may describe the assistant as AI; it must not describe the estimates as AI.

*Why binding: engineers trust deterministic numbers; "AI-generated quote" invites doubt and diligence risk. Truth in positioning is a launch requirement.*

## A2 — Plans, pricing periods & bonus time (supersedes §2 "Plans", §6.1 pricing table, §8.1)

| Plan | Billing | Bonus | Trial |
|---|---|---|---|
| Monthly | ₹ [TBD] / seat / month | None | 30 days |
| 6-Month | one-time, per seat | **+15 days free** | 30 days |
| 12-Month | one-time, per seat | **+2 months free** | 30 days |

- Renewal cadence follows the bonus: 6-month renews after 6 months + 15 days; 12-month after 14 months.
- Bonus periods remain administrator-configurable (BR-004, BR-050) — these are the launch defaults.
- The per-seat price point (₹1,599 in the base document) is **not confirmed** — Product Owner decision pending (see Decisions Register below).

## A3 — Licensing: Individual AND Company accounts (supersedes §2 "Licensing", §3.1 "One license, one person")

The "no shared team seats in v1.0" decision is **reversed** — company licensing is in scope for v1.0:

- **Individual account:** exactly as specified in the base document — one verified person, one seat.
- **Company account:** one organisation holding **N seats** under a single billing relationship. Every seat is still a named, verified person (email + phone per BR-001/BR-002 — seats are not shared logins).
- **Volume pricing:** 2+ seats earn a per-seat discount. Launch defaults (admin-configurable, final % = Product Owner decision): 2–4 seats −10%, 5–9 seats −15%, 10+ seats custom/enterprise quote.
- **New customer-side role: Company Admin** — buys/assigns/revokes seats, sees org-level usage and invoices. Sits between Licensed User and Platform Administrator in the RBAC matrix (§7.3). A Company Admin may also hold a seat.
- Each seat is bound to **one machine** per the Architect Brief's single-device rule (R2); moving a seat to a new machine is self-service a limited number of times, then admin-assisted.

## A4 — Shared company workspace (extends Part V)

For company accounts, projects, STEP files and estimates belong to the **organisation**, not the individual seat:

- Any seat in the company can **open any colleague's project and estimate in the viewer** — read the stored record, no regeneration, no second upload, no extra charge (BR-005/BR-031 immutability unchanged).
- The uploading seat is recorded as the project's **owner**; rename/delete stay owner + Company Admin actions. Viewing is org-wide.
- **Storage quota pools at the organisation level** (seats × per-seat quota), so one heavy user doesn't hit a wall while colleagues have headroom.
- The audit log records which seat uploaded, generated, opened, renamed or deleted — operator history per person even inside a shared workspace.
- Individual accounts are unaffected: their projects remain private to the single seat.

## A5 — AI Assistant is a priced add-on (new; aligns with Architect Brief R8)

- **What the add-on contains (implemented July 2026):**
  1. *Plan copilot* — grounded Q&A about the current plan (setups, times, estimate).
  2. *Quotation letter writer* — one click drafts the customer-facing quote email (English / Hindi / Kannada / Tamil), total price only, internal cost lines never leak, missing commercial facts become bracketed placeholders.
  3. *DFM feedback note* — turns the engine's machinability findings into a polite design-improvement note the shop sends its customer.
  4. *Cost advisor* — ranks the levers to hit a target price (material, batch size, tolerance, feature exclusions); suggests only, never computes prices — the engine recomputes.
  - Roadmap (not in v1): batch RFQ triage across multiple uploads; tolerance/thread extraction from 2D PDF drawings.
- Model tiering: light generation on the cheapest model tier, advisory reasoning on the mid tier — per-task, env-configurable; est. AI cost <₹50/seat/month at heavy usage, so add-on margin is pricing-driven, not cost-driven.
- The conversational assistant is an **entitlement**, off by default, purchasable per seat (monthly add-on) or bundled into a higher-priced seat — Product Owner decision pending.
- Requires a server-side LLM API key and per-seat usage metering (assistant calls appear in the admin usage metrics, §10.1).
- The subscription schema must model this as an entitlement row, not a plan variant — consistent with the module-entitlement architecture (Architect Brief R8) so future modules (Fabrication & Welding, Sheet Metal & Laser, 3D Printing) plug into the same mechanism.

## A6 — Alignment with the Architect Brief (technical addendum)

The base document and ARCHITECT_BRIEF.md (product repo) are companion documents. Where the spec is silent, the brief governs. Explicitly imported into this spec:

- **Single-device enforcement per seat** (Brief R2) — device binding table, admin-visible and resettable. The spec's session model (§7.2) gains a device dimension.
- **Module entitlements** (Brief R8) — `entitlements(account, module, plan, expiry)`; v1.0 ships CNC Machining only, but billing/schema must not assume one product.
- **Storage** — OD-003 is ratified as: 25 GB soft quota per subscription, **pooled per organisation** for company accounts (supersedes A6 of the brief's "15–20 files" phrasing; the GB quota governs).
- **Coupons ≈ trial invite codes** — the coupon mechanism (§6.6) is also the instrument for the 10-company trial cohort (Brief R1): admin issues a coupon per trial company; no payment mandate required on that path.

## A7 — Landing page ownership (clarifies §6.1)

The landing page, pricing page and product UI are **built in-house by DataDelimited** (the existing frontend team/tooling). The architect owns everything behind them: auth, billing integration, subscriptions, entitlements, storage, environments and deployment. §6.1's content requirements stand as the landing page's functional spec.

---

## Decisions Register (Product Owner — resolve before build)

| # | Decision | Options / notes |
|---|---|---|
| D1 | Per-seat monthly price | Base doc says ₹1,599; earlier planning said ₹1,999. Pick one. |
| D2 | Volume discount percentages | Defaults proposed in A3 (−10% / −15% / custom). |
| D3 | AI Assistant pricing | Add-on ₹/seat/month, or premium seat tier incl. assistant. |
| D4 | Card-before-trial (PRR-001) | Keep mandate-first checkout (better conversion to paid, worse trial starts) or no-card trial for India market. If kept: adopt PRR-001's "card required, first charge after 30 days" disclosure verbatim. |
| D5 | Grace period (OD-001) | Adopt PRR-002's 7 days unless objection. |

## Adopted recommendations

PRR-001 (mandate disclosure), PRR-002 (7-day grace), PRR-003 (atomic coupon consumption), PRR-005 (trial-ending notifications day 23 & 29), PRR-006 (estimate versioning when regeneration ships), PRR-007 (email/phone change re-verification), PRR-008 (200 MB upload / 25 GB quota) — all adopted as part of this amendment set.
