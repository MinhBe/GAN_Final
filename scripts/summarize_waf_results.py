from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Aggregate:
    probes: int = 0
    blocked: int = 0
    network_errors: int = 0
    latencies: list[float] = field(default_factory=list)

    def add(self, blocked: bool, network_error: bool, latency_ms: float) -> None:
        self.probes += 1
        self.blocked += int(blocked)
        self.network_errors += int(network_error)
        self.latencies.append(latency_ms)

    def metrics(self) -> dict[str, int | float]:
        ordered = sorted(self.latencies)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1) if ordered else 0
        bypassed = self.probes - self.blocked - self.network_errors
        return {
            "probes": self.probes,
            "blocked": self.blocked,
            "bypassed": bypassed,
            "network_errors": self.network_errors,
            "blocked_rate": self.blocked / self.probes if self.probes else 0.0,
            "bypass_rate": bypassed / self.probes if self.probes else 0.0,
            "latency_mean_ms": statistics.fmean(ordered) if ordered else 0.0,
            "latency_median_ms": statistics.median(ordered) if ordered else 0.0,
            "latency_p95_ms": ordered[p95_index] if ordered else 0.0,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_source_ranges(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Source manifest is empty")
    expected_start = 0
    for row in rows:
        start = int(row["row_start_inclusive"])
        end = int(row["row_end_exclusive"])
        if start != expected_start or end <= start:
            raise ValueError("Source manifest ranges must be contiguous and non-empty")
        expected_start = end
    return rows


def source_for_row(
    source_row: int,
    ranges: list[dict[str, str]],
    starts: list[int],
) -> dict[str, str]:
    index = bisect.bisect_right(starts, source_row) - 1
    if index < 0:
        raise ValueError(f"source_row {source_row} precedes the first manifest range")
    row = ranges[index]
    if source_row >= int(row["row_end_exclusive"]):
        raise ValueError(f"source_row {source_row} is outside the source manifest")
    return row


def write_breakdown(
    path: Path,
    dimensions: list[str],
    aggregates: dict[tuple[str, ...], Aggregate],
) -> None:
    metric_fields = [
        "probes",
        "blocked",
        "bypassed",
        "network_errors",
        "blocked_rate",
        "bypass_rate",
        "latency_mean_ms",
        "latency_median_ms",
        "latency_p95_ms",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*dimensions, *metric_fields])
        writer.writeheader()
        for key in sorted(aggregates):
            row = dict(zip(dimensions, key))
            row.update(aggregates[key].metrics())
            writer.writerow(row)


def markdown_table(rows: list[dict[str, object]], dimension: str) -> list[str]:
    lines = [
        f"| {dimension} | Probes | Blocked | Bypassed | Block rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row[dimension]} | {int(row['probes']):,} | "
            f"{int(row['blocked']):,} | {int(row['bypassed']):,} | "
            f"{float(row['blocked_rate']):.2%} |"
        )
    return lines


def summarize(
    results_csv: Path,
    source_manifest: Path,
    campaign_summary: Path,
    out_dir: Path,
    waf_image: str,
) -> dict[str, object]:
    ranges = load_source_ranges(source_manifest)
    starts = [int(row["row_start_inclusive"]) for row in ranges]
    expected_payload_rows = int(ranges[-1]["row_end_exclusive"])
    dimensions = {
        "by_run_http": ["model", "family", "scenario", "ratio", "http_method"],
        "by_run": ["model", "family", "scenario", "ratio"],
        "by_model": ["model"],
        "by_family": ["family"],
        "by_ratio": ["ratio"],
        "by_scenario": ["scenario"],
        "by_http_method": ["http_method"],
    }
    groups: dict[str, dict[tuple[str, ...], Aggregate]] = {
        name: defaultdict(Aggregate) for name in dimensions
    }
    overall = Aggregate()
    empty_payload = Aggregate()
    row_count = 0
    last_probe_index = -1

    with results_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for result in reader:
            probe_index = int(result["probe_index"])
            if probe_index != last_probe_index + 1:
                raise ValueError(f"Non-contiguous probe index at {probe_index}")
            last_probe_index = probe_index
            source_row = int(result["source_row"])
            source = source_for_row(source_row, ranges, starts)
            values = {
                "model": source["method"],
                "family": source["family"],
                "scenario": source["scenario"],
                "ratio": source["ratio"],
                "http_method": result["method"],
            }
            blocked = result["blocked"].casefold() == "true"
            network_error = result["status"] == ""
            latency = float(result["latency_ms"])
            overall.add(blocked, network_error, latency)
            if result["payload"] == "":
                empty_payload.add(blocked, network_error, latency)
            for name, keys in dimensions.items():
                key = tuple(values[field] for field in keys)
                groups[name][key].add(blocked, network_error, latency)
            row_count += 1

    campaign = json.loads(campaign_summary.read_text(encoding="utf-8"))
    expected_probes = int(campaign["probe_count"])
    if row_count != expected_probes:
        raise ValueError(f"Expected {expected_probes} probes, found {row_count}")
    if int(campaign["input_payload_count"]) != expected_payload_rows:
        raise ValueError("Campaign payload count does not match source manifest")

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name, keys in dimensions.items():
        path = out_dir / f"waf_breakdown_{name}.csv"
        write_breakdown(path, keys, groups[name])
        outputs[name] = str(path)

    model_rows = [
        {"model": key[0], **aggregate.metrics()}
        for key, aggregate in sorted(groups["by_model"].items())
    ]
    family_rows = [
        {"family": key[0], **aggregate.metrics()}
        for key, aggregate in sorted(groups["by_family"].items())
    ]
    ratio_rows = [
        {"ratio": key[0], **aggregate.metrics()}
        for key, aggregate in sorted(groups["by_ratio"].items())
    ]
    http_rows = [
        {"http_method": key[0], **aggregate.metrics()}
        for key, aggregate in sorted(groups["by_http_method"].items())
    ]
    run_rows = [
        {
            "model": key[0],
            "family": key[1],
            "scenario": key[2],
            "ratio": key[3],
            **aggregate.metrics(),
        }
        for key, aggregate in groups["by_run"].items()
    ]
    weakest = sorted(run_rows, key=lambda row: (row["blocked_rate"], row["model"]))[:10]
    strongest = sorted(
        run_rows,
        key=lambda row: (-float(row["blocked_rate"]), str(row["model"])),
    )[:10]

    analysis: dict[str, object] = {
        "schema_version": 1,
        "scope": "result/final/**/generated_payloads.csv only",
        "waf_image": waf_image,
        "source_csv_count": len(ranges),
        "input_payload_count": expected_payload_rows,
        "probe_count": row_count,
        "results_csv_sha256": sha256_file(results_csv),
        "source_manifest_sha256": sha256_file(source_manifest),
        "campaign_summary_sha256": sha256_file(campaign_summary),
        "overall": overall.metrics(),
        "empty_payloads": empty_payload.metrics(),
        "by_model": model_rows,
        "by_family": family_rows,
        "by_ratio": ratio_rows,
        "by_http_method": http_rows,
        "weakest_runs_by_block_rate": weakest,
        "strongest_runs_by_block_rate": strongest,
        "outputs": outputs,
    }
    analysis_path = out_dir / "waf_analysis.json"
    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    overall_metrics = overall.metrics()
    report_lines = [
        "# Final/full WAF evaluation",
        "",
        "## Scope",
        "",
        "- Input selection: only `result/final/**/generated_payloads.csv`.",
        f"- Source CSV files: {len(ranges)}.",
        f"- Generated payload rows: {expected_payload_rows:,}; duplicates and empty rows preserved.",
        f"- HTTP probes: {row_count:,} (`GET` and `POST` for every row).",
        f"- WAF image: `{waf_image}`.",
        "- Rule engine and blocking were enabled at CRS paranoia level 1; verbose container audit logging was disabled.",
        "",
        "## Overall",
        "",
        f"- Blocked: {int(overall_metrics['blocked']):,} "
        f"({float(overall_metrics['blocked_rate']):.2%}).",
        f"- Bypassed with HTTP 200: {int(overall_metrics['bypassed']):,} "
        f"({float(overall_metrics['bypass_rate']):.2%}).",
        f"- Network errors: {int(overall_metrics['network_errors']):,}.",
        f"- Latency: mean {float(overall_metrics['latency_mean_ms']):.3f} ms, "
        f"median {float(overall_metrics['latency_median_ms']):.3f} ms, "
        f"p95 {float(overall_metrics['latency_p95_ms']):.3f} ms.",
        "",
        "An HTTP 200 row is a WAF bypass candidate, not proof that the payload",
        "successfully exploited a database. The backend is an inert local echo service.",
        "",
        "## By model",
        "",
        *markdown_table(model_rows, "model"),
        "",
        "## By family",
        "",
        *markdown_table(family_rows, "family"),
        "",
        "## By ratio",
        "",
        *markdown_table(ratio_rows, "ratio"),
        "",
        "## By HTTP method",
        "",
        *markdown_table(http_rows, "http_method"),
        "",
        "## Ten lowest blocking runs",
        "",
        "| Model | Family | Scenario | Ratio | Block rate |",
        "|---|---|---|---|---:|",
    ]
    for row in weakest:
        report_lines.append(
            f"| {row['model']} | {row['family']} | {row['scenario']} | "
            f"{row['ratio']} | {float(row['blocked_rate']):.2%} |"
        )
    report_lines.extend(
        [
            "",
            "## Artifacts",
            "",
        "- `waf_probe_results.csv`: one row per HTTP probe.",
        "- `waf_summary.json`: campaign-level status and latency.",
        "- `waf_analysis.json`: machine-readable analysis.",
        "- `waf_breakdown_by_run.csv`: 96 Final runs, GET and POST combined.",
        "- `waf_breakdown_by_run_http.csv`: 96 Final runs split by GET/POST.",
        f"- Probe result SHA-256: `{analysis['results_csv_sha256']}`.",
        "",
        ]
    )
    report_path = out_dir / "WAF_FINAL_FULL_REPORT.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    analysis["analysis_path"] = str(analysis_path)
    analysis["report_path"] = str(report_path)
    return analysis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--campaign-summary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--waf-image", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    analysis = summarize(
        results_csv=args.results,
        source_manifest=args.source_manifest,
        campaign_summary=args.campaign_summary,
        out_dir=args.out_dir,
        waf_image=args.waf_image,
    )
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
