# Production Backlog — before/at go-live (Aug 1, 2026)

Status: LIVING DOCUMENT · created 2026-07-12 from user-testing feedback round 2
(Estimator_Additional_Requirements.docx) + open items across the project.
Owner: Vinayak. Items here are explicitly deferred from current sprints and MUST
be revisited before production.

## PB-1 · Cost library server sync (from Estimator ARD decision)
v1 stores each shop's costing profiles + hole cost library per browser
(localStorage) with CSV import/export. For production: move to account-backed
server storage (lands with W4 auth/multi-tenancy) so prices sync across the
shop's computers, edits keep the audit trail server-side, and frozen quote
snapshots are retrievable. Migration: import existing localStorage/CSV on first
login.

## PB-2 · Quick-Quote mobile flow — the "ChatGPT quoting shops" strategy
Prospect insight (owner with 2–3 machines): they photo/PDF the drawing into
ChatGPT and accept whatever estimate comes back. Strategy to win them:
- Upload a DRAWING (PDF/photo), not just STEP — first page shows an instant
  simple estimate; user types either machine time OR ₹/cm² right on that page.
- One button expands to the full app (strategy, overview, setups) — desktop or
  mobile; first page must be phone-friendly.
- Positioning: "as fast as ChatGPT, but with real machining logic + a quote
  document you can send."
Scope note: PDF/photo → geometry is a hard problem; v1 can be manual-entry
quick-quote (dims + features typed) with the same 1-page UX. Backlog until
core Estimator sprint ships.

## PB-3 · LEGACY-4 test triage (task #82)
Four legacy suite failures, pre-existing, need judgment with Vinayak:
operation_plan identity, starting_part_policy candidate loss (possible real
bug), stock_allowance 0.002 mm depth (possible real bug), vmc_golden re-baseline
(needs machinist sign-off on SLIDE BASE counts). Do NOT silently re-baseline.

## PB-4 · Hole cost library seed sign-off (ARD M6)
Only one confirmed row (24 H7 × 50 mm = ₹800). All other seeds ship as ORANGE
"estimated — not confirmed" rows. Before production: shop-floor sign-off pass
converts rows to confirmed (green). Tester request doc already covers C3
cutting data; add the hole-price table to the next shop visit.

## PB-5 · Real lathe part validation (Epic 20-2)
Lathe engine (detect → plan → tools → time → G-code) is verified on synthetic
T04–T11 only. Need one real customer shaft/flange STEP end-to-end + machinist
review of the G-code assumptions (G97/G99, representative passes, [GROOVE_Z]).

## PB-6 · W4 launch infra (existing task #12)
Auth/multi-tenancy, deployment (shareable link — testing is currently
localhost-only), pricing page, 3+2-axis flagged beta. PB-1 rides on this.

## PB-7 · Multi-currency cost engine
ARD scopes this iteration INR-only (display-currency selector already exists,
symbol-only). Production for Gulf market: real per-currency rate cards.

## PB-8 · Tester machining inputs pending (Tester_Request doc sent)
B1 Wall Roughing rules, B3 Adaptive Roughing rules, C3 named-tool cutting data,
step-shoulder false-positive confirmation. Implement as strategy classes when
answers arrive.

## PB-9 · Assistant panel v2
Streaming responses, in-app API key setup UI, retry affordance after no-key,
possibly server-managed key per tenant post-auth.

## PB-10 · Body names from STEP (Toolpath parity, nice-to-have)
Toolpath lists CAD body names (e.g. "M10 tapped hole1", "Iso4762-m16x85").
We label by classification (plate/shaft/bracket). Reading STEP product names
(OCAF/XCAF) would give named BOM rows and better exclusion UX for fasteners.

## PB-11 · Fixture vs toolpath full collision check
Clamp keep-out is heuristic (end grips on facing, feature-clearance placement).
Full toolpath-vs-fixture collision verification is deferred.
