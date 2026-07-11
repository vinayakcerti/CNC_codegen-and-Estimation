"""Group similar WeldmentPart bodies by classification + approximate dimensions."""
from __future__ import annotations
from .models import WeldmentPart, WeldmentGroup

# Two bodies are considered "same" if all three sorted dimensions agree within this fraction.
_DIM_TOL_FRAC = 0.03   # 3 % — generous enough for rounding but strict enough for real diffs


def _dim_key(part: WeldmentPart):
    dims = sorted([part.length_mm, part.width_mm, part.height_mm])
    # Round to nearest 0.5 mm to absorb tessellation noise
    rounded = tuple(round(d / 0.5) * 0.5 for d in dims)
    # Bounding box alone MERGES DIFFERENT BODIES that share an envelope (e.g.
    # the 650 plate with M10 holes vs the same plate without — audited on the
    # SLIDE BASE: three such wrong merges, one collapsing 3 distinct designs
    # into "plate ×8"). Volume (exact BRep, holes change it) + face count are
    # cheap, robust discriminators; identical parts still group as qty > 1.
    return (part.classification,) + rounded + (
        round(part.volume_cm3, 1),
        part.faces_count,
    )


def group_parts(parts: list[WeldmentPart]) -> list[WeldmentGroup]:
    """Return WeldmentGroup list — identical parts share one group with qty > 1."""
    groups: dict[str, WeldmentGroup] = {}
    for part in parts:
        key_tuple = _dim_key(part)
        key = "_".join(str(v) for v in key_tuple)
        if key in groups:
            groups[key].quantity += 1
            groups[key].body_indices.append(part.body_index)
        else:
            groups[key] = WeldmentGroup(
                group_id=key,
                classification=part.classification,
                quantity=1,
                representative=part,
                body_indices=[part.body_index],
            )
    return list(groups.values())
