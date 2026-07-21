# Demo Script — CNC Plan & Process Pro (~12 min)

## Before the audience arrives
1. Start both servers; open the app in Chrome at `localhost:5173`.
2. **Run one sample through once** (click a sample, let it analyze) — this warms up the CAD engine so the live demo feels fast.
3. Set your currency in Estimate → Estimate settings if the audience is not INR.

## Act 1 — "From CAD file to plan in one click" (3 min)
- **Start on Projects.** Say: *"This is the whole workflow — a shop gets a customer STEP file, and today quoting it takes a senior guy 30-60 minutes. Watch."*
- Upload a simple plate (e.g. `04_plate_mixed_holes_d6_d10_d20.step`) or click a bundled sample.
- While the staged loader runs, narrate: *"It's reading the actual 3D geometry — finding holes, slots, pockets, deciding which face the tool enters from."*
- **Land on the Strategy tab.** Point at the right panel: *"It found the features, grouped them into setups — Setup 1 from the top, Setup 2 flipped — chose workholding, real tools from the shop's library, speeds and feeds, and a cycle time per operation."*
- **Click any operation.** The 3D viewer highlights exactly where that cut happens; the op card shows tool, spindle, feed, path length, cut time. Click a hole op → the drill axis and entry direction show in 3D. *"Nothing is a black box — every minute is traceable to a cut."*

## Act 2 — "It thinks like a machinist" (3 min)
- **Overview tab.** Material + machine pickers (grouped Milling / Lathe / Turn-Mill), quantity, **Stock mode**. Switch Automatic → **Manual**, enter oversize billet dims → the plan grows Edge Milling setups for the side stock; clicking one highlights the exact side face. *"Tell it the raw material you actually buy, and the plan and price follow."*
- **Feature Table** (bottom panel): every detected feature with dims and confidence. **Untick a feature** — *"customer says these holes are already done"* — ops, time, and price update. Show the exclude (⊘) button on an op row too.
- **Tool Table**: the tool crib this plan drew from.
- Viewer chips: Grid / Dims / **Stock** (translucent billet) / **Fixture** (vise/jaws), opacity slider, view cube.

## Act 3 — "The money screen" (3 min)
- **Estimate tab.** Hero price on top. *"This is what the customer sees; everything below is where it came from."*
- **Estimate settings**: two costing models — **Time-based** (machine-hours × rate) vs **Rate card** (per-cm² / per-feature pricing). Flip between them live.
- Tolerance preset & complexity multipliers — tighten tolerance, price moves.
- **Quote ledger**: material (stock volume + density), setups, per-setup machining, add-on processes (**+ Add process** — anodizing, plating…).
- **Export Excel** (top bar): per-part cost-split workbook — Summary, Ops, Holes, Features, Cost Library sheets. **Prepare Quote**: customer-facing quote.
- **Route tab**: the traveler — CNC Milling block (machine + rate), CNC Turning if lathe features, Welding & Assembly for weldments, custom stations. *"This is the process routing sheet a planner would write."*

## Act 4 — The wow finishers (2-3 min)
- **The weldment.** Open **SLIDE BASE (28 bodies)**. Show "Weldment — how will you machine it?": **Build part-by-part** vs **Already welded — surface ops only**. Click a single plate → the workspace scopes to that body: its features, its setups, its price. *"It quoted a 28-body welded assembly plate-by-plate."*
- **The Assistant tab** — AI copilot answering questions about the current plan (*"why two setups?", "what if I use a bigger face mill?"*). The Pro-tier differentiator.
- Close: *"Minutes, not an hour — and every number is defensible because you can click it."*

---

# Screen-by-screen reference

## Left sidebar (always visible)
| Icon | Screen | What it is |
|---|---|---|
| ▦ | **Projects** | Landing screen: bundled demo samples + multi-file STEP upload |
| ◧ | **Part workspace** | The main working screen (viewer + tabs) for the loaded part |
| ▤ | **Shop Library** | Your machines and rate cards |
| ◈ | Team | Placeholder — coming with accounts/multi-user (don't click in demo) |

## Projects
Upload one or many STEP files, or click a bundled sample. Each part becomes a card; clicking analyzes it and opens the workspace.

## Part workspace — layout
- **Top bar:** filename, the four tabs, Assistant, theme toggle, Upload STEP, Export Excel (cost-split workbook), Prepare Quote (customer quote).
- **Center: 3D viewer.** Drag to orbit; view cube for standard views. Chips: Grid, Dims (dimension labels), Stock (translucent billet box), Fixture (workholding). Opacity slider dims the part so highlights show through. Clicking an op/feature highlights the actual CAD faces and auto-orients the camera.
- **Right: plan inspector.** Physical-feature count, total machine time, setup list — each setup shows its entry face, workholding recommendation, and numbered ops with tool + cycle time; ⊘ excludes an op. Clicking an op opens its card: tool, geometry (size, depth, L/D ratio, through/blind, thread likelihood), cutting parameters (rpm/feed/path/cut time).
- **Bottom panel:** **Tool Table** (tool crib: number, type, Ø, flutes, flute length, max depth) and **Feature Table** (every detected feature: type, name, dims, depth, confidence, thread, setup; include/exclude checkboxes; filter chips All/None/by-type).

## Overview tab
- **Weldment mode choice** (multi-body only): Build part-by-part vs Already welded (surface ops only).
- **Workpieces to build**: job quantity multiplier.
- **Material** picker (+ add custom) and **Machine** picker grouped Milling / Lathe / Turn-Mill (+ add custom).
- **Stock mode**: Automatic (+5 mm/side) or Manual (billet L×W×H → drives facing depths, Edge Milling ops, and material cost).
- **Features / Operations / General / Part envelope / Topology / Machinability issues**: counts, part dims, surface area/volume/mass, face counts, DFM warnings.

## Strategy tab
The operation plan grouped by setup — "how we'll machine it." Everything clickable and reflected in 3D. Lathe parts get a Turning setup; scoped bodies get their own per-plate plan.

## Estimate tab
- **Hero price** with staged compute animation.
- **Estimate settings**: currency, costing model (Time-based vs Rate card), tolerance preset, complexity multipliers.
- **Quote ledger**: material, setups, machining per setup, add-on processes; excluded features/ops drop out live. Under a body scope it prices just that body.

## Route tab
Whole-job process routing: numbered station blocks — CNC Milling (machine + time + rate + cost), CNC Turning (if lathe work), Welding & Assembly (weldments), **+ Add process** for custom stations (name, time, rate). Route summary totals at the bottom. Body scope intentionally doesn't apply — the route always covers the whole job.

## Assistant tab
Claude-powered copilot with the current plan as context — ask why an op exists, what changes if the machine/tool changes, etc. (Pro-tier feature.)

## Shop Library
Your shop's machines (copy-on-edit from the curated India/global machine library) and **rate cards** (per-operation pricing used by the Rate-card costing model). What you configure here is what plans and estimates draw from.

---

**Demo don'ts:** don't click **Team** (placeholder); don't upload a giant customer STEP cold (parse time) — stick to samples or pre-warmed parts; for manual stock use sensible oversize dims (bigger than the part) so the plan stays valid.
