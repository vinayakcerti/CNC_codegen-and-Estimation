# VMC Operator Validation Checklist

**Purpose:** Structured review by a real VMC machinist / CNC operator before the app is used for production quoting or planning.  
**Instructions:** Load each sample in the app, step through all pages (Feature Review → Operation Plan → Time Estimate → CNC Export), and complete the fields below. Mark each item ✅ Pass / ⚠️ Concern / ❌ Fail.  
**Reviewer:** ___________________________  
**Date:** ___________________________  
**App version / branch:** v2-feature-review-engine  

---

## How to Run Each Sample

1. Open the app (`streamlit run app.py`)
2. Go to **1. Upload STEP File** — upload the sample file
3. Go to **5a. Setup & Feature Review** — accept all detected candidates
4. Go to **6. Operation Plan** — review operations table
5. Go to **7. Time & Effort Estimate** — review time and cost estimate
6. Go to **9. CNC Program Export** — review draft G-code and setup sheet

---

## Sample 1: M01_vmc_basic_plate_holes.step

**Description:** Basic plate with 4 through-holes Ø8 mm.  
**Expected features:** Face milling ×2, Hole ×4  
**Expected operations:** Face Mill (top) → Spot Drill ×4 → Drill ×4 → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (Face milling ×2, Hole ×4) | | |
| Operation sequence practical for VMC? | | |
| Tool choice acceptable? (spot drill, drill, face mill) | | |
| Speeds and feeds realistic for mild steel? | | |
| Time estimate believable for this part? | | |
| Setup sheet understandable to a new operator? | | |
| Draft G-code structure acceptable as a draft/reference? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Sample 2: M02_vmc_slot_plate.step

**Description:** Plate with a single flat-ended through-slot (no rounded ends).  
**Expected features:** Face milling ×2, Slot ×1  
**Expected operations:** Face Mill (top) → Rough End Mill (slot) → Finish End Mill (slot) → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (Slot detected, not Pocket) | | |
| Slot dimensions believable from geometry? | | |
| Operation sequence practical? (rough then finish) | | |
| Notes mention depth/radial passes and corner radius check? | | |
| Notes mention flute length check for finish pass? | | |
| Tool choice acceptable? (end mill for slot) | | |
| Speeds and feeds realistic? | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Draft G-code structure acceptable? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Sample 3: M03_vmc_blind_rectangular_pocket.step

**Description:** Plate with one blind rectangular pocket (has a floor face, depth ≈12 mm).  
**Expected features:** Face milling ×2, Pocket ×1  
**Expected operations:** Face Mill (top) → Rough End Mill (pocket) → Finish End Mill (pocket) → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (Pocket detected with floor face) | | |
| Pocket depth realistic? | | |
| Operation sequence practical? (rough then finish) | | |
| Notes mention depth/radial passes and corner radius check? | | |
| Notes mention flute length check? | | |
| Tool choice acceptable? | | |
| Speeds and feeds realistic? | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Draft G-code structure acceptable? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Sample 4: M05_vmc_large_bore_plate.step

**Description:** Plate with one large bore (Ø35 mm) and two pilot holes.  
**Expected features:** Face milling ×2, Large hole / boring ×1, Hole ×2  
**Expected operations:** Face Mill (top) → Spot Drill ×2 → Pilot Drill ×1 → Drill ×2 → Boring → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (boring + pilot holes) | | |
| Operation sequence practical? (pilot drill before boring) | | |
| Boring note mentions min bore, max bore, reach, rigidity? | | |
| Boring note includes final diameter? | | |
| Tool choice acceptable? (boring bar) | | |
| Speeds and feeds realistic for boring Ø35? | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Draft G-code uses G76 fine boring cycle? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Sample 5: M07_vmc_chamfered_plate.step

**Description:** Plate with 4 through-holes and top outer-edge chamfers (45°, ~2 mm).  
**Expected features:** Face milling ×2, Hole ×4, Chamfer ×1  
**Expected operations:** Face Mill (top) → Spot Drill → Drill → Chamfer → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (Chamfer detected, not missed) | | |
| Chamfer size estimate reasonable (~2 mm)? | | |
| Operation sequence practical? (chamfer after drilling) | | |
| Chamfer note mentions chamfer mill / countersink tool? | | |
| Chamfer note says to verify edge selection? | | |
| Tool choice acceptable? (chamfer tool) | | |
| Speeds and feeds realistic? | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Draft G-code chamfer section acceptable as draft? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Sample 6: 17b_top_milled_step_shoulder-Body.step

**Description:** Top-milled step shoulder (Y-direction, 90×30 mm floor, depth 12 mm).  
**Expected features:** Face milling ×2, Step ×1  
**Expected operations:** Face Mill (top) → Rough End Mill (step) → Finish End Mill (step) → Face Mill (bottom)

| Check | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Feature detection correct? (Step detected, not Pocket/Slot) | | |
| Step dimensions realistic? (length≈90, width≈30, depth≈12) | | |
| Operation sequence practical? | | |
| Rough note mentions depth/radial passes? | | |
| Finish note mentions tool reach and flute length check? | | |
| Tool choice acceptable? (end mill for step) | | |
| Rough path length estimate believable? (≈900 mm) | | |
| Finish path length estimate believable? (≈180 mm) | | |
| Time estimate believable? | | |
| Setup sheet understandable? | | |
| Draft G-code structure acceptable? | | |
| Any dangerous or misleading instruction? | | |
| **Operator comments:** | | |

---

## Overall App Feedback

| Item | ✅ / ⚠️ / ❌ | Comments |
|---|---|---|
| Draft CNC warning on export page clear enough? | | |
| G-code header warning strong enough? | | |
| Setup 2 separator visible in G-code when needed? | | |
| Setup sheet layout readable and print-friendly? | | |
| Time estimates within believable range (±50%)? | | |
| Cost estimates within believable range? | | |
| Would you trust this app for first-pass quoting? | | |
| Would you use this app to brief a new operator? | | |
| **Any instructions that could cause a machine crash or injury?** | | |
| **General comments / suggested improvements:** | | |

---

## Sign-off

| | |
|---|---|
| Reviewer name | |
| Role / experience | |
| Date reviewed | |
| Samples tested | |
| Overall recommendation | |
| Follow-up items | |
