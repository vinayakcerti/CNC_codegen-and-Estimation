# Security, Leak & Threat Review — 2026-07-12

Three passes (coder line-review · architect · adversarial tester against the live backend on :8000). Read-only review; two safe fixes were then applied to the working tree (see bottom). Nothing committed.

## Findings (by severity)

| Sev | Where | Issue | Fix / status |
|-----|-------|-------|--------------|
| HIGH | `backend/main.py` all routes | No app-layer auth. Only gate today is nginx basic-auth. | **Launch blocker** — keep backend bound to `127.0.0.1` behind nginx until Week-4 auth. Never bind `0.0.0.0` without auth. |
| HIGH | `backend/main.py:54-60` CORS `allow_origins=["*"]` | Confirmed live: `Access-Control-Allow-Origin: *` echoed for a hostile Origin. Any site could drive the API (incl. `/api/assistant`, which spends the Anthropic key). `allow_credentials=False` limits it. | **Launch fix** — lock to the real frontend origin. Left for you: changing it now could break a LAN-IP tester. |
| HIGH | `POST /api/weldment` | Bypassed the STEP size/binary validator every other upload path uses → unbounded-size DoS. | **FIXED (uncommitted)** — added `validate_step_payload`; verified live: bad file → HTTP 400, clean message, no traceback. |
| MED | `/api/analyze`, `/api/assistant` | Unauthenticated, unthrottled, expensive (OCCT tessellation ~90-120 s; assistant spends API credits). | **Launch fix** — add per-IP rate limit + concurrency cap before public exposure. |
| MED | `deploy/setup-server.sh` | Bootstraps nginx with hardcoded `tester1 / ChangeMe123!`. | **Launch fix** — generate a random password at bootstrap. |
| LOW | `App.tsx`, `QuoteModal.tsx` logo | Company logo dataURL was the one HTML attribute interpolated unescaped (self-XSS only; user sets their own logo). | **FIXED (uncommitted)** — now only embeds if it matches `^data:image/`, and escaped. |
| LOW | `frontend/.env.production` | Env file tracked in git (benign now — empty var). | Keep env files out of VCS as they grow. |
| INFO | npm audit | 2 MODERATE via `exceljs`→`uuid`. No HIGH/CRITICAL. | Monitor; bump when a non-breaking fix ships. |

## Guardrails already in place — keep these

- **`esc()` on every user string** in both HTML document generators (filenames, company/customer fields, machine/process/setup names). XSS surface genuinely covered.
- **Hardened JSON/CSV import** (`shopFile.ts`, `costing.ts`) — never spreads parsed JSON into objects, so `__proto__` can't pollute; rebuilds fixed-shape objects field-by-field.
- **No dangerous sinks** — no `innerHTML`/`dangerouslySetInnerHTML`; no `eval`/`exec`/`pickle`/`subprocess`/`shell=True` in backend or modules.
- **Upload path-traversal safe** — client filename never used to write disk; all writes are random tempfiles, unlinked in `finally`; `/api/sample` uses basename + extension allowlist (verified: `../` → 404).
- **Clean error responses (verified live)** — wrong type, missing params, empty, oversized filename all return structured messages, no tracebacks, no paths.
- **Secrets hygiene clean** — no keys/tokens/passwords in tree or git history; `.gitignore` covers `*.db`, venvs, `.claude/`; API key read only from `os.environ`.
- **Prod hardening present** — systemd binds `127.0.0.1`, `MemoryMax=3G`; nginx `client_max_body_size 210m` + basic-auth.

## Must fix before production (Week-4)

1. Auth on the FastAPI layer (or ironclad `127.0.0.1`-only guarantee).
2. Lock CORS to the real origin.
3. Rate-limit + cap concurrency on `/api/analyze` and `/api/assistant`.
4. Replace the hardcoded `ChangeMe123!` bootstrap password.

(HIGH #3 weldment guard and the LOW logo-escape are already applied in the working tree, pending your review.)
