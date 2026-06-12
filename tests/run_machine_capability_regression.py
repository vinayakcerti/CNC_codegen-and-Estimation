"""Regression checks for machine-axis and setup accessibility planning."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import get_default_machines, get_default_materials, get_default_tools
from modules.machine_capability import (
    assess_setup_access,
    machine_feasibility_summary,
    normalize_machine_capabilities,
)
from modules.operation_planner import plan_operations


def _feature(feature_type="Pocket", setup="Top", **overrides):
    feature = {
        "feature_name": f"{feature_type} regression feature",
        "feature_type": feature_type,
        "quantity": 1,
        "x_pos": 10.0,
        "y_pos": 20.0,
        "diameter": 10.0,
        "length": 30.0,
        "width": 20.0,
        "depth": 5.0,
        "priority": 1,
        "setup_label": setup,
        "physical_feature_id": f"PF-{feature_type}-{setup}",
    }
    feature.update(overrides)
    return feature


def main():
    tools = get_default_tools()
    material = get_default_materials()[0]
    vmc = next(
        machine
        for machine in get_default_machines()
        if machine.get("machine_type") == "VMC"
    )

    assert vmc["axis_count"] == 3
    assert vmc["indexed_3plus2"] is False
    assert vmc["simultaneous_5_axis"] is False

    side = assess_setup_access(vmc, "Front")
    assert side["status"] == "requires_setup"
    assert side["method"] == "manual_refixure"
    assert side["blocked"] is False

    bottom = assess_setup_access(vmc, "Bottom")
    assert bottom["status"] == "requires_setup"
    assert bottom["method"] == "manual_flip"

    hmc = normalize_machine_capabilities({"machine_type": "HMC"})
    indexed = assess_setup_access(hmc, "Right")
    assert indexed["status"] == "supported"
    assert indexed["method"] == "indexed_3plus2"

    five_axis = normalize_machine_capabilities({
        "machine_type": "VMC",
        "axis_count": 5,
        "indexed_3plus2": True,
        "simultaneous_5_axis": True,
    })
    simultaneous = assess_setup_access(
        five_axis,
        "Top",
        requires_simultaneous_5_axis=True,
    )
    assert simultaneous["status"] == "supported"
    assert simultaneous["method"] == "simultaneous_5_axis"

    blocked_five_axis = assess_setup_access(
        vmc,
        "Top",
        requires_simultaneous_5_axis=True,
    )
    assert blocked_five_axis["blocked"] is True

    top_ops = plan_operations([_feature()], tools, material, vmc)
    assert top_ops
    assert all(op["accessibility_status"] == "supported" for op in top_ops)
    assert all(op["setup_method"] == "direct_3_axis" for op in top_ops)

    detector_alias_ops = plan_operations(
        [
            _feature(feature_type="Face milling"),
            _feature(
                feature_type="Large hole / boring",
                physical_feature_id="PF-large-bore-alias",
            ),
        ],
        tools,
        material,
        vmc,
    )
    assert detector_alias_ops
    assert not any(op["operation_type"] == "Manual Review" for op in detector_alias_ops)
    assert {op["feature_type"] for op in detector_alias_ops} == {
        "Face Milling",
        "Large Hole / Boring",
    }

    side_ops = plan_operations([_feature(setup="Left")], tools, material, vmc)
    assert side_ops
    assert all(op["accessibility_status"] == "requires_setup" for op in side_ops)
    assert all(op["planning_blocked"] is False for op in side_ops)

    unknown_ops = plan_operations(
        [_feature(feature_type="Freeform Surface", setup="Top")],
        tools,
        material,
        vmc,
    )
    assert len(unknown_ops) == 1
    assert unknown_ops[0]["operation_type"] == "Manual Review"
    assert unknown_ops[0]["tool_number"] == 0
    assert unknown_ops[0]["planning_blocked"] is True

    summary = machine_feasibility_summary(top_ops + side_ops + unknown_ops)
    assert summary["blocked"] == 1
    assert summary["manual_review"] == 1
    assert summary["requires_setup"] == len(side_ops)

    print("PASS: machine capability and setup accessibility regression")


if __name__ == "__main__":
    main()
