"""Quick verification that Step feature produces 2 dedicated operations."""
import sys, json, pathlib
sys.path.insert(0, r"C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro")
from modules.operation_planner import plan_operations

_root = pathlib.Path(r"C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro")
tools = json.loads((_root / "data" / "default_tools.json").read_text())
material = json.loads((_root / "data" / "default_materials.json").read_text())[0]

step_feature = {
    "feature_type": "Step",
    "feature_name": "Step shoulder 90.0x30.0 depth 12.0 mm",
    "length": 90.0, "width": 30.0, "depth": 12.0,
    "x_pos": 0.0, "y_pos": 0.0,
    "diameter": None, "quantity": 1, "priority": 3,
    "accepted": True, "ignored": False,
}

ops = plan_operations([step_feature], tools, material)

print(f"Operations generated: {len(ops)}")
print()
for op in ops:
    print(f"  Op {op['op_num']:02d}  {op['operation_type']:<20}  "
          f"tool={op['tool_name']:<20}  path={op['est_path_length_mm']:>7.1f} mm")
    print(f"         notes: {op['notes']}")
    print()

assert len(ops) == 2, f"Expected 2 ops, got {len(ops)}"
assert ops[0]["operation_type"] == "Rough End Mill", ops[0]["operation_type"]
assert ops[1]["operation_type"] == "Finish End Mill", ops[1]["operation_type"]
assert ops[0]["feature_type"] == "Step"
assert ops[1]["feature_type"] == "Step"
assert "multiple depth" in ops[0]["notes"].lower(), ops[0]["notes"]
assert "floor" in ops[1]["notes"].lower(), ops[1]["notes"]
print("All assertions passed.")
