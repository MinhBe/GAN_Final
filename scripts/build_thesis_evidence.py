"""Build deterministic thesis-to-run and quality-to-WAF evidence artifacts.

The script never rewrites original experiment artifacts.  It reads the
campaign-aware indices, uses Git objects as a fallback for sparse checkouts,
and writes only new derived manifests.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Iterable


METHOD_DISPLAY_VI = {
    "smote": "SMOTE",
    "gan": "Vanilla GAN",
    "ctgan": "CTGAN",
    "seqgan_master": "SeqGAN cơ sở",
    "seqgan_improved": "SeqGAN cải tiến",
}

TABLES_BY_CAMPAIGN = {
    "phase1_survey": ["Bảng 3.5", "Bảng 3.6", "Bảng 3.19", "Hình 3.12"],
    "phase2a_scenario_search": ["Bảng 3.5", "Bảng 3.7", "Bảng 3.8", "Bảng 3.19", "Hình 3.12"],
    "phase2b_ratio_search_medium": ["Bảng 3.5", "Bảng 3.9", "Bảng 3.10", "Bảng 3.13", "Bảng 3.19", "Hình 3.12"],
    "phase3_seqgan_improved_test_medium": ["Bảng 3.5", "Bảng 3.11", "Bảng 3.12", "Bảng 3.13", "Bảng 3.14", "Bảng 3.19", "Hình 3.12"],
    "final_full/baselines": ["Bảng 3.5", "Bảng 3.13", "Bảng 3.14", "Bảng 3.15", "Bảng 3.18", "Bảng 3.19", "Bảng 3.20", "Hình 3.12"],
    "final_full/seqgan_improved_refinement": ["Bảng 3.5", "Bảng 3.13", "Bảng 3.14", "Bảng 3.16", "Bảng 3.17", "Bảng 3.18", "Bảng 3.19", "Bảng 3.20", "Bảng 3.21", "Hình 3.12"],
}

EXPECTED_CORRELATIONS = {
    "garbage_rate": 0.879048,
    "sql_structure_rate": -0.879048,
    "family_motif_coverage": -0.626259,
    "family_motif_hit_rate": -0.901313,
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_batch_read(repo: Path, paths: Iterable[str]) -> dict[str, bytes]:
    unique_paths = list(dict.fromkeys(paths))
    process = subprocess.Popen(
        ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    output: dict[str, bytes] = {}
    try:
        for path in unique_paths:
            process.stdin.write(f"HEAD:{path}\n".encode("utf-8"))
            process.stdin.flush()
            header = process.stdout.readline().decode("utf-8", errors="replace").strip()
            if header.endswith(" missing"):
                continue
            parts = header.split()
            if len(parts) != 3:
                raise RuntimeError(f"Unexpected git cat-file response for {path}: {header}")
            size = int(parts[2])
            output[path] = process.stdout.read(size)
            process.stdout.read(1)
    finally:
        process.stdin.close()
        process.wait(timeout=30)
    if process.returncode:
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        raise RuntimeError(f"git cat-file failed: {stderr}")
    return output


def artifact_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    wanted = {
        "run_manifest.json",
        "training_metadata.json",
        "generated_payloads.csv",
        "quality_metrics.json",
        "rf_metrics.json",
    }
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        name = Path(row.get("relative_path", "")).name
        if row.get("run_key") and name in wanted:
            result[(row["run_key"], name)] = row
    return result


def artifact_fields(mapping: dict[tuple[str, str], dict[str, str]], run_key: str, name: str) -> tuple[str, str]:
    row = mapping.get((run_key, name), {})
    relative_path = row.get("relative_path", "")
    if relative_path and not relative_path.startswith("final_result_info/"):
        relative_path = f"final_result_info/{relative_path}"
    return relative_path, row.get("sha256", "")


def build_traceability(
    repo: Path,
    run_index: Path,
    inventory: Path,
    waf_sources: Path,
    output: Path,
) -> list[dict[str, str]]:
    runs = read_csv(run_index)
    artifacts = artifact_map(read_csv(inventory))
    source_by_key = {row["run_key"]: row for row in read_csv(waf_sources)}
    manifest_paths = [artifact_fields(artifacts, row["run_key"], "run_manifest.json")[0] for row in runs]
    manifest_blobs = git_batch_read(repo, [path for path in manifest_paths if path])

    rows: list[dict[str, str]] = []
    for run in runs:
        run_key = run["run_key"]
        source = source_by_key.get(run_key, {})
        run_manifest_path, run_manifest_sha = artifact_fields(artifacts, run_key, "run_manifest.json")
        manifest: dict[str, object] = {}
        if run_manifest_path and run_manifest_path in manifest_blobs:
            manifest = json.loads(manifest_blobs[run_manifest_path].decode("utf-8-sig"))
        inputs = manifest.get("inputs") if isinstance(manifest.get("inputs"), dict) else {}
        dataset = inputs.get("dataset") if isinstance(inputs, dict) and isinstance(inputs.get("dataset"), dict) else {}
        holdout = inputs.get("holdout") if isinstance(inputs, dict) and isinstance(inputs.get("holdout"), dict) else {}
        training_path, training_sha = artifact_fields(artifacts, run_key, "training_metadata.json")
        payload_path, payload_sha = artifact_fields(artifacts, run_key, "generated_payloads.csv")
        quality_path, quality_sha = artifact_fields(artifacts, run_key, "quality_metrics.json")
        rf_path, rf_sha = artifact_fields(artifacts, run_key, "rf_metrics.json")
        start = source.get("row_start_inclusive", "")
        end = source.get("row_end_exclusive", "")
        rows.append({
            "thesis_table_ids": ";".join(TABLES_BY_CAMPAIGN.get(run["campaign"], [])),
            "run_key": run_key,
            "run_id": str(manifest.get("run_id", "")),
            "campaign": run["campaign"],
            "method_id": run["method"],
            "method_display_vi": METHOD_DISPLAY_VI.get(run["method"], run["method"]),
            "family": run["family"],
            "scenario": run["scenario"],
            "ratio": run["ratio"],
            "variant": run["variant"],
            "execution_profile": run["execution_profile"],
            "status": run["status"],
            "destination": run["destination"],
            "config_path": str(manifest.get("config", "")),
            "config_sha256": str(manifest.get("config_sha256", "")),
            "dataset_path": str(dataset.get("path", "")),
            "dataset_sha256": str(dataset.get("sha256", "")),
            "holdout_path": str(holdout.get("path", "")),
            "holdout_sha256": str(holdout.get("sha256", "")),
            "run_manifest_path": run_manifest_path,
            "run_manifest_sha256": run_manifest_sha,
            "training_metadata_path": training_path,
            "training_metadata_sha256": training_sha,
            "generated_payloads_path": payload_path,
            "generated_payloads_sha256": payload_sha,
            "quality_metrics_path": quality_path,
            "quality_metrics_sha256": quality_sha,
            "rf_metrics_path": rf_path,
            "rf_metrics_sha256": rf_sha,
            "waf_source_row_start_inclusive": start,
            "waf_source_row_end_exclusive": end,
            "waf_source_row_count": source.get("row_count", ""),
            "empty_payload_count": source.get("empty_payload_count", ""),
            "waf_source_csv_sha256": source.get("source_csv_sha256", ""),
            "waf_probe_join_rule": f"source_row >= {start} and source_row < {end}" if start and end else "",
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Pearson correlation requires equally sized vectors with at least two values")
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    if denominator == 0:
        raise ValueError("Pearson correlation is undefined for a constant vector")
    return numerator / denominator


def build_correlation(
    repo: Path,
    trace_rows: list[dict[str, str]],
    probe_results: Path,
    output_csv: Path,
    output_json: Path,
    source_manifest: Path,
) -> dict[str, object]:
    ordered = sorted(trace_rows, key=lambda row: int(row["waf_source_row_start_inclusive"]))
    starts = [int(row["waf_source_row_start_inclusive"]) for row in ordered]
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with probe_results.open("r", encoding="utf-8-sig", newline="") as handle:
        for probe in csv.DictReader(handle):
            source_row = int(probe["source_row"])
            index = bisect.bisect_right(starts, source_row) - 1
            if index < 0 or source_row >= int(ordered[index]["waf_source_row_end_exclusive"]):
                raise ValueError(f"WAF source_row {source_row} is outside every run range")
            run_key = ordered[index]["run_key"]
            outcome = probe.get("outcome", "")
            if outcome == "blocked":
                counts[run_key]["blocked"] += 1
                counts[run_key]["eligible"] += 1
            elif outcome in {"bypass", "not_blocked"}:
                counts[run_key]["not_blocked"] += 1
                counts[run_key]["eligible"] += 1
            elif outcome == "skipped_get_too_long":
                counts[run_key]["not_sent_too_long"] += 1
            elif outcome:
                counts[run_key][outcome] += 1

    quality_paths = [row["quality_metrics_path"] for row in trace_rows if row["quality_metrics_path"]]
    quality_blobs = git_batch_read(repo, quality_paths)
    derived_rows: list[dict[str, object]] = []
    for row in trace_rows:
        quality_path = row["quality_metrics_path"]
        quality = json.loads(quality_blobs[quality_path].decode("utf-8-sig"))
        aggregate = counts[row["run_key"]]
        eligible = aggregate["eligible"]
        derived_rows.append({
            "run_key": row["run_key"],
            "campaign": row["campaign"],
            "method_id": row["method_id"],
            "method_display_vi": row["method_display_vi"],
            "family": row["family"],
            "scenario": row["scenario"],
            "ratio": row["ratio"],
            "variant": row["variant"],
            "garbage_rate": quality["garbage_rate"],
            "sql_structure_rate": quality["sql_structure_rate"],
            "unique_rate": quality["unique_rate"],
            "normalized_unique_rate": quality["normalized_unique_rate"],
            "dominant_payload_share": quality["dominant_payload_share"],
            "normalized_dominant_payload_share": quality["normalized_dominant_payload_share"],
            "family_motif_coverage": quality["family_motif_coverage"],
            "family_motif_hit_rate": quality["family_motif_hit_rate"],
            "eligible_requests": eligible,
            "blocked_requests": aggregate["blocked"],
            "not_blocked_requests": aggregate["not_blocked"],
            "not_sent_too_long": aggregate["not_sent_too_long"],
            "waf_not_blocked_rate": aggregate["not_blocked"] / eligible if eligible else "",
            "quality_metrics_path": quality_path,
            "quality_metrics_sha256": row["quality_metrics_sha256"],
        })

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(derived_rows[0]))
        writer.writeheader()
        writer.writerows(derived_rows)

    correlations: dict[str, float] = {}
    ys = [float(row["waf_not_blocked_rate"]) for row in derived_rows]
    for metric in EXPECTED_CORRELATIONS:
        correlations[metric] = pearson([float(row[metric]) for row in derived_rows], ys)
    deviations = {metric: correlations[metric] - expected for metric, expected in EXPECTED_CORRELATIONS.items()}
    if any(abs(value) > 0.000001 for value in deviations.values()):
        raise ValueError(f"Correlation values do not reproduce the thesis: {deviations}")

    summary: dict[str, object] = {
        "schema_version": "thesis-quality-waf-correlation-v1",
        "thesis_figure_id": "Hình 3.12",
        "thesis_section": "3.4.3",
        "run_count": len(derived_rows),
        "eligible_request_count": sum(int(row["eligible_requests"]) for row in derived_rows),
        "blocked_request_count": sum(int(row["blocked_requests"]) for row in derived_rows),
        "not_blocked_request_count": sum(int(row["not_blocked_requests"]) for row in derived_rows),
        "not_sent_too_long_count": sum(int(row["not_sent_too_long"]) for row in derived_rows),
        "denominator_policy": "blocked + not_blocked; excludes not_sent_too_long, format errors and network errors",
        "correlation_method": "Pearson correlation across campaign-aware run_key rows",
        "correlations_with_waf_not_blocked_rate": correlations,
        "historical_alias": {"bypass_rate": "waf_not_blocked_rate"},
        "inputs": {
            "waf_probe_results": {
                "path": "waf_evaluation/waf_evaluation/campaign/full/waf_probe_results.csv (restore from ZIP)",
                "sha256": sha256_file(probe_results),
            },
            "waf_source_manifest": {
                "path": str(source_manifest.relative_to(repo).as_posix()),
                "sha256": sha256_file(source_manifest),
            },
            "quality_metrics": "one quality_metrics.json per run; hashes are recorded in run_quality_waf_correlation.csv",
        },
        "derived_csv": str(output_csv.relative_to(repo).as_posix()),
    }
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-index", type=Path, default=Path("final_result_info/_index/run_index.csv"))
    parser.add_argument("--inventory", type=Path, default=Path("final_result_info/_index/artifact_inventory.csv"))
    parser.add_argument("--waf-sources", type=Path, default=Path("waf_evaluation/waf_evaluation/input/all_payloads_sources.csv"))
    parser.add_argument("--probe-results", type=Path)
    parser.add_argument("--trace-output", type=Path, default=Path("final_result_info/_index/thesis_run_traceability.csv"))
    parser.add_argument("--correlation-csv", type=Path, default=Path("waf_evaluation/waf_evaluation/campaign/full/run_quality_waf_correlation.csv"))
    parser.add_argument("--correlation-json", type=Path, default=Path("waf_evaluation/waf_evaluation/campaign/full/correlation_summary_canonical.json"))
    args = parser.parse_args()
    repo = args.repo.resolve()
    resolve = lambda path: path if path.is_absolute() else repo / path
    trace_rows = build_traceability(
        repo,
        resolve(args.run_index),
        resolve(args.inventory),
        resolve(args.waf_sources),
        resolve(args.trace_output),
    )
    result: dict[str, object] = {"traceability_rows": len(trace_rows), "traceability_output": str(resolve(args.trace_output))}
    if args.probe_results:
        summary = build_correlation(
            repo,
            trace_rows,
            resolve(args.probe_results),
            resolve(args.correlation_csv),
            resolve(args.correlation_json),
            resolve(args.waf_sources),
        )
        result["correlation"] = summary
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
