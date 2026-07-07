# CNC Plan & Process Pro — Web UI Tester Guide (branch: `v4-web-ui`)

You are testing the new React web app **against Toolpath AI** (app.toolpath.com)
using the **same STEP file in both tools**. This guide explains how to run it,
what every page does, the logic behind the numbers, and what feedback we need.

---

## 1. Setup (once)

Prerequisites: Git, Node 18+ (`node -v`), Miniforge/conda with the
`cnc-cadquery` environment (CadQuery crashes without conda's DLL context —
never run the backend with plain python).

```bash
git fetch origin
git checkout v4-web-ui
git pull origin v4-web-ui

# If you don't have the env yet:
conda create -n cnc-cadquery python=3.11 -y
conda activate cnc-cadquery
conda install -c conda-forge cadquery -y
pip install fastapi uvicorn python-multipart

# Frontend deps (once):
npm --prefix frontend install
```

## 2. Run (two terminals)

```bash
# Terminal 1 — engine API
conda run -n cnc-cadquery uvicorn backend.main:app --port 8000

# Terminal 2 — web app
npm --prefix frontend run dev
```

Open **http://localhost:5173**. (The old Streamlit app still works separately:
`conda run -n cnc-cadquery streamlit run app.py` — not the focus of this test.)

## 3. Test protocol

1. Open Toolpath and upload the reference part
   (`test_samples/3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP`).
2. In our app, click the **SLIDE BASE sample card** (or Upload STEP with the
   same file). **The analysis takes ~90 seconds with only a text spinner** —
   known limitation, job-queue fix is planned.
3. Walk the pages below **side by side with Toolpath** and note differences:
   numbers, clarity, anything confusing or missing.
4. Also upload **one of your own parts** to both tools and repeat.

---

## 4. Page-by-page — what it does and HOW it works

### Projects (landing)
Sample cards + upload. Click a card → full analysis pipeline runs:
STEP parse → feature detection → machinability → 3D tessellation.

### Overview
- **Cut config** — material selector (9 Indian-market materials + "+ Add
  material" for your own with density/machinability/safety). Changing it
  re-plans everything: feeds/speeds scale with machinability, estimate mass
  uses density.
- **Machine** — 36-machine library (Ace Micromatic, BFW, Jyoti, LMW, HMT,
  HAAS, Brother, DN Solutions, Mazak, Makino…) + "+ Add machine". Machine
  choice caps spindle RPM, sets rapids/tool-change/setup times in estimates.
- **Stock mode/preset/size** — Automatic = part envelope + 5 mm/side.
  Manual mode lets you type stock L/W/H; the estimate's material line uses it.
- **Features plannable (grade)** — % of detected features whose operations
  plan cleanly with the current tool library + machine (A–D grade).
- **Machinable surface (%)** — on multibody parts this is now computed from
  a validated per-body surface walk (hover the value for the method and the
  exclusions list, e.g. weld-prep grooves below the smallest endmill).
  Comparable to Toolpath's "machinable surface area"; expect ≥95% on
  normal parts.
- **Bodies** — multibody parts split into groups (identical parts grouped
  with ×N). Clicking a group **scopes the whole app to that body**: isolated
  3D, its features, its own machining plan. "Full assembly" resets. The scope
  chip at the top shows the current scope from any tab.
- **Setups** — face-direction setups with a recommended workholding
  (vise/jaws/fixture from stock geometry rules). Clicking one orients the
  camera and shows the amber tool-approach cone + grid floor + vise-jaw
  visual (v1 workholding scene).
- **Holes** — grouped by diameter ("7× Ø5mm — Setup …") with a thread-status
  dropdown. When scoped, the Strategy header also shows a hole census chip
  ("0 of 22 holes threaded (7 likely M6) · 8 thru · 14 blind") — the
  "likely" part is a tap-drill-table inference from the pilot diameter
  (Ø4.2→M5, Ø5→M6, Ø6.8→M8 …), clearly labeled, since STEP files carry no
  thread data. Counterbored holes are never marked likely-tapped.
- **Machinability issues** — features whose ops are blocked (no tool fits,
  depth exceeds reach…).

### Strategy
**The logic:** detected features → per-feature operation rules (Hole → spot
drill + drill; Slot/Pocket → rough end mill + finish; faces → face mill) →
tool matched from the library (46 metric tools) → cutting time =
path ÷ feed × material safety factor. Operations grouped by setup with
rollups ("Rough End Mill ×8 — 25mm 3F Flat Endmill — 7.5m"); expand for
individual ops.
- **Click any op** → its exact CAD faces highlight blue on the part
  (fallback: a blue locator ring at the feature position) and a **cutting
  parameters panel** opens (tool, spindle, feed, path, cut time). Edit the
  feed → time recomputes live (estimates only; doesn't change the plan).
- **When scoped to a body** (IMPORTANT — this is where accuracy is best):
  holes/slots come from **exact cylinder geometry** (validated against
  Toolpath: identical 22-hole table on the reference plate), not from the
  raw detector. Reference plate scoped plan: 22 drilled holes + 4 slots +
  facing = ~38 min vs Toolpath's 42 min.
- **Whole-assembly view** still uses raw/grouped detections — expect noisier
  numbers there; scoping per body is the accurate workflow (same as
  Toolpath, which only ever analyzes one body).

### Bottom panel (under the 3D viewer)
Switch **Tool Table** (the 46-tool library: name, type, Ø, flutes, tip angle)
/ **Feature Table** (all detected candidates with dims + confidence). Drag
its top edge to resize; double-click to collapse.

### Estimate
**The ledger math**, all operator-controlled:
- Material = **stock** volume × material density × ₹/kg (stock, not
  finished-part — same basis as Toolpath).
- Per-setup machining = setup minutes ÷ 60 × ₹/hr × **preset ×
  complexity × tolerance** (multipliers shown in a caption).
- **Feature basis**: Grouped (physical features — recommended) vs Raw (every
  detection — most conservative). Re-plans on change.
- **Quote preset**: Conservative (textbook rough+finish, ×1.00) / Standard
  shop (×0.85) / Competitive (×0.70).
- **Tolerance class**: General ±0.2 (×1.00) → Precision (×1.60).
- Setup charges ×N + margin % → **Grand total**, with the **Range** line
  showing the competitive↔conservative ends so a quote is never blind.

### Route (our differentiator — Toolpath has no equivalent)
Multi-process routing for one job:
1. **CNC Milling** — auto from the Strategy totals on your selected machine.
2. **Welding & Assembly** — auto for weldments (fit-up → tack → weld →
   grind → inspect phases with times from the fabrication model), own ₹/hr.
3. **CNC Turning** — **now auto-planned**: when turned regions are detected,
   the block shows planned lathe minutes from the turning planner (insert
   tools, surface-speed cycle times). Enter a manual time to override.
4. **+ Add process** — anything (powder coating, heat treat…) with
   name/time/rate.
Route summary = process blocks + material + setup charges + margin →
**routed grand total**.

### Turning (NEW — test with any shaft/flange/bushing STEP)
Upload a turned part: detection types **OD Turning** regions (Ø × length),
**ID Turning / Bore**, and **ID Groove** (dia × width); short recesses get a
"verify: possible undercut / thread relief" flag. The Strategy tab shows a
**Lathe Chuck setup group** (3-jaw chuck workholding; long shafts L/D>5
escalate to "Chuck + Tailstock") with Face → OD Rough → OD Finish →
ID Rough/Finish Bore → Groove ops, each with an insert-grade tool (CNMG /
DNMG / boring bars / MGMN groove), RPM from surface speed, and cycle time.
Cross-drilled holes on shafts are detected too and planned as milled
drilling. Note: this is planning + quoting, not lathe G-code.

### Viewer controls
Orbit/pan/zoom always; view cube; **Opacity slider** (bottom-right);
sun/moon **theme toggle** (topbar); resizable/collapsible right inspector
(drag its left edge / double-click).

---

## 5. Known limitations (don't file these — we know)
- ~90 s analysis with only a spinner (job queue planned).
- **Estimate is now per-body when scoped** (ledger switches to the body's
  own plan + stock and says "Per-body estimate — … , 1 pc"); the ROUTE tab
  intentionally stays whole-job.
- Thread status on hole rows is still a dropdown; the "likely M…" chips are
  tap-drill inference, not detected threads (STEP has no thread data).
- Turning plans ops + times but does not generate lathe G-code or canned
  cycles yet.
- No toolpath motion simulation (Toolpath licenses ModuleWorks for that; we
  render feature highlights instead — out of scope for now).
- Whole-assembly Strategy on weldments includes noisy detections; scoped
  bodies use validated geometry.

## 6. What we need back from you
Per page: what's wrong, what's confusing, what's missing vs Toolpath, and
what's better. Specifically:
1. On the reference plate (scope to "Plate ×1"): do our 22 holes / 4 slots /
   ~38 min agree with what Toolpath shows you?
2. On YOUR part: are the detected features right? Which are wrong/missing?
3. Is the estimate believable for your shop rates? Which knob is missing?
4. Route tab: does the multi-process quote match how you actually job-cost?
5. Anything that made you stop and think "what does this mean?"
