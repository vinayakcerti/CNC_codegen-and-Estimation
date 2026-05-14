# Working Context for Claude and Codex

## Project

**Project name:** CNC Process Planner

**Repo path:** `C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro`

**Current branch:** `v2-feature-review-engine`

## Python and Regression

**Correct Python environment:**

```powershell
C:\Users\vinay\miniforge3\envs\cnc-cadquery\python.exe
```

**Important regression command:**

```powershell
C:\Users\vinay\miniforge3\envs\cnc-cadquery\python.exe tests/run_feature_detection_regression.py
```

**Expected regression result:**

- 18 PASS
- 0 FAIL
- 0 MISSING
- 0 ERROR

## Current Completed VMC Baseline

- Face milling
- Holes
- Blind holes
- Large bore / boring
- Rounded slots
- Flat-ended slots
- Blind pockets
- Through pockets/windows
- Step/shoulder
- Chamfer
- Operation planning for all above
- Reset current job button
- Operator validation warnings/checklist
- Pricing/currency/tolerance model
- Manual quote currency conversion

## Important Rule

Do not modify feature detection, operation planning, pricing, or UI unless the task explicitly asks for it.

## Agent Roles

**Claude role:** Main developer. Can edit files only within the approved task. No commits.

**Codex role:** Reviewer/tester only. Do not edit files unless explicitly asked. Use correct CadQuery Python path for tests.

## Current Next Workstream

UI/UX redesign using Toolpath reference, then static interactive 3D preview.

## Toolpath Reference

Uploaded docx described competitor flow: Upload/Overview, 3D viewer, material, setup faces, tools, strategy, estimate, cut config, tool library.

We will not implement animation now. Only rotatable static viewer later.

## Latest Status

VMC baseline stable and ready for operator validation.
