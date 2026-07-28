"""Validate the campaign-aware experiment index without rewriting artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


REQUIRED_COLUMNS = {
    "run_key", "campaign", "method", "family", "scenario", "ratio",
    "variant", "execution_profile", "status", "destination", "provenance",
}


def audit(index_csv: Path, summary_json: Path, artifact_root: Path | None = None) -> dict[str, object]:
    with index_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        rows = list(reader)
    errors: list[str] = []
    missing_columns = sorted(REQUIRED_COLUMNS - columns)
    if missing_columns:
        errors.append(f"missing index columns: {', '.join(missing_columns)}")
    keys = [row.get("run_key", "") for row in rows]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if key and count > 1)
    if duplicate_keys:
        errors.append(f"duplicate run_key values: {len(duplicate_keys)}")
    empty_keys = sum(not key for key in keys)
    if empty_keys:
        errors.append(f"empty run_key values: {empty_keys}")
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    if summary.get("required_artifact_missing_count") not in (None, 0):
        errors.append(f"summary required_artifact_missing_count={summary['required_artifact_missing_count']}")
    if summary.get("campaign_aware_run_key_duplicates") not in (None, 0):
        errors.append(f"summary campaign_aware_run_key_duplicates={summary['campaign_aware_run_key_duplicates']}")
    missing_destinations: list[str] = []
    if artifact_root is not None:
        for row in rows:
            destination = row.get("destination", "")
            if destination and not (artifact_root / destination).exists():
                missing_destinations.append(destination)
        if missing_destinations:
            errors.append(f"missing destination directories: {len(missing_destinations)}")
    trace_path = index_csv.parent / "thesis_run_traceability.csv"
    table_path = index_csv.parent / "thesis_table_manifest.csv"
    trace_rows: list[dict[str, str]] = []
    table_rows: list[dict[str, str]] = []
    if trace_path.exists():
        with trace_path.open("r", encoding="utf-8-sig", newline="") as handle:
            trace_rows = list(csv.DictReader(handle))
        trace_keys = [row.get("run_key", "") for row in trace_rows]
        if trace_keys != keys:
            errors.append("thesis traceability run_key sequence does not match run_index.csv")
        required_trace_fields = {
            "thesis_table_ids", "run_key", "run_id", "campaign", "method_id",
            "run_manifest_sha256", "generated_payloads_sha256", "quality_metrics_sha256",
            "rf_metrics_sha256", "waf_source_row_start_inclusive", "waf_source_row_end_exclusive",
        }
        missing_trace_values = sum(
            any(not row.get(field, "") for field in required_trace_fields) for row in trace_rows
        )
        if missing_trace_values:
            errors.append(f"traceability rows missing required values: {missing_trace_values}")
    else:
        errors.append(f"missing thesis traceability manifest: {trace_path}")
    if table_path.exists():
        with table_path.open("r", encoding="utf-8-sig", newline="") as handle:
            table_rows = list(csv.DictReader(handle))
        table_ids = [row.get("thesis_table_id", "") for row in table_rows]
        if len(table_rows) != 21 or len(set(table_ids)) != 21:
            errors.append("thesis table manifest must contain 21 unique Chapter 3 tables")
    else:
        errors.append(f"missing thesis table manifest: {table_path}")
    return {
        "schema": "provenance-audit-v1",
        "index_rows": len(rows),
        "unique_run_keys": len(set(keys)),
        "missing_columns": missing_columns,
        "duplicate_run_keys": duplicate_keys,
        "missing_destinations": missing_destinations[:50],
        "summary_total_runs": summary.get("total_runs"),
        "thesis_traceability_rows": len(trace_rows),
        "thesis_table_rows": len(table_rows),
        "errors": errors,
        "ok": not errors,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=Path("final_result_info/_index/run_index.csv"))
    parser.add_argument("--summary", type=Path, default=Path("final_result_info/_index/summary.json"))
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    result = audit(args.index, args.summary, args.artifact_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
