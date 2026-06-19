"""
VMC Feature Detection Regression Runner
Usage:
    python tests/run_feature_detection_regression.py [--allow-missing] [--verbose]

Options:
    --allow-missing   Missing STEP files are reported but do not count as failures.
    --verbose         Print full candidate list for all files, not just failures.
"""

import sys
import os
import json
import argparse
from pathlib import Path
from collections import Counter

# Add project root to sys.path so modules/ is importable
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.step_parser import detect_feature_candidates_from_cadquery_file

_EXPECTATIONS_FILE = _SCRIPT_DIR / "feature_detection_expectations.json"
_TEST_SAMPLES_DIR  = _PROJECT_ROOT / "test_samples"
_REPORT_DIR        = _PROJECT_ROOT / "_bmad-output" / "implementation-artifacts"

# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(description="VMC feature-detection regression runner")
    p.add_argument("--allow-missing", action="store_true",
                   help="Missing STEP files are reported but not counted as failures")
    p.add_argument("--verbose", action="store_true",
                   help="Print candidate list for ALL files, not just failures")
    return p.parse_args()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_feature_types(candidates):
    c = Counter()
    for cand in candidates:
        ft = cand.get("feature_type") or "Unknown"
        c[ft] += 1
    return dict(c)


def _format_counts(counts_dict):
    if not counts_dict:
        return "(none)"
    return ", ".join(f"{k}={v}" for k, v in sorted(counts_dict.items()))


def _counts_match(expected, actual):
    for ft, exp_n in expected.items():
        if actual.get(ft, 0) != exp_n:
            return False
    # Also fail if actual has feature types not in expected
    for ft, act_n in actual.items():
        if ft not in expected and act_n > 0:
            return False
    return True


def _print_candidates(candidates, indent="  "):
    if not candidates:
        print(f"{indent}(no candidates)")
        return
    for c in candidates:
        print(f"{indent}{c.get('candidate_id','?')}  {c.get('feature_type','?')}  "
              f"{c.get('feature_name','?')}  conf={c.get('confidence','?')}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = _parse_args()

    with open(_EXPECTATIONS_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    expectations = data["expectations"]
    expected_files = {e["file"] for e in expectations}

    # Find STEP files in test_samples not covered by expectations
    all_step_files = {p.name for p in _TEST_SAMPLES_DIR.glob("*.step")}
    uncovered = sorted(all_step_files - expected_files)

    results = []  # list of dicts per entry

    print("=" * 72)
    print("VMC Feature Detection Regression")
    print(f"Samples dir : {_TEST_SAMPLES_DIR}")
    print(f"Expectations: {len(expectations)} entries")
    print("=" * 72)

    for entry in expectations:
        fname    = entry["file"]
        notes    = entry.get("notes", "")
        expected = entry.get("expected_counts", {})
        fpath    = _TEST_SAMPLES_DIR / fname

        if not fpath.exists():
            status = "MISSING"
            actual = {}
            candidates = []
        else:
            try:
                result = detect_feature_candidates_from_cadquery_file(str(fpath))
                if not result.get("success", False):
                    warns = result.get("warnings", [])
                    raise RuntimeError("; ".join(warns) if warns else "parser returned success=False")
                candidates = result.get("candidate_features", [])
                actual = _count_feature_types(candidates)
                status = "PASS" if _counts_match(expected, actual) else "FAIL"
            except Exception as exc:
                status = "ERROR"
                actual = {}
                candidates = []
                print(f"  [ERROR] {fname}: {exc}")

        results.append({
            "file": fname, "notes": notes, "status": status,
            "expected": expected, "actual": actual, "candidates": candidates,
        })

        exp_str = _format_counts(expected)
        act_str = _format_counts(actual)
        print(f"\n[{status:7s}]  {fname}")
        print(f"  Notes   : {notes}")
        print(f"  Expected: {exp_str}")
        print(f"  Actual  : {act_str}")

        if status == "FAIL" or args.verbose:
            print("  Candidates:")
            _print_candidates(candidates)

    # ── Summary ───────────────────────────────────────────────────────────────
    n_pass    = sum(1 for r in results if r["status"] == "PASS")
    n_fail    = sum(1 for r in results if r["status"] == "FAIL")
    n_missing = sum(1 for r in results if r["status"] == "MISSING")
    n_error   = sum(1 for r in results if r["status"] == "ERROR")
    n_total   = len(results)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print(f"  Total    : {n_total}")
    print(f"  PASS     : {n_pass}")
    print(f"  FAIL     : {n_fail}")
    print(f"  MISSING  : {n_missing}")
    print(f"  ERROR    : {n_error}")

    if uncovered:
        print(f"\nUncovered STEP files in test_samples/ ({len(uncovered)}):")
        for f in uncovered:
            print(f"  {f}")

    # ── Exit code ─────────────────────────────────────────────────────────────
    failures = n_fail + n_error
    if not args.allow_missing:
        failures += n_missing

    if failures == 0:
        print("\nResult: ALL PRESENT TESTS PASSED")
    else:
        print(f"\nResult: {failures} FAILURE(S)")

    # ── Markdown report ───────────────────────────────────────────────────────
    _write_report(results, uncovered, n_pass, n_fail, n_missing, n_error, args)

    return 0 if failures == 0 else 1


def _write_report(results, uncovered, n_pass, n_fail, n_missing, n_error, args):
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _REPORT_DIR / "vmc_regression_test_report.md"

    from datetime import date
    today = date.today().isoformat()

    lines = []
    lines.append("# VMC Feature Detection Regression Report\n")
    lines.append(f"**Date:** {today}  ")
    lines.append(f"**Branch:** v2-feature-review-engine  ")
    _opt_str = " ".join(filter(None, [
        "--allow-missing" if args.allow_missing else "",
        "--verbose" if args.verbose else "",
    ])) or "(none)"
    lines.append(f"**Options:** `{_opt_str}`  \n")

    lines.append("## Summary\n")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total entries | {len(results)} |")
    lines.append(f"| PASS | {n_pass} |")
    lines.append(f"| FAIL | {n_fail} |")
    lines.append(f"| MISSING | {n_missing} |")
    lines.append(f"| ERROR | {n_error} |\n")

    lines.append("## Per-File Results\n")
    lines.append("| File | Status | Expected | Actual | Notes |")
    lines.append("|------|--------|----------|--------|-------|")
    for r in results:
        lines.append(
            f"| `{r['file']}` | **{r['status']}** "
            f"| {_format_counts(r['expected'])} "
            f"| {_format_counts(r['actual'])} "
            f"| {r['notes']} |"
        )

    if uncovered:
        lines.append("\n## Uncovered STEP Files\n")
        lines.append("These files exist in `test_samples/` but have no entry in `feature_detection_expectations.json`:\n")
        for f in uncovered:
            lines.append(f"- `{f}`")

    lines.append("\n## Failure Details\n")
    failed = [r for r in results if r["status"] in ("FAIL", "ERROR")]
    if not failed:
        lines.append("No failures.")
    else:
        for r in failed:
            lines.append(f"\n### {r['file']} — {r['status']}\n")
            lines.append(f"- **Expected:** {_format_counts(r['expected'])}")
            lines.append(f"- **Actual:** {_format_counts(r['actual'])}")
            lines.append(f"- **Notes:** {r['notes']}")
            if r["candidates"]:
                lines.append("\nCandidates detected:\n")
                lines.append("| ID | Type | Name | Confidence |")
                lines.append("|----|------|------|------------|")
                for c in r["candidates"]:
                    lines.append(
                        f"| {c.get('candidate_id','?')} "
                        f"| {c.get('feature_type','?')} "
                        f"| {c.get('feature_name','?')} "
                        f"| {c.get('confidence','?')} |"
                    )

    report_text = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    sys.exit(main())
