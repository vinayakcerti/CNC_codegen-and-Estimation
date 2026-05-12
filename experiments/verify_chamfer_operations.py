"""Quick verification that Chamfer feature produces 1 dedicated Chamfer operation."""
import sys, json, pathlib
sys.path.insert(0, r"C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro")
from modules.operation_planner import plan_operations

_root = pathlib.Path(r"C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro")
tools = json.loads((_root / "data" / "default_tools.json").read_text())
material = json.loads((_root / "data" / "default_materials.json").read_text())[0]

chamfer_feature = {
    "feature_type":     "Chamfer",
    "feature_name":     "Top edge chamfer ~2.0×2.0 mm (4 faces)",
    "quantity":         4,
    "diameter":         None,
    "length":           None,
    "width":            2.0,
    "depth":            2.0,
    "x_pos":            0.0,
    "y_pos":            0.0,
    "priority":         4,
    "accepted":         True,
    "ignored":          False,
}

ops = plan_operations([chamfer_feature], tools, material)

print(f"Operations generated: {len(ops)}")
print()
for op in ops:
    print(f"  Op {op['op_num']:02d}  {op['operation_type']:<20}  "
          f"tool={op['tool_name']:<24}  path={op['est_path_length_mm']:>7.1f} mm")
    print(f"         notes: {op['notes']}")
    print()

assert len(ops) == 1, f"Expected 1 op, got {len(ops)}"
assert ops[0]["operation_type"] == "Chamfer", ops[0]["operation_type"]
assert ops[0]["feature_type"] == "Chamfer"
assert "chamfer top edges" in ops[0]["notes"].lower(), ops[0]["notes"]
assert "chamfer mill" in ops[0]["notes"].lower(), ops[0]["notes"]
assert "verify chamfer size" in ops[0]["notes"].lower(), ops[0]["notes"]
assert ops[0]["est_path_length_mm"] > 0, ops[0]["est_path_length_mm"]
print("All assertions passed.")
