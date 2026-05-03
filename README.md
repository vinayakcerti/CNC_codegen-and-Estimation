# CNC Process Planner

A Python Streamlit application for Indian SME CNC workshops.
Covers the full process from CAD import through G-code export and job documentation.

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
pip install -r requirements.txt
streamlit run app.py
```

## Project Structure

```
app.py                  # Main Streamlit application (10 screens)
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
