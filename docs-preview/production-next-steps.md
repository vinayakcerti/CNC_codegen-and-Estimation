# Production Next Steps — CNC Plan & Process Pro

Launch target: **Aug 1, 2026**. Ordered by dependency — each item unblocks the ones below it.
Sources: `_bmad-output/planning-artifacts/production-backlog-2026-07.md` (PB-1..PB-11) + Week-4 launch plan.
Status legend: 🟢 shipped · 🟠 built, waiting on sign-off · 🔴 launch blocker.

## 🟢 Already shipped (context, no action)

STEP analysis + feature detection · setup planning + workholding · strategy (ops/tools/cycle times) · dual costing (₹/hr default + rate-card ₹/cm² with hole cost library) · Quote + Effort Estimate HTML docs · Excel cost-split export · weldment assembly rollup · lathe/turning v1 with G-code draft · My Shop machines + rate cards · 3D viewer with body scoping · AI assistant panel v1 · 13 regression gates in `tests/`.

## 🟠 Close out validation first (nothing below makes sense on an unvalidated engine)

- [ ] **1. Collect tester machining inputs (PB-8)** — B1 wall-roughing + B3 adaptive-roughing rules and C3 named-tool cutting data feed directly into strategy classes; estimates stay approximate until they land.
- [ ] **2. Triage LEGACY-4 test failures with Vinayak (PB-3)** — two of the four look like real engine bugs (starting_part_policy candidate loss, stock_allowance 0.002 mm depth); do not silently re-baseline.
- [ ] **3. Hole-price seed sign-off (PB-4)** — only one confirmed row today (24 H7 × 50 mm = ₹800); quotes built on "estimated" orange rows undermine the whole rate-card pitch.
- [ ] **4. Validate lathe on a real customer part (PB-5)** — turning is proven only on synthetic T04–T11; one real shaft/flange STEP end-to-end plus machinist review of G-code assumptions (G97/G99, passes).

## 🔴 Launch blockers, in dependency order

- [ ] **5. Security hardening** — CORS is currently `*` and uploads are unrestricted; size/type limits, rate limiting and header lockdown must precede any public URL.
- [ ] **6. Auth + multi-tenancy (PB-6 / W4)** — accounts are the prerequisite for per-shop data isolation and for every server-side store below; nothing shop-specific can go to a shared server without it.
- [ ] **7. Rate-card + cost library server sync (PB-1)** — move `cnc.costing.profiles` (rate cards + hole library) from localStorage to account-backed DB; migrate existing localStorage/CSV on first login; enables frozen quote snapshots and cross-computer sync.
- [ ] **8. Deployment + hosting** — testers are localhost-only today; `deploy/` already has nginx + systemd + setup scripts, so this is wiring + a domain, and it unblocks shareable-link testing.
- [ ] **9. Backups** — the moment shop prices and quotes live server-side (item 7), scheduled DB backups + restore drill become mandatory, not optional.
- [ ] **10. Monitoring + error tracking** — `/api/health` exists; add uptime alerting and server error capture so the first paying shop is not the monitoring system.
- [ ] **11. Pricing page (PB-6)** — AI vs no-AI tiers are already separated in the architecture (backend is fully functional without `ANTHROPIC_API_KEY`), so pricing is presentation work, best done last against the final feature set.

## ⏭ Post-launch backlog (explicitly not blocking Aug 1)

- **PB-2** Quick-quote mobile flow — the "ChatGPT-quoting shops" wedge; v1 can be manual-entry with the same one-page UX.
- **PB-7** Multi-currency rate cards — Gulf market; this iteration is INR-only (display-currency selector is symbol-only).
- **PB-9** Assistant v2 — streaming, in-app API-key setup, per-tenant server-managed key once auth exists.
- **PB-10** STEP body names via OCAF/XCAF — named BOM rows and easier fastener exclusion (Toolpath parity).
- **PB-11** Fixture-vs-toolpath collision check — clamp keep-out is heuristic today; full verification deferred.
