# Story: VMC Operator Validation Readiness

**Epic:** Output Quality / Operator Safety  
**Priority:** High (pre-demo gating — must pass operator review)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a VMC machinist reviewing the app's output before a demo,  
> I want all operation notes, setup callouts, and CNC program headers  
> to contain clear, accurate planning-level guidance,  
> so that I can give feedback on whether the plan is safe and realistic  
> without being misled into running draft code on a machine.

---

## 2. Goals

1. Setup 1 / Setup 2 separation is unambiguous in the operation plan and G-code.
2. Boring operations carry a complete tooling verification note.
3. Pocket and slot operations carry corner-radius, flute-length, and stepover notes.
4. Step finish operations carry a reach/flute-length note.
5. The draft CNC header and the export page both state clearly that the program must not be run without CAM verification.
6. An operator validation checklist exists for the six primary VMC samples.

---

## 3. Files Changed

| File | Change |
|------|--------|
| `modules/operation_planner.py` | `_context_note()` expanded for Face Milling, Large Hole / Boring, Pocket (new branch), Slot, Step, Chamfer |
| `modules/gcode_generator.py` | Header warning strengthened; Setup 2 separator block added before bottom face-mill G-code |
| `app.py` | `page_cnc_export` `st.error` text strengthened |
| `_bmad-output/implementation-artifacts/vmc_operator_validation_checklist.md` | New operator review checklist |

---

## 4. Changes Detail

### 4.1 `operation_planner.py` — `_context_note()`

| Feature / Op | Before | After |
|---|---|---|
| Face Milling bottom | "Setup 2 required — flip part before machining this face." | + " Verify workholding and fixture clearance for second setup." |
| Large Hole / Boring (any diameter) | "Verify boring tool reach and minimum bore capability for final diameter Ø{d} mm." (only for Ø≥25) | "Verify boring tool minimum bore, maximum bore, reach, and rigidity before machining. Final diameter: Ø{d} mm." (all boring ops) |
| Pocket Rough End Mill | *(no context note)* | "Rough pocket using multiple depth/radial passes. Verify tool diameter and corner radius suitability." |
| Pocket Finish End Mill | *(no context note)* | "Finishing pass cleans pocket walls and floor. Verify tool flute length ≥ pocket depth." |
| Slot Rough End Mill | "Use multiple depth passes and radial stepovers." | + " Verify tool diameter ≤ slot width and corner radius suitability." |
| Slot Finish End Mill | "Finish slot walls and floor after roughing." | "Finish slot walls and floor. Verify tool flute length ≥ slot depth and corner radius suitability." |
| Step Finish End Mill | *(no context note)* | "Verify tool reach and flute length for shoulder wall finish pass." |

### 4.2 `gcode_generator.py` — Header

Before:
```
; THIS IS DRAFT CNC CODE. VERIFY IN CAM/SIMULATOR BEFORE
; RUNNING ON A REAL CNC MACHINE.
```

After:
```
; DO NOT RUN THIS PROGRAM DIRECTLY ON A MACHINE.
; THIS IS DRAFT PLANNING CODE ONLY.
; VERIFY IN CAM/SIMULATOR AND BY A QUALIFIED CNC PROGRAMMER
; BEFORE RUNNING ON ANY REAL MACHINE.
; Tool numbers, offsets, speeds, and feeds MUST be verified.
```

### 4.3 `gcode_generator.py` — Setup 2 separator

When a bottom Face Mill operation is encountered in the G-code loop,
a prominent separator block is emitted before the tool change:

```
; ============================================================
; SETUP 2 — FLIP PART BEFORE CONTINUING
; Remove from fixture. Flip part. Re-indicate and re-zero Z.
; Verify workholding and fixture clearance for second setup.
; ============================================================
```

### 4.4 `app.py` — CNC export page error

Before:
```
IMPORTANT: Generated CNC code is DRAFT only. ALWAYS verify in CAM/simulator before running on a real machine.
```

After:
```
DO NOT RUN THIS PROGRAM DIRECTLY ON A MACHINE. This is draft planning code only. Verify in CAM/simulator and by a qualified CNC programmer before use on any real machine.
```

---

## 5. Definition of Done

- [x] `_context_note()` updated — boring, pocket, slot, step, face milling bottom.
- [x] G-code header strengthened.
- [x] Setup 2 separator block appears before bottom face-mill operations in G-code.
- [x] `app.py` export page error text strengthened.
- [x] `vmc_operator_validation_checklist.md` created with all 6 samples.
- [x] `python tests/run_feature_detection_regression.py` → 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR.
- [x] No feature detection logic changed.
- [x] No regression expectations changed.
- [ ] Operator validation checklist completed by machinist (perform before demo).
