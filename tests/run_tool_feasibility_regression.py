"""Regression checks for tool, holder, and machine-limit feasibility."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import get_default_machines, get_default_materials, get_default_tools
from modules.operation_planner import plan_operations
from modules.tool_feasibility import assess_tool_feasibility


def _feature(feature_type="Pocket", **overrides):
    feature = {
        "feature_name": f"{feature_type} tool feasibility",
        "feature_type": feature_type,
        "quantity": 1,
        "x_pos": 0.0,
        "y_pos": 0.0,
        "diameter": 0.0,
        "length": 30.0,
        "width": 20.0,
        "depth": 5.0,
        "priority": 1,
        "setup_label": "Top",
        "physical_feature_id": f"PF-{feature_type}",
    }
    feature.update(overrides)
    return feature


def main():
    tools = get_default_tools()
    material = get_default_materials()[0]
    vmc = next(m for m in get_default_machines() if m["machine_type"] == "VMC")

    no_boring_tools = [tool for tool in tools if tool["tool_type"] != "Boring"]
    missing = plan_operations(
        [_feature("Large Hole / Boring", diameter=35.0, depth=20.0)],
        no_boring_tools,
        material,
        vmc,
    )
    boring = next(op for op in missing if op["operation_type"] == "Boring")
    assert boring["tool_name"] == "UNRESOLVED"
    assert boring["tool_feasibility_status"] == "blocked"
    assert boring["planning_blocked"] is True

    short_tool = {
        "tool_number": 99,
        "tool_name": "Short End Mill",
        "tool_type": "End Mill",
        "diameter_mm": 10.0,
        "default_spindle_rpm": 2000,
        "default_feed_rate_mm_min": 500,
        "max_depth_mm": 8.0,
        "flute_length_mm": 8.0,
        "overall_length_mm": 60.0,
        "holder_diameter_mm": 20.0,
    }
    reach = plan_operations(
        [_feature(depth=15.0)],
        [short_tool],
        material,
        vmc,
    )
    assert all(op["planning_blocked"] for op in reach)
    assert all("exceeds" in op["tool_warning"] for op in reach)

    oversized = plan_operations(
        [_feature(width=6.0, length=30.0, depth=4.0)],
        [short_tool],
        material,
        vmc,
    )
    assert all(op["planning_blocked"] for op in oversized)
    assert all("exceeds the smallest feature opening" in op["tool_warning"] for op in oversized)

    drill = next(tool for tool in tools if tool["tool_type"] == "Drill")
    mismatch = assess_tool_feasibility(
        "Drill",
        _feature("Hole", diameter=9.0, depth=10.0),
        drill,
        vmc,
    )
    assert mismatch["blocked"] is True
    assert "does not match" in mismatch["warning"]

    fast_tool = dict(short_tool)
    fast_tool["default_spindle_rpm"] = vmc["max_spindle_rpm"] + 2000
    fast_tool["default_feed_rate_mm_min"] = vmc["max_feed_rate"] + 1000
    capped = assess_tool_feasibility(
        "End Mill",
        _feature(),
        fast_tool,
        vmc,
        requested_spindle_rpm=fast_tool["default_spindle_rpm"],
        requested_feed_rate_mm_min=fast_tool["default_feed_rate_mm_min"],
    )
    assert capped["blocked"] is False
    assert capped["spindle_rpm"] == vmc["max_spindle_rpm"]
    assert capped["feed_rate_mm_min"] == vmc["max_feed_rate"]
    assert "capped to machine limit" in capped["warning"]

    print("PASS: tool and holder feasibility regression")


if __name__ == "__main__":
    main()
