# Story: Start New Job / Reset Current Job

**Epic:** UX / State Management  
**Priority:** High (testing blocker — stale state causes confusion across sessions)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer testing multiple STEP files,  
> I want a single "Start New Job / Reset Current Job" button on page 5a,  
> so that I can clear all stale accepted features and candidates  
> before uploading a new STEP file without residual state from a previous job.

---

## 2. Problem

When testing multiple STEP files in sequence, old accepted features remain in
`st.session_state.features` (and the SQLite DB) after uploading a new file.
Page 5a shows stale features from the previous STEP, and page 6 Operation Plan
generates a plan for the wrong file's features.

Root cause: `features` is persisted to `cnc_planner.db` via `save_features_to_db`.
Uploading a new STEP file resets `step_candidates` and `added_candidate_ids`, but
does **not** clear the accepted features list or the downstream computed state
(`operations`, `time_result`).

---

## 3. Files Changed

| File | Change |
|------|--------|
| `app.py` | Single block added in `page_setup_review()`, between variable setup and the "Stock Dimensions" subheader. No other function or page modified. |

---

## 4. Implementation

### Insertion point

After the four variable bindings at the top of `page_setup_review()`:

```python
stock    = st.session_state.get("stock", {})
machine  = st.session_state.get("selected_machine")
material = st.session_state.get("selected_material")
features = st.session_state.get("features", [])
step_ok  = bool(st.session_state.get("step_parse_result"))
```

### Code added

```python
# ── Start New Job / Reset ────────────────────────────────────────────────
if st.session_state.pop("_job_reset_done", False):
    st.success("Job reset — features and candidates cleared. Upload a new STEP file on page 1.")

_has_job_state = bool(features) or bool(st.session_state.get("step_candidates"))
if _has_job_state:
    _rc1, _rc2 = st.columns([5, 1])
    _rc1.info(
        f"**{len(features)} accepted feature(s)**  ·  "
        f"**{len(st.session_state.get('step_candidates', []))} CAD candidate(s)**"
        + (f"  ·  File: **{st.session_state.uploaded_filename}**"
           if st.session_state.get("uploaded_filename") else "")
    )
    if _rc2.button("Start New Job / Reset", type="secondary", use_container_width=True):
        st.session_state.features = []
        save_features_to_db([])
        st.session_state.features_from_candidates = False
        st.session_state.step_candidates = []
        st.session_state.step_candidate_warnings = []
        st.session_state.added_candidate_ids = set()
        for _k in ("operations", "time_result", "step_parse_result", "step_geometry"):
            st.session_state.pop(_k, None)
        st.session_state.uploaded_filename = None
        st.session_state.step_uploader_key += 1
        st.session_state.stock = {
            "length": 150.0, "width": 100.0, "height": 50.0,
            "part_volume": 600.0, "stock_volume": 750.0,
        }
        st.session_state._job_reset_done = True
        st.rerun()
```

### Visibility logic

The info strip and button appear only when `features` is non-empty **or** `step_candidates` is non-empty. On a completely fresh session the block is invisible.

### Post-reset success message

A `_job_reset_done` session flag is set before `st.rerun()`. On the next render,
`st.session_state.pop("_job_reset_done", False)` returns `True` and shows
`st.success(...)` at the top of the page. The flag is immediately consumed, so
the message shows only once.

---

## 5. Session Keys Cleared

| Key | Action | Not a Master Data Key |
|-----|--------|-----------------------|
| `features` | `= []` + `save_features_to_db([])` | ✓ |
| `features_from_candidates` | `= False` | ✓ |
| `step_candidates` | `= []` | ✓ |
| `step_candidate_warnings` | `= []` | ✓ |
| `added_candidate_ids` | `= set()` | ✓ |
| `operations` | `pop` | ✓ |
| `time_result` | `pop` | ✓ |
| `step_parse_result` | `pop` | ✓ |
| `step_geometry` | `pop` | ✓ |
| `uploaded_filename` | `= None` | ✓ |
| `step_uploader_key` | `+= 1` (resets file uploader widget) | ✓ |
| `stock` | reset to 150×100×50 defaults | ✓ |

**Not cleared (master data):** `tools`, `materials`, `machines`,
`selected_material`, `selected_machine`.  
**Database:** `cnc_planner.db` is not deleted; `save_features_to_db([])` writes
an empty list to the features table.

---

## 6. Existing Conflict Warning

The existing conflict warning block (lines ~978–988) is **kept unchanged**.
It shows a narrower "Clear existing features before accepting CAD candidates" button
only when both manual features and fresh CAD candidates exist and `features_from_candidates`
is False. That is a different, targeted action; it coexists without confusion because
"Start New Job / Reset" is more prominent and full-scope.

---

## 7. How to Test in Streamlit

1. **Upload M02_vmc_slot_plate.step** on page 1 → auto-parse runs.
2. Go to **5a. Setup & Feature Review** → accept the Slot candidate → click **Add accepted candidates**.
3. Go to **6. Operation Plan** → confirm the plan shows `Slot` operations.
4. Return to **5a**. The info strip shows `1 accepted feature(s) · 2 CAD candidate(s) · File: M02_vmc_slot_plate.step`.
5. Click **Start New Job / Reset** → confirm the page shows the success banner and the info strip is gone.
6. Navigate to **1. Upload STEP File** → upload `M03_vmc_blind_rectangular_pocket.step`.
7. Go to **5a** → confirm only M03 candidates appear (Pocket + Face milling), no M02 Slot remains.
8. Accept M03 candidates → go to **6** → confirm only Pocket operations appear.

---

## 8. Definition of Done

- [x] Button appears near the top of page 5a when features or candidates exist.
- [x] Button is invisible on a fresh session.
- [x] All 12 job-specific session keys listed above are cleared on click.
- [x] `save_features_to_db([])` called so the DB is also cleared.
- [x] Master data (tools, materials, machines) is not affected.
- [x] `cnc_planner.db` is not deleted.
- [x] `st.rerun()` is called after reset.
- [x] Success message appears once on the post-reset render.
- [x] Existing conflict warning block preserved.
- [x] No other modules, tests, or data files modified.
- [ ] Streamlit manual test per section 7 (perform before demo).
