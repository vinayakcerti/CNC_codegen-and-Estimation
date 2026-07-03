"""Data models for the Weldment / Fabrication Assembly workflow."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WeldmentPart:
    """Represents one solid body extracted from a multi-body STEP file."""
    body_index: int
    label: str                        # e.g. "Body 1"
    classification: str               # plate / block / tube / shaft / gusset / bracket / unknown
    length_mm: float
    width_mm: float
    height_mm: float
    volume_cm3: float
    surface_area_mm2: float
    faces_count: int
    material_guess: str = "Steel"
    features: list[dict] = field(default_factory=list)   # holes, slots, pockets detected on this body
    operations: list[dict] = field(default_factory=list) # recommended per-part machining ops
    machining_time_min: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class WeldmentGroup:
    """A set of identical (same class + dims) WeldmentPart bodies."""
    group_id: str
    classification: str
    quantity: int
    representative: WeldmentPart         # first body in the group
    body_indices: list[int] = field(default_factory=list)


@dataclass
class WeldmentJob:
    """Top-level job container for a weldment / fabrication assembly."""
    filename: str
    total_bodies: int
    parts: list[WeldmentPart] = field(default_factory=list)
    groups: list[WeldmentGroup] = field(default_factory=list)
    assembly_operations: list[dict] = field(default_factory=list)
    total_machining_time_min: float = 0.0
    total_assembly_time_min: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def total_time_min(self) -> float:
        return self.total_machining_time_min + self.total_assembly_time_min
