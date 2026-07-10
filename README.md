# CNC Plan & Process Pro

CNC process planning & quoting for Indian SME machine shops — FastAPI backend +
React 3D web app. Covers the full flow: STEP import → feature detection →
fixturing-based setups → operation strategy → cycle time → estimate → branded
quote / effort estimate / draft G-code.

*(The original Streamlit UI was retired in July 2026; the planning modules it
pioneered live on under `modules/` and power the API.)*

## Features

- STEP file import with automatic bounding-box extraction
- 18 pre-loaded Indian & international CNC machine profiles
- Tool library with integrated Speeds & Feeds calculator
- 26 material grades (IS/EN/BIS references)
- Feature-based operation planning (holes, bores, pockets, slots, threads)
- Cycle-time estimation and itemised job cost estimator
- 2D and interactive 3D visual preview
- Fanuc G-code export (G81, G83, G84, G85, G76)
- Printable HTML setup sheet with revision history
- Job notes and audit trail (SQLite)

## Quick Start

```bash
# Backend (CadQuery/OCCT needs the conda env)
conda run -n cnc-cadquery python -m uvicorn backend.main:app --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## Project Structure

```
backend/main.py         # FastAPI API (analyze, strategy, estimate, weldment)
frontend/               # React 19 + Vite + three.js web app
modules/
  data_store.py         # SQLite persistence, defaults loader
  operation_planner.py  # Feature → operation rule engine
  time_estimator.py     # Cycle-time & effort calculation
  gcode_generator.py    # Fanuc G-code generator
  visual_preview.py     # Plotly 2D/3D visualisation
  step_parser.py        # STEP file bounding-box parser
  setup_sheet.py        # HTML setup sheet generator
  speeds_feeds.py       # Cutting-speed & feed calculator
  tolerance_guide.py    # ISO 286-1 IT grade & surface finish guide
  tool_selector.py      # Automatic tool assignment
data/
  default_machines.json
  default_materials.json
  default_tools.json
public/
  favicon.svg
```

## Requirements

- Python 3.10+
- See `requirements.txt`

## License

Proprietary — all rights reserved.
