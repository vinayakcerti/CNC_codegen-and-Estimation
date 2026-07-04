"""DFM / machinability scoring for 3-axis milling.

Runs the detected feature candidates through the existing planning pipeline
(plan_operations -> tool selection -> feasibility gates) and reduces the
result to a single explainable machinability percentage plus an issue list —
the same idea as Toolpath's "Machinable Surface Area" indicator, but driven
by the shop's actual tool library and machine limits.
"""
from __future__ import annotations

from .operation_planner import plan_operations, setup_labels_for_operations


def _candidates_to_features(candidates):
    """Map detected candidates to the feature shape plan_operations expects."""
    features = []
    for i, c in enumerate(candidates):
        features.append({
            "feature_type": c.get("feature_type", ""),
            "feature_name": c.get("feature_name") or f"Feature {i + 1}",
            "diameter": c.get("diameter") or 0,
            "length": c.get("length") or 0,
            "width": c.get("width") or 0,
            "depth": c.get("depth") or 0,
            "x_pos": c.get("x_pos", 0) or 0,
            "y_pos": c.get("y_pos", 0) or 0,
            "quantity": int(c.get("quantity", 1) or 1),
            "setup_label": c.get("setup") or c.get("setup_label") or "Top",
            "source_candidate_id": c.get("candidate_id", ""),
        })
    return features


def compute_dfm_score(candidates, tools, material, machine=None) -> dict:
    """Compute a machinability score for detected feature candidates.

    Returns dict:
        score_pct        : 0-100 int — headline machinability percentage
        grade            : "A" | "B" | "C" | "D"
        total_features   : int
        machinable       : int — features with no blocked operation
        at_risk          : int — features with warnings but not blocked
        blocked          : int — features with >=1 blocked operation
        setup_count      : int — distinct setups needed
        setup_labels     : list[str]
        issues           : list of {"severity": "blocked"|"warning",
                                    "feature": str, "message": str}
        total_operations : int
        blocked_operations: int
    """
    empty = {
        "score_pct": 0, "grade": "—", "total_features": 0,
        "machinable": 0, "at_risk": 0, "blocked": 0,
        "setup_count": 0, "setup_labels": [], "issues": [],
        "total_operations": 0, "blocked_operations": 0,
    }
    if not candidates:
        return empty

    features = _candidates_to_features(candidates)
    try:
        operations = plan_operations(features, tools, material, machine)
    except Exception as exc:
        empty["issues"] = [{
            "severity": "blocked", "feature": "—",
            "message": f"Operation planning failed: {exc}",
        }]
        return empty

    # Per-feature verdicts from that feature's operations
    per_feature: dict[str, dict] = {}
    issues = []
    seen_msgs = set()
    blocked_ops = 0
    for op in operations:
        fname = op.get("feature_name", "—")
        # Strip rough/finish suffixes so ops group back to their feature
        base = fname.replace(" (Rough)", "").replace(" (Finish)", "")
        rec = per_feature.setdefault(base, {"blocked": False, "warned": False})
        if op.get("planning_blocked"):
            rec["blocked"] = True
            blocked_ops += 1
        elif op.get("tool_warning"):
            rec["warned"] = True
        msg = (op.get("tool_warning") or "").strip()
        if msg and (base, msg) not in seen_msgs:
            seen_msgs.add((base, msg))
            issues.append({
                "severity": "blocked" if op.get("planning_blocked") else "warning",
                "feature": base,
                "message": msg,
            })

    total = len(per_feature)
    blocked = sum(1 for r in per_feature.values() if r["blocked"])
    at_risk = sum(1 for r in per_feature.values()
                  if r["warned"] and not r["blocked"])
    machinable = total - blocked

    # Score: fraction of features fully machinable, with a light penalty for
    # at-risk (warned) features. Ops-level ratio blended in so one bad
    # operation on a multi-op feature still costs something.
    ops_total = len(operations)
    ops_ok = ops_total - blocked_ops
    feature_ratio = machinable / total if total else 0.0
    ops_ratio = ops_ok / ops_total if ops_total else 0.0
    score = 100.0 * (0.7 * feature_ratio + 0.3 * ops_ratio)
    score -= 3.0 * at_risk          # soft penalty per at-risk feature
    score = max(0, min(100, round(score)))

    grade = ("A" if score >= 90 else
             "B" if score >= 75 else
             "C" if score >= 60 else "D")

    setup_labels = setup_labels_for_operations(operations)

    # Blocked issues first, then warnings
    issues.sort(key=lambda i: (i["severity"] != "blocked", i["feature"]))

    return {
        "score_pct": score,
        "grade": grade,
        "total_features": total,
        "machinable": machinable,
        "at_risk": at_risk,
        "blocked": blocked,
        "setup_count": len(setup_labels),
        "setup_labels": list(setup_labels),
        "issues": issues,
        "total_operations": ops_total,
        "blocked_operations": blocked_ops,
    }
