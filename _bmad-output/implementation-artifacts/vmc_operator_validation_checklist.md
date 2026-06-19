# VMC Operator Validation Checklist

**Purpose:** Structured review by a real VMC machinist / CNC operator before the app is used for production quoting or planning.
**Instructions:** Load each sample in the app, step through the current VMC workflow, and mark each item Pass / Concern / Fail.
**Reviewer:** ___________________________
**Date:** ___________________________
**App version / branch:** v2-feature-review-engine

---

## Standard Workflow

1. Open the app at `http://localhost:8503/`.
2. Go to **Part Setup** and upload the sample STEP file.
3. Keep **Raw Block / Billet** unless the sample is intentionally a casting, forging, weldment, or rework part.
4. Go to **Select Work** and accept only the intended machining groups.
5. Go to **Feature Review** and confirm the accepted feature list and validation notes.
6. Go to **Strategy** and review operation order, tools, setup split, and warnings.
7. Go to **Estimate** and review machining time, cost, tolerance, and quote currency.
8. Go to **Export** and review the setup sheet plus draft CNC warnings. Do not run the G-code.

---

## Sample 1: M03_vmc_blind_rectangular_pocket.step

**Purpose:** Pocket baseline and pricing path.
**Expected features:** Face milling x2, Pocket x1.
**Expected operations:** Face Mill top -> Rough Pocket -> Finish Pocket -> Face Mill bottom.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Feature detection correct? | | |
| Pocket depth and dimensions believable? | | |
| Rough/finish operation sequence practical? | | |
| Tool choice acceptable for pocketing? | | |
| Notes mention depth/radial passes and flute length checks? | | |
| Estimate and INR quote believable? | | |
| Setup sheet understandable? | | |
| Any dangerous or misleading instruction? | | |

---

## Sample 2: M07_vmc_chamfered_plate.step

**Purpose:** Chamfer detection and chamfer operation planning.
**Expected features:** Face milling x2, Hole x4, Chamfer x1.
**Expected operations:** Face Mill top -> Spot Drill -> Drill -> Chamfer -> Face Mill bottom.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Chamfer detected and not missed? | | |
| Chamfer size estimate reasonable? | | |
| Operation order practical? | | |
| Chamfer note mentions chamfer mill/countersink and edge verification? | | |
| Tool choice acceptable? | | |
| Time estimate believable? | | |
| Draft G-code and setup sheet warnings clear? | | |
| Any dangerous or misleading instruction? | | |

---

## Sample 3: M02_vmc_slot_plate.step

**Purpose:** Flat-ended slot classification.
**Expected features:** Face milling x2, Slot x1.
**Expected operations:** Face Mill top -> Rough Slot -> Finish Slot -> Face Mill bottom.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Slot detected as Slot, not Pocket? | | |
| Slot dimensions believable? | | |
| Rough/finish sequence practical? | | |
| Notes mention depth/radial passes and corner radius check? | | |
| Tool choice acceptable? | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Any dangerous or misleading instruction? | | |

---

## Sample 4: 17b_top_milled_step_shoulder-Body.step

**Purpose:** Step/shoulder detection and planning.
**Expected features:** Face milling x2, Step x1.
**Expected operations:** Face Mill top -> Rough Step -> Finish Step -> Face Mill bottom.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Step detected as Step, not Slot/Pocket? | | |
| Step dimensions and depth believable? | | |
| Rough/finish step sequence practical? | | |
| Notes mention depth/radial passes and tool reach? | | |
| Tool choice acceptable? | | |
| Path length and time estimate believable? | | |
| Setup sheet understandable? | | |
| Any dangerous or misleading instruction? | | |

---

## Sample 5: M05_vmc_large_bore_plate.step

**Purpose:** Large bore and boring notes.
**Expected features:** Face milling x2, Hole x2, Large hole / boring x1.
**Expected operations:** Face Mill top -> Spot Drill/Drill pilot features -> Boring -> Face Mill bottom.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Boring feature detected correctly? | | |
| Pilot holes and large bore not confused? | | |
| Boring note mentions min bore, max bore, reach, and rigidity? | | |
| Boring operation order practical? | | |
| Tool choice acceptable? | | |
| Time estimate believable? | | |
| Draft G-code and setup sheet warnings clear? | | |
| Any dangerous or misleading instruction? | | |

---

## Sample 6: 25_vmc_job_plate_all_basic_features.step

**Purpose:** Mixed-feature sanity check.
**Expected features:** Face milling x2, Slot x2, Large hole / boring x1, Chamfer x1.

| Check | Pass / Concern / Fail | Comments |
|---|---|---|
| Mixed feature detection correct? | | |
| Select Work grouping is easy to understand? | | |
| 3D colors/highlights make machining intent clear? | | |
| Operation plan is practical enough for first-pass quoting? | | |
| Estimate is believable for a mixed VMC plate? | | |
| Export output is clearly draft-only? | | |
| Any dangerous or misleading instruction? | | |

---

## Overall App Feedback

| Item | Pass / Concern / Fail | Comments |
|---|---|---|
| Upload and parse flow clear? | | |
| Starting Part Type choices understandable? | | |
| Select Work cards map to real machining intent? | | |
| Feature Review validation useful? | | |
| Strategy page operation order credible? | | |
| Estimate page assumptions editable and understandable? | | |
| Export safety warning strong enough? | | |
| Setup sheet readable for shop-floor handover? | | |
| Would you trust this app for first-pass quoting? | | |
| Would you use this app to brief a new operator? | | |
| Any instruction that could cause scrap, machine damage, or injury? | | |

---

## Sign-off

| Field | Response |
|---|---|
| Reviewer name | |
| Role / experience | |
| Date reviewed | |
| Samples tested | |
| Overall recommendation | |
| Follow-up items | |
