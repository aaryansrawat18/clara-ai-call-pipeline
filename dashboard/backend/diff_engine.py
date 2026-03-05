"""
Diff engine for Clara Answers dashboard.
Computes structured diffs between v1 and v2 artifacts using Python standard library.
"""

import json
import difflib
from typing import Dict, Any, List, Optional


def compute_json_diff(v1: Dict[str, Any], v2: Dict[str, Any], path: str = "") -> List[Dict]:
    """Compute a structured diff between two JSON objects."""
    changes = []

    all_keys = set(list(v1.keys()) + list(v2.keys()))

    for key in sorted(all_keys):
        current_path = f"{path}.{key}" if path else key
        v1_val = v1.get(key)
        v2_val = v2.get(key)

        if v1_val == v2_val:
            continue

        if key not in v1:
            changes.append({
                "path": current_path,
                "type": "added",
                "old_value": None,
                "new_value": v2_val
            })
        elif key not in v2:
            changes.append({
                "path": current_path,
                "type": "removed",
                "old_value": v1_val,
                "new_value": None
            })
        elif isinstance(v1_val, dict) and isinstance(v2_val, dict):
            changes.extend(compute_json_diff(v1_val, v2_val, current_path))
        elif isinstance(v1_val, list) and isinstance(v2_val, list):
            v1_set = set(str(x) for x in v1_val)
            v2_set = set(str(x) for x in v2_val)
            added = v2_set - v1_set
            removed = v1_set - v2_set

            if added or removed:
                changes.append({
                    "path": current_path,
                    "type": "modified_list",
                    "added": sorted(list(added)),
                    "removed": sorted(list(removed)),
                    "old_value": v1_val,
                    "new_value": v2_val
                })
        else:
            changes.append({
                "path": current_path,
                "type": "modified",
                "old_value": v1_val,
                "new_value": v2_val
            })

    return changes


def compute_text_diff(v1_text: str, v2_text: str) -> Dict[str, Any]:
    """Compute a unified text diff between two strings."""
    v1_lines = v1_text.splitlines(keepends=True)
    v2_lines = v2_text.splitlines(keepends=True)

    diff = list(difflib.unified_diff(v1_lines, v2_lines, fromfile="v1", tofile="v2", lineterm=""))

    # Also generate side-by-side diff
    differ = difflib.HtmlDiff()
    html_table = differ.make_table(
        v1_text.splitlines(),
        v2_text.splitlines(),
        fromdesc="v1",
        todesc="v2",
        context=True,
        numlines=3
    )

    return {
        "unified_diff": diff,
        "html_diff": html_table,
        "v1_line_count": len(v1_lines),
        "v2_line_count": len(v2_lines),
        "additions": sum(1 for line in diff if line.startswith('+') and not line.startswith('+++')),
        "deletions": sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
    }


def compute_full_diff(v1_memo: Dict, v2_memo: Dict,
                      v1_spec: Dict, v2_spec: Dict) -> Dict[str, Any]:
    """Compute comprehensive diff between v1 and v2 for both memo and spec."""

    memo_changes = compute_json_diff(v1_memo, v2_memo)

    # Prompt diff
    v1_prompt = v1_spec.get("system_prompt", "")
    v2_prompt = v2_spec.get("system_prompt", "")
    prompt_diff = compute_text_diff(v1_prompt, v2_prompt)

    spec_changes = compute_json_diff(
        {k: v for k, v in v1_spec.items() if k != "system_prompt"},
        {k: v for k, v in v2_spec.items() if k != "system_prompt"}
    )

    # Summary statistics
    total_memo_changes = len(memo_changes)
    total_spec_changes = len(spec_changes)
    prompt_changed = v1_prompt != v2_prompt

    # Identify missing/incomplete fields in v2
    missing_fields = find_missing_fields(v2_memo)

    return {
        "memo_diff": {
            "changes": memo_changes,
            "total_changes": total_memo_changes
        },
        "spec_diff": {
            "changes": spec_changes,
            "total_changes": total_spec_changes,
            "prompt_diff": prompt_diff,
            "prompt_changed": prompt_changed
        },
        "summary": {
            "total_changes": total_memo_changes + total_spec_changes + (1 if prompt_changed else 0),
            "memo_fields_changed": total_memo_changes,
            "spec_fields_changed": total_spec_changes,
            "prompt_changed": prompt_changed,
            "prompt_additions": prompt_diff["additions"],
            "prompt_deletions": prompt_diff["deletions"]
        },
        "missing_fields": missing_fields
    }


def find_missing_fields(memo: Dict) -> List[str]:
    """Identify empty or missing fields in an account memo."""
    missing = []

    required_fields = {
        "account_id": "Account ID",
        "company_name": "Company Name",
        "office_address": "Office Address",
        "services_supported": "Services Supported",
        "emergency_definition": "Emergency Definitions",
        "after_hours_flow_summary": "After-Hours Flow Summary",
        "office_hours_flow_summary": "Office Hours Flow Summary"
    }

    for field, label in required_fields.items():
        val = memo.get(field)
        if not val or (isinstance(val, list) and len(val) == 0):
            missing.append(label)

    # Check business hours completeness
    bh = memo.get("business_hours", {})
    if not bh.get("timezone"):
        missing.append("Business Hours: Timezone")
    if not bh.get("days"):
        missing.append("Business Hours: Days")
    if not bh.get("start"):
        missing.append("Business Hours: Start Time")

    # Check unknowns
    unknowns = memo.get("questions_or_unknowns", [])
    if unknowns:
        missing.append(f"Has {len(unknowns)} unresolved question(s)")

    return missing
