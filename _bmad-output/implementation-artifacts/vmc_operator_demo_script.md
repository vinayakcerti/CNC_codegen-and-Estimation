# VMC Operator Demo Script

**Audience:** VMC machinist, CNC programmer, quotation engineer, or workshop owner.
**Demo branch:** `v2-feature-review-engine`
**App URL:** `http://localhost:8503/`
**Purpose:** Collect practical feedback on first-pass VMC planning and quoting.

---

## Opening Script

Use this wording at the start:

> This is not CAM software and the generated CNC code must not be run on a machine. We are testing whether the app is useful for first-pass VMC quoting and process planning. Please judge whether the detected machining work, operation order, tooling notes, time estimate, and setup sheet look believable.

Ask the operator to focus on:

- Is the detected machining work correct?
- Are any real machining features missing or wrongly classified?
- Is the operation sequence practical for a VMC?
- Are the tool choices and safety notes credible?
- Does the estimated time feel believable for quoting?
- Is the setup sheet useful for shop-floor communication?
- Is anything dangerous, misleading, or likely to cause scrap?

Do not ask them to judge:

- Whether the draft G-code is ready to run.
- Whether this replaces CAM.
- Whether every feature type in all possible parts is supported.

---

## Setup

Run the app from the repo:

```powershell
cd "C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro"
git checkout v2-feature-review-engine
C:\Users\vinay\miniforge3\Scripts\conda.exe run -n cnc-cadquery python -m streamlit run app.py --server.port 8503
```

Open:

```text
http://localhost:8503/
```

If the sidebar shows **Local database is offline**, continue the demo. The app will use default tools and in-session job data.

---

## Standard Demo Path

For every sample:

1. **Part Setup**
   Upload the STEP file. Keep **Raw Block / Billet** for the provided VMC samples.
2. **Select Work**
   Review the machining groups and accept only the intended work.
3. **Feature Review**
   Confirm accepted features, quantities, dimensions, and validation notes.
4. **Strategy**
   Review operation order, setup split, tools, feeds, and warnings.
5. **Estimate**
   Review time, cost, tolerance, and quote currency assumptions.
6. **Export**
   Open **VMC handover test pack**, review setup sheet, and confirm draft CNC warnings are clear.

---

## Recommended Demo Order

| Order | STEP file | What to ask |
|---|---|---|
| 1 | `M03_vmc_blind_rectangular_pocket.step` | Is the pocket detected correctly? Is the rough/finish pocket plan useful? |
| 2 | `M07_vmc_chamfered_plate.step` | Is the chamfer detected and planned credibly? |
| 3 | `M02_vmc_slot_plate.step` | Is this correctly treated as a slot, not a pocket? |
| 4 | `17b_top_milled_step_shoulder-Body.step` | Is the step/shoulder plan believable? |
| 5 | `M05_vmc_large_bore_plate.step` | Are the boring notes and operation order acceptable? |
| 6 | `25_vmc_job_plate_all_basic_features.step` | Does a mixed-feature plate remain understandable? |

---

## Minimum Feedback To Collect

For each sample, record:

- Pass / Concern / Fail for feature detection.
- Pass / Concern / Fail for operation sequence.
- Pass / Concern / Fail for tooling notes.
- Pass / Concern / Fail for time estimate.
- Any missing feature or wrong classification.
- Any unsafe or misleading instruction.
- One sentence on whether this helps first-pass quoting.

Use:

```text
_bmad-output/implementation-artifacts/vmc_operator_validation_checklist.md
```

---

## Close The Demo

Ask these final questions:

1. Which result made you trust the app most?
2. Which result made you trust it least?
3. What is the first thing we must fix before showing this to another workshop?
4. Would you use this for first-pass quoting if the output is clearly marked as planning-only?
5. What real STEP file should we test next?

---

## Important Safety Line

End with:

> Treat every CNC program from this app as draft planning output only. It must be checked in CAM/simulation and reviewed by a qualified CNC programmer before any machine use.
