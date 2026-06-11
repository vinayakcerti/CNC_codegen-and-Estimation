# Geometry Coordinate Contract

**Status:** Implemented foundation; UI/export rollout in progress  
**Date:** 2026-06-11

## Coordinate Frames

### CAD frame

The unmodified coordinate system supplied by the STEP file. CAD coordinates are
retained for tessellation, exact face provenance, diagnostics, and viewer
geometry.

### Work frame

The normalized planning coordinate system used for operator-facing feature
locations, setup assignment, operations, and exports.

- Work X is stock length.
- Work Y is stock width.
- Work Z is stock height/tool approach for the primary setup.
- The default work origin is the minimum transformed part corner.
- Work coordinates are therefore non-negative for supported orientations.

### Setup-local frame

Each additional setup retains the same physical work-frame feature position but
has an explicit setup orientation: Top, Bottom, Front, Back, Left, or Right.

## Supported Transform

The canonical transform is axis-aligned:

`work_point = axis_permutation_and_sign(cad_point - cad_origin)`

It supports:

- translation of arbitrary CAD origins
- centered and negative CAD coordinates
- X/Y/Z axis permutations
- reversed/mirrored axis signs
- setup-label mapping from transformed face normals

Identity orientation is preferred. CAD X/Z/Y is preferred second because many
VMC exports model Y as vertical. Other inferred permutations require operator
orientation confirmation before production use.

## Data Contract

Candidates may contain:

- `cad_position`: original STEP coordinates
- `work_position`: transformed planning coordinates
- `cad_setup_label`: setup direction in the CAD frame
- `work_setup_label`: setup direction in the work frame
- `coordinate_transform`: serializable transform metadata

The CAD viewer must continue using CAD geometry. Operator-facing accepted
features use work coordinates. Exact face meshes must never be transformed
independently from their source solid.

## Unsupported Cases

Arbitrary non-orthogonal orientation, simultaneous 5-axis accessibility,
ambiguous multi-solid transforms, or geometry that cannot be assigned a
reliable work frame must be labelled `Manual review required`. The system must
not invent a confident 3-axis setup.

## Validation Rules

- Transforming the CAD minimum/maximum corners must reproduce work spans.
- Setup labels must derive from transformed normals.
- Raw CAD values must remain available after acceptance.
- UI, operations, setup sheets, CSV, and draft code must ultimately use the same
  work-frame values.
- Zero is a valid coordinate and must not be replaced by a fallback.
