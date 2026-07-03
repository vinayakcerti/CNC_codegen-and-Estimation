"""Group similar WeldmentPart bodies by classification + approximate dimensions."""
from __future__ import annotations
from .models import WeldmentPart, WeldmentGroup

# Two bodies are considered "same" if all three sorted dimensions agree within this fraction.
_DIM_TOL_FRAC = 0.03   # 3 % — generous enough for rounding but strict enough for real diffs


def _dim_key(part: WeldmentPart) -> tuple[str, float, float, float]:
    dims = sorted([part.length_mm, part.width_mm, part.height_mm])
    # Round to nearest 0.5 mm to absorb tessellation noise
    rounded = tuple(round(d / 0.5) * 0.5 for d in dims)
    return (part.classification,) + rounded  # type: ignore[return-value]


def group_parts(parts: list[WeldmentPart]) -> list[WeldmentGroup]:
    """Return WeldmentGroup list — identical parts share one group with qty > 1."""
    groups: dict[str, WeldmentGroup] = {}
    for part in parts:
        key_tuple = _dim_key(part)
        key = f"{key_tuple[0]}_{key_tuple[1]}x{key_tuple[2]}x{key_tuple[3]}"
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
