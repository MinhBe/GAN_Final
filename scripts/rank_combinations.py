from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence

FAMILIES = ("boolean", "union", "time", "error")
SCENARIOS = ("A", "B", "C", "D", "E", "F")
BASE_METHODS = ("smote", "gan", "ctgan", "seqgan_master")
RETRIEVAL_METHODS = frozenset({"smote", "gan", "ctgan"})

SQL_METRICS = (
    ("sql_parse_rate", True),
    ("sql_structure_rate", True),
    ("family_motif_coverage", True),
    ("garbage_rate", False),
)
NOVELTY_METRICS = (
    ("exact_input_overlap", False),
    ("normalized_input_overlap", False),
    ("holdout_overlap", False),
    ("mean_nearest_similarity", False),
)
DIVERSITY_METRICS = (
    ("unique_rate", True),
    ("self_bleu", False),
    ("distinct_1", True),
    ("distinct_2", True),
    ("distinct_3", True),
    ("dominant_payload_share", False),
    ("lexical_diversity", True),
)
STABILITY_METRICS = (
    ("reward_mean", True),
    ("reward_variance", False),
    ("training_collapse_rate", False),
    ("gradient_norm", False),
    ("training_time", False),
)
RF_METRICS = (
    ("rf_macro_f1", True),
    ("rf_attack_precision", True),
    ("rf_attack_recall", True),
    ("rf_attack_f1", True),
    ("rf_balanced_accuracy", True),
    ("rf_pr_auc", True),
    ("rf_delta_macro_f1", True),
    ("rf_delta_attack_recall", True),
)

DEFAULT_THRESHOLDS = {
    "seed": 88,
    "required_metrics": [
        "n_generated",
        "sql_parse_rate",
        "sql_structure_rate",
        "family_motif_coverage",
        "garbage_rate",
        "exact_input_overlap",
        "normalized_input_overlap",
        "holdout_overlap",
        "mean_nearest_similarity",
        "unique_rate",
        "self_bleu",
        "distinct_1",
        "distinct_2",
        "distinct_3",
        "dominant_payload_share",
        "lexical_diversity",
    ],
    "common": {
        "min_generated_count": 1,
        "min_generated_count_fraction": 1.0,
        "min_sql_parse_rate": 0.0,
        "min_sql_structure_rate": 0.0,
        "min_family_motif_coverage": 0.0,
        "max_garbage_rate": 1.0,
        "min_nearest_similarity": 0.0,
        "require_train_reference": False,
        "require_holdout_reference": False,
    },
    "direct": {
        "min_unique_rate": 0.0,
        "max_dominant_payload_share": 1.0,
        "max_normalized_input_overlap": 1.0,
    },
    "retrieval": {
        "min_unique_nearest_payload_rate": 0.0,
        "max_dominant_retrieved_payload_share": 1.0,
    },
    "rf": {"max_macro_f1_drop": 0.15, "max_attack_recall_drop": 0.20},
    "severe_stop_reasons": [
        "error",
        "exception",
        "nan_loss",
        "non_finite_loss",
        "empty_output",
        "training_failed",
        "vanishing_reward",
    ],
}


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _deep_merge(base: dict, update: dict) -> dict:
    result = dict(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_thresholds(path: Path | None) -> dict[str, object]:
    if path is None:
        return _deep_merge({}, DEFAULT_THRESHOLDS)
    value = _read_json(path)
    if value is None:
        raise ValueError(f"Cannot read thresholds: {path}")
    return _deep_merge(DEFAULT_THRESHOLDS, value)


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}_{key}" if prefix else str(key)
            result.update(_flatten(child, name))
    else:
        result[prefix] = value
    return result


def _first(data: dict[str, object], names: Sequence[str]) -> object | None:
    flattened = _flatten(data)
    lowered = {key.casefold(): value for key, value in flattened.items()}
    for name in names:
        if name in data:
            return data[name]
        if name.casefold() in lowered:
            return lowered[name.casefold()]
        suffix = f"_{name.casefold()}"
        matches = [value for key, value in lowered.items() if key.endswith(suffix)]
        if matches:
            return matches[0]
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def canonical_method(value: object) -> str:
    name = str(value or "").strip().casefold().replace("-", "_")
    aliases = {
        "vanilla_gan": "gan",
        "seqgan": "seqgan_master",
        "sequence_gan": "seqgan_master",
        "sequence_gan_master": "seqgan_master",
    }
    return aliases.get(name, name)


def canonical_ratio(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text in {"", "none"}:
        return ""
    if text == "full":
        return "full"
    for prefix in ("1:", "1/", "r"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    try:
        return str(int(float(text)))
    except ValueError:
        return text


def _ancestor_identity(path: Path, candidates: Iterable[str]) -> str:
    allowed = {candidate.casefold(): candidate for candidate in candidates}
    for parent in path.parents:
        if parent.name.casefold() in allowed:
            return allowed[parent.name.casefold()]
    return ""


def _load_training_metadata(run_dir: Path) -> dict[str, object]:
    candidates = [run_dir / "training_metadata.json"]
    candidates.extend(sorted(run_dir.glob("*/training_metadata.json")))
    for candidate in candidates:
        value = _read_json(candidate)
        if value is not None:
            return value
    return {}


def _load_epoch_values(run_dir: Path) -> dict[str, object]:
    paths = [run_dir / "epoch_log.csv", *sorted(run_dir.glob("*/epoch_log.csv"))]
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            continue
        if not rows:
            continue
        result: dict[str, object] = {}
        for key in rows[-1]:
            values = [_number(row.get(key)) for row in rows]
            numeric = [value for value in values if value is not None]
            if numeric:
                result[key] = numeric[-1]
                result[f"{key}_mean"] = statistics.fmean(numeric)
                result[f"{key}_variance"] = statistics.pvariance(numeric) if len(numeric) > 1 else 0.0
        return result
    return {}


def _per_class_value(data: dict[str, object], metric: str, target: str = "attack") -> float | None:
    direct = _number(_first(data, (f"attack_{metric}", metric if target == "attack" else f"{target}_{metric}")))
    if direct is not None and metric not in {"recall", "precision", "f1"}:
        return direct
    flattened = _flatten(data)
    target_keys = (target, "1", "true", "malicious", "sqli")
    for key, value in flattened.items():
        lowered = key.casefold()
        if metric in lowered and any(token in lowered.split("_") for token in target_keys):
            parsed = _number(value)
            if parsed is not None:
                return parsed
    if metric == "recall":
        recalls = _first(data, ("per_class_recall",))
        if isinstance(recalls, dict):
            for key, value in recalls.items():
                if str(key).casefold() in target_keys:
                    parsed = _number(value)
                    if parsed is not None:
                        return parsed
            non_normal = [
                _number(value)
                for key, value in recalls.items()
                if str(key).casefold() not in {"normal", "0", "false"}
            ]
            valid = [value for value in non_normal if value is not None]
            if len(valid) == 1:
                return valid[0]
    return direct


def _rf_pair(run_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
    search_roots = [run_dir, run_dir / "rf"]
    for root in search_roots:
        combined = _read_json(root / "rf_metrics.json")
        if combined:
            baseline = combined.get("baseline", combined.get("A_real_to_real"))
            augmented = combined.get("augmented", combined.get("C_augmented_to_real"))
            if isinstance(baseline, dict) and isinstance(augmented, dict):
                return baseline, augmented
    baseline_names = ("baseline_metrics.json", "rf_baseline_summary.json")
    augmented_names = ("augmented_metrics.json", "rf_gan_summary.json")
    baseline = {}
    augmented = {}
    for root in search_roots:
        for name in baseline_names:
            value = _read_json(root / name)
            if value:
                baseline = value
                break
        for name in augmented_names:
            value = _read_json(root / name)
            if value:
                augmented = value
                break
    return baseline, augmented


def _rf_fields(run_dir: Path) -> dict[str, float | None]:
    baseline, augmented = _rf_pair(run_dir)
    macro_aug = _number(_first(augmented, ("macro_f1", "f1_macro", "f1")))
    macro_base = _number(_first(baseline, ("macro_f1", "f1_macro", "f1")))
    recall_aug = _per_class_value(augmented, "recall")
    recall_base = _per_class_value(baseline, "recall")
    return {
        "rf_macro_f1": macro_aug,
        "rf_attack_precision": _per_class_value(augmented, "precision"),
        "rf_attack_recall": recall_aug,
        "rf_attack_f1": _per_class_value(augmented, "f1"),
        "rf_balanced_accuracy": _number(_first(augmented, ("balanced_accuracy",))),
        "rf_pr_auc": _number(_first(augmented, ("pr_auc", "average_precision", "auc_pr"))),
        "rf_delta_macro_f1": macro_aug - macro_base if macro_aug is not None and macro_base is not None else None,
        "rf_delta_attack_recall": recall_aug - recall_base if recall_aug is not None and recall_base is not None else None,
        "rf_baseline_macro_f1": macro_base,
        "rf_baseline_attack_recall": recall_base,
    }


def _training_fields(metadata: dict[str, object], epochs: dict[str, object], quality: dict[str, object]) -> dict[str, object]:
    combined = dict(metadata)
    combined.update(epochs)
    aliases = {
        "generator_loss": ("generator_loss", "g_loss", "gen_loss", "generator_loss_mean"),
        "discriminator_loss": ("discriminator_loss", "d_loss", "disc_loss", "discriminator_loss_mean"),
        "reward_mean": ("reward_mean", "reward_combined_mean", "reward_combined", "parser_reward_raw_mean"),
        "reward_variance": ("reward_variance", "reward_combined_variance", "reward_variance_mean"),
        "gradient_norm": ("gradient_norm", "gradient_norm_mean", "generator_gradient_norm", "grad_norm"),
        "training_time": ("training_time", "training_time_seconds", "elapsed_seconds", "wall_time_seconds"),
        "training_collapse_rate": ("collapse_rate", "model_collapse_rate", "final_collapse_rate"),
    }
    result: dict[str, object] = {}
    for target, names in aliases.items():
        value = _number(_first(combined, names))
        if value is None and target == "training_collapse_rate":
            value = _number(quality.get("model_collapse_rate"))
        result[target] = value
    result["stop_reason"] = _first(combined, ("stop_reason",)) or quality.get("stop_reason") or "n/a"
    return result


def _variant_id(quality: dict[str, object], metadata: dict[str, object], path: Path) -> str:
    for source in (quality, metadata):
        value = _first(source, ("variant", "variant_id", "axis_id", "configuration_id"))
        if value not in {None, ""}:
            return str(value)
    parent = path.parent.name
    if canonical_ratio(parent) != parent.casefold() or parent.casefold() == "full":
        return ""
    return parent


def collect_rows(results_root: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(results_root.rglob("quality_metrics.json")):
        quality = _read_json(path)
        if quality is None:
            continue
        run_dir = path.parent
        metadata = _load_training_metadata(run_dir)
        epochs = _load_epoch_values(run_dir)
        row = dict(quality)
        row["method"] = canonical_method(row.get("method") or _ancestor_identity(path, (*BASE_METHODS, "seqgan", "seqgan_improved")))
        row["family"] = str(row.get("family") or _ancestor_identity(path, FAMILIES)).casefold()
        row["scenario"] = str(row.get("scenario") or _ancestor_identity(path, SCENARIOS)).upper()
        row["ratio"] = canonical_ratio(row.get("ratio") or next((part for part in path.parts if canonical_ratio(part).isdigit() or part.casefold() == "full"), ""))
        row["variant"] = _variant_id(quality, metadata, path)
        row["run_dir"] = str(run_dir)
        row["quality_metrics_path"] = str(path)
        row.update(_training_fields(metadata, epochs, quality))
        row.update(_rf_fields(run_dir))
        rows.append(row)
    return rows


def _finite_metric(row: dict[str, object], key: str) -> float | None:
    return _number(row.get(key))


def validity_gate(
    row: dict[str, object],
    thresholds: dict[str, object],
    include_rf: bool = False,
) -> tuple[bool, list[str]]:
    reasons = []
    expected_seed = int(thresholds.get("seed") or 88)
    actual_seed = _finite_metric(row, "seed")
    if actual_seed is None:
        reasons.append("missing_seed")
    elif int(actual_seed) != expected_seed:
        reasons.append(f"seed_mismatch:{int(actual_seed)}")
    required = list(thresholds.get("required_metrics") or [])
    for key in required:
        if _finite_metric(row, str(key)) is None:
            reasons.append(f"missing_or_nonfinite:{key}")
    if not bool(row.get("schema_valid", True)):
        reasons.append("invalid_output_schema")
    stop_reason = str(row.get("stop_reason") or "").strip().casefold()
    severe = {str(value).casefold() for value in thresholds.get("severe_stop_reasons") or []}
    if stop_reason in severe or any(stop_reason.startswith(f"{value}:") for value in severe):
        reasons.append(f"severe_stop_reason:{stop_reason}")
    common = thresholds.get("common") if isinstance(thresholds.get("common"), dict) else {}
    count = int(_finite_metric(row, "n_generated") or 0)
    if count < int(common.get("min_generated_count", 1)):
        reasons.append("generated_count_below_threshold")
    fraction = _finite_metric(row, "generated_count_fraction")
    if fraction is not None and fraction < float(common.get("min_generated_count_fraction", 1.0)):
        reasons.append("generated_count_fraction_below_threshold")
    comparisons = (
        ("sql_parse_rate", "min_sql_parse_rate", True),
        ("sql_structure_rate", "min_sql_structure_rate", True),
        ("family_motif_coverage", "min_family_motif_coverage", True),
        ("garbage_rate", "max_garbage_rate", False),
        ("mean_nearest_similarity", "min_nearest_similarity", True),
    )
    for metric, threshold_name, minimum in comparisons:
        value = _finite_metric(row, metric)
        threshold = _number(common.get(threshold_name))
        if value is not None and threshold is not None:
            if minimum and value < threshold:
                reasons.append(f"{metric}_below_threshold")
            if not minimum and value > threshold:
                reasons.append(f"{metric}_above_threshold")
    if bool(common.get("require_train_reference")) and int(_finite_metric(row, "train_reference_count") or 0) == 0:
        reasons.append("missing_train_reference")
    if bool(common.get("require_holdout_reference")) and int(_finite_metric(row, "holdout_reference_count") or 0) == 0:
        reasons.append("missing_holdout_reference")
    retrieval = str(row.get("generation_kind") or "") == "retrieval" or canonical_method(row.get("method")) in RETRIEVAL_METHODS
    section_name = "retrieval" if retrieval else "direct"
    section = thresholds.get(section_name) if isinstance(thresholds.get(section_name), dict) else {}
    if retrieval:
        unique_nearest = _finite_metric(row, "unique_nearest_payload_rate")
        dominant_retrieved = _finite_metric(row, "dominant_retrieved_payload_share")
        if unique_nearest is None:
            reasons.append("missing_or_nonfinite:unique_nearest_payload_rate")
        elif unique_nearest < float(section.get("min_unique_nearest_payload_rate", 0.0)):
            reasons.append("unique_nearest_payload_rate_below_threshold")
        if dominant_retrieved is None:
            reasons.append("missing_or_nonfinite:dominant_retrieved_payload_share")
        elif dominant_retrieved > float(section.get("max_dominant_retrieved_payload_share", 1.0)):
            reasons.append("dominant_retrieved_payload_share_above_threshold")
    else:
        unique = _finite_metric(row, "unique_rate")
        dominant = _finite_metric(row, "dominant_payload_share")
        overlap = _finite_metric(row, "normalized_input_overlap")
        if unique is not None and unique < float(section.get("min_unique_rate", 0.0)):
            reasons.append("unique_rate_below_threshold")
        if dominant is not None and dominant > float(section.get("max_dominant_payload_share", 1.0)):
            reasons.append("dominant_payload_share_above_threshold")
        if overlap is not None and overlap > float(section.get("max_normalized_input_overlap", 1.0)):
            reasons.append("normalized_input_overlap_above_threshold")
    if include_rf:
        rf = thresholds.get("rf") if isinstance(thresholds.get("rf"), dict) else {}
        macro_delta = _finite_metric(row, "rf_delta_macro_f1")
        recall_delta = _finite_metric(row, "rf_delta_attack_recall")
        if macro_delta is None:
            reasons.append("missing_rf_delta_macro_f1")
        elif macro_delta < -float(rf.get("max_macro_f1_drop", 0.15)):
            reasons.append("rf_macro_f1_severe_drop")
        if recall_delta is None:
            reasons.append("missing_rf_delta_attack_recall")
        elif recall_delta < -float(rf.get("max_attack_recall_drop", 0.20)):
            reasons.append("rf_attack_recall_severe_drop")
    return not reasons, reasons


def _median_row(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {}
    result = dict(rows[0])
    keys = {key for row in rows for key in row}
    for key in keys:
        values = [_finite_metric(row, key) for row in rows]
        numeric = [value for value in values if value is not None]
        if numeric:
            result[key] = statistics.median(numeric)
    result["replicate_count"] = len(rows)
    return result


def _rank_values(records: Sequence[dict[str, object]], key: str, higher: bool, valid_key: str = "valid") -> dict[str, float]:
    valid = []
    for record in records:
        value = _finite_metric(record, key)
        if bool(record.get(valid_key)) and value is not None:
            valid.append((str(record["id"]), value))
    ordered = sorted(valid, key=lambda item: ((-item[1]) if higher else item[1], item[0]))
    ranks = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average = ((index + 1) + end) / 2.0
        for position in range(index, end):
            ranks[ordered[position][0]] = average
        index = end
    worst = len(records) + 1.0
    return {str(record["id"]): ranks.get(str(record["id"]), worst) for record in records}


def _group_ranks(records: Sequence[dict[str, object]], metrics: Sequence[tuple[str, bool]]) -> dict[str, float]:
    per_record: dict[str, list[float]] = defaultdict(list)
    for key, higher in metrics:
        metric_ranks = _rank_values(records, key, higher)
        for identity, rank in metric_ranks.items():
            per_record[identity].append(rank)
    return {identity: statistics.fmean(values) for identity, values in per_record.items()}


def _final_ranks(records: Sequence[dict[str, object]], score_key: str, valid_key: str = "valid") -> dict[str, float]:
    prepared = []
    for record in records:
        copied = dict(record)
        copied["rank_score"] = record.get(score_key)
        prepared.append(copied)
    return _rank_values(prepared, "rank_score", False, valid_key=valid_key)


def _cell_records(
    rows: Sequence[dict[str, object]],
    family: str,
    method: str,
    scenarios: Sequence[str],
    ratio: str,
    thresholds: dict[str, object],
) -> list[dict[str, object]]:
    records = []
    for scenario in scenarios:
        matches = [
            row
            for row in rows
            if str(row.get("family")) == family
            and canonical_method(row.get("method")) == method
            and str(row.get("scenario")) == scenario
            and canonical_ratio(row.get("ratio")) == ratio
        ]
        aggregate = _median_row(matches)
        gates = [validity_gate(row, thresholds) for row in matches]
        valid = bool(matches) and all(value[0] for value in gates)
        reasons = sorted({reason for _, run_reasons in gates for reason in run_reasons})
        if not matches:
            reasons = ["missing_run"]
        aggregate.update(
            {
                "id": scenario,
                "family": family,
                "method": method,
                "scenario": scenario,
                "ratio": ratio,
                "valid": valid,
                "gate_reasons": ";".join(reasons),
            }
        )
        records.append(aggregate)
    sql = _group_ranks(records, SQL_METRICS)
    novelty = _group_ranks(records, NOVELTY_METRICS)
    diversity = _group_ranks(records, DIVERSITY_METRICS)
    for record in records:
        identity = str(record["id"])
        record["sql_group_rank"] = sql[identity]
        record["novelty_group_rank"] = novelty[identity]
        record["diversity_group_rank"] = diversity[identity]
        record["three_group_rank_mean"] = statistics.fmean((sql[identity], novelty[identity], diversity[identity]))
    method_ranks = _final_ranks(records, "three_group_rank_mean")
    for record in records:
        record["method_scenario_rank"] = method_ranks[str(record["id"])]
    return records


def rank_phase2a(
    rows: Sequence[dict[str, object]],
    thresholds: dict[str, object],
    ratio: str = "20",
    methods: Sequence[str] = BASE_METHODS,
    families: Sequence[str] = FAMILIES,
    scenarios: Sequence[str] = SCENARIOS,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ratio = canonical_ratio(ratio)
    method_details = []
    indexed = {}
    for family in families:
        for method in methods:
            records = _cell_records(rows, family, canonical_method(method), scenarios, ratio, thresholds)
            method_details.extend(records)
            for record in records:
                indexed[(family, canonical_method(method), str(record["scenario"]))] = record
    aggregates = []
    for family in families:
        for scenario in scenarios:
            cells = [indexed[(family, canonical_method(method), scenario)] for method in methods]
            ranks = [float(cell["method_scenario_rank"]) for cell in cells]
            sql = [float(cell["sql_group_rank"]) for cell in cells]
            novelty = [float(cell["novelty_group_rank"]) for cell in cells]
            diversity = [float(cell["diversity_group_rank"]) for cell in cells]
            valid_count = sum(bool(cell["valid"]) for cell in cells)
            aggregates.append(
                {
                    "family": family,
                    "scenario": scenario,
                    "ratio": ratio,
                    "aggregate_rank": sum(ranks),
                    "median_method_rank": statistics.median(ranks),
                    "validity_rank": statistics.median(sql),
                    "novelty_rank": statistics.median(novelty),
                    "diversity_rank": statistics.median(diversity),
                    "valid_method_count": valid_count,
                    "expected_method_count": len(methods),
                    "eligible": valid_count == len(methods),
                    "method_ranks": json.dumps(
                        {canonical_method(method): indexed[(family, canonical_method(method), scenario)]["method_scenario_rank"] for method in methods},
                        sort_keys=True,
                    ),
                    "gate_reasons": ";".join(
                        f"{cell['method']}={cell['gate_reasons']}" for cell in cells if cell["gate_reasons"]
                    ),
                }
            )
    top2 = []
    for family in families:
        eligible = [row for row in aggregates if row["family"] == family and row["eligible"]]
        eligible.sort(key=lambda row: (float(row["aggregate_rank"]), float(row["median_method_rank"]), str(row["scenario"])))
        for rank, row in enumerate(eligible[:2], 1):
            selected = dict(row)
            selected["rank"] = rank
            top2.append(selected)
    details = method_details + aggregates
    return top2, details


def load_cells(path: Path) -> list[tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cells = []
    for row in rows:
        family = str(row.get("family") or "").casefold()
        scenario = str(row.get("scenario") or "").upper()
        if family in FAMILIES and scenario in SCENARIOS and (family, scenario) not in cells:
            cells.append((family, scenario))
    counts = Counter(family for family, _ in cells)
    if len(cells) != 8 or any(counts[family] != 2 for family in FAMILIES):
        raise ValueError("Selection must contain exactly two unique scenarios for each family")
    return cells


def select_global_ratio(
    rows: Sequence[dict[str, object]],
    thresholds: dict[str, object],
    cells: Sequence[tuple[str, str]],
    methods: Sequence[str] = BASE_METHODS,
    ratios: Sequence[str] = ("full", "10", "20", "50", "100", "200", "500"),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    audit = []
    for raw_ratio in ratios:
        ratio = canonical_ratio(raw_ratio)
        valid_runs = 0
        viable_cells = 0
        reasons = []
        for family, scenario in cells:
            cell_valid = True
            for method in methods:
                matches = [
                    row
                    for row in rows
                    if str(row.get("family")) == family
                    and str(row.get("scenario")) == scenario
                    and canonical_method(row.get("method")) == canonical_method(method)
                    and canonical_ratio(row.get("ratio")) == ratio
                ]
                if not matches:
                    cell_valid = False
                    reasons.append(f"{family}:{scenario}:{canonical_method(method)}=missing")
                    continue
                gates = [validity_gate(row, thresholds, include_rf=True) for row in matches]
                run_valid = all(gate[0] for gate in gates)
                valid_runs += int(run_valid)
                if not run_valid:
                    cell_valid = False
                    joined = ",".join(sorted({reason for _, values in gates for reason in values}))
                    reasons.append(f"{family}:{scenario}:{canonical_method(method)}={joined}")
            viable_cells += int(cell_valid)
        expected_runs = len(cells) * len(methods)
        audit.append(
            {
                "ratio": ratio,
                "viable": viable_cells == len(cells) and valid_runs == expected_runs,
                "viable_cells": viable_cells,
                "expected_cells": len(cells),
                "valid_runs": valid_runs,
                "expected_runs": expected_runs,
                "reasons": ";".join(reasons),
            }
        )
    numeric_viable = [row for row in audit if row["viable"] and str(row["ratio"]).isdigit()]
    selected = max(numeric_viable, key=lambda row: int(str(row["ratio"]))) if numeric_viable else next((row for row in audit if row["viable"] and row["ratio"] == "full"), None)
    result = {
        "selected_ratio": selected["ratio"] if selected else None,
        "selected_global_ratio": selected["ratio"] if selected else None,
        "selection_rule": "largest_numeric_ratio_with_all_cells_and_methods_viable",
        "cell_count": len(cells),
        "method_count": len(methods),
        "viable": selected is not None,
    }
    return result, audit


def _phase3_cell_records(
    rows: Sequence[dict[str, object]],
    family: str,
    scenario: str,
    ratio: str,
    variants: Sequence[str],
    thresholds: dict[str, object],
) -> list[dict[str, object]]:
    records = []
    stability_required = tuple(key for key, _ in STABILITY_METRICS) + ("generator_loss", "discriminator_loss")
    rf_required = tuple(key for key, _ in RF_METRICS)
    for variant in variants:
        matches = [
            row
            for row in rows
            if str(row.get("family")) == family
            and str(row.get("scenario")) == scenario
            and canonical_ratio(row.get("ratio")) == ratio
            and str(row.get("variant")) == variant
        ]
        aggregate = _median_row(matches)
        gates = [validity_gate(row, thresholds) for row in matches]
        reasons = sorted({reason for _, values in gates for reason in values})
        if not matches:
            reasons.append("missing_run")
        missing_stability = [key for key in stability_required if _finite_metric(aggregate, key) is None]
        missing_rf = [key for key in rf_required if _finite_metric(aggregate, key) is None]
        reasons.extend(f"missing_stability:{key}" for key in missing_stability)
        reasons.extend(f"missing_rf:{key}" for key in missing_rf)
        valid = bool(matches) and all(gate[0] for gate in gates) and not missing_stability and not missing_rf
        aggregate.update(
            {
                "id": variant,
                "family": family,
                "scenario": scenario,
                "ratio": ratio,
                "variant": variant,
                "valid": valid,
                "gate_reasons": ";".join(sorted(set(reasons))),
            }
        )
        records.append(aggregate)
    groups = {
        "sql_group_rank": SQL_METRICS,
        "novelty_group_rank": NOVELTY_METRICS,
        "diversity_group_rank": DIVERSITY_METRICS,
        "stability_group_rank": STABILITY_METRICS,
        "rf_group_rank": RF_METRICS,
    }
    for target, metrics in groups.items():
        ranks = _group_ranks(records, metrics)
        for record in records:
            record[target] = ranks[str(record["id"])]
    for record in records:
        record["five_group_rank_mean"] = statistics.fmean(float(record[key]) for key in groups)
    overall = _final_ranks(records, "five_group_rank_mean")
    for record in records:
        record["dataset_variant_rank"] = overall[str(record["id"])]
    return records


def rank_phase3(
    rows: Sequence[dict[str, object]],
    thresholds: dict[str, object],
    cells: Sequence[tuple[str, str]],
    ratio: str,
    variants: Sequence[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ratio = canonical_ratio(ratio)
    details = []
    for family, scenario in cells:
        details.extend(_phase3_cell_records(rows, family, scenario, ratio, variants, thresholds))
    aggregates = []
    for variant in variants:
        variant_rows = [row for row in details if row["variant"] == variant]
        valid_count = sum(bool(row["valid"]) for row in variant_rows)
        result = {
            "variant": variant,
            "dataset_count": len(variant_rows),
            "valid_dataset_count": valid_count,
            "expected_dataset_count": len(cells),
            "eligible": valid_count == len(cells),
            "sql_rank": statistics.median(float(row["sql_group_rank"]) for row in variant_rows),
            "novelty_rank": statistics.median(float(row["novelty_group_rank"]) for row in variant_rows),
            "diversity_rank": statistics.median(float(row["diversity_group_rank"]) for row in variant_rows),
            "stability_rank": statistics.median(float(row["stability_group_rank"]) for row in variant_rows),
            "rf_utility_rank": statistics.median(float(row["rf_group_rank"]) for row in variant_rows),
            "median_dataset_rank": statistics.median(float(row["dataset_variant_rank"]) for row in variant_rows),
            "gate_reasons": ";".join(
                f"{row['family']}:{row['scenario']}={row['gate_reasons']}" for row in variant_rows if row["gate_reasons"]
            ),
        }
        result["aggregate_rank"] = statistics.fmean(
            float(result[key])
            for key in ("sql_rank", "novelty_rank", "diversity_rank", "stability_rank", "rf_utility_rank")
        )
        aggregates.append(result)
    aggregates.sort(key=lambda row: (not bool(row["eligible"]), float(row["aggregate_rank"]), str(row["variant"])))
    for rank, row in enumerate([value for value in aggregates if value["eligible"]], 1):
        row["rank"] = rank
    for row in aggregates:
        row.setdefault("rank", "")
    return aggregates, details


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(value) for key, value in row.items()})


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _split_values(values: Sequence[str] | None, fallback: Sequence[str]) -> list[str]:
    if not values:
        return list(fallback)
    result = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result


def cmd_rank_phase2a(args: argparse.Namespace) -> int:
    rows = collect_rows(args.results_root)
    thresholds = load_thresholds(args.thresholds)
    methods = [canonical_method(value) for value in _split_values(args.methods, BASE_METHODS)]
    top2, details = rank_phase2a(rows, thresholds, ratio=args.ratio, methods=methods)
    write_csv(args.out, top2)
    details_out = args.details_out or args.out.with_name(f"{args.out.stem}_details.csv")
    write_csv(details_out, details)
    family_counts = {family: sum(row["family"] == family for row in top2) for family in FAMILIES}
    if not args.allow_incomplete and any(count < 2 for count in family_counts.values()):
        raise SystemExit(f"Phase 2A has fewer than two fully valid scenarios for: {family_counts}")
    print(f"Wrote {len(top2)} selected scenarios to {args.out}")
    return 0


def cmd_select_ratio(args: argparse.Namespace) -> int:
    rows = collect_rows(args.results_root)
    thresholds = load_thresholds(args.thresholds)
    cells = load_cells(args.cells)
    methods = [canonical_method(value) for value in _split_values(args.methods, BASE_METHODS)]
    ratios = _split_values(args.ratios, ("full", "10", "20", "50", "100", "200", "500"))
    selected, audit = select_global_ratio(rows, thresholds, cells, methods=methods, ratios=ratios)
    write_json(args.out, selected)
    audit_out = args.audit_out or args.out.with_name(f"{args.out.stem}_audit.csv")
    write_csv(audit_out, audit)
    if not selected["viable"]:
        raise SystemExit("No ratio passed the viability gate across every selected cell and method")
    print(f"Selected ratio {selected['selected_ratio']}")
    return 0


def cmd_rank_phase3(args: argparse.Namespace) -> int:
    rows = collect_rows(args.results_root)
    thresholds = load_thresholds(args.thresholds)
    cells = load_cells(args.cells)
    variants = _split_values(args.variants, tuple(f"V{index}" for index in range(1, 9)))
    aggregates, details = rank_phase3(rows, thresholds, cells, args.ratio, variants)
    write_csv(args.out, aggregates)
    details_out = args.details_out or args.out.with_name(f"{args.out.stem}_details.csv")
    write_csv(details_out, details)
    eligible = [row for row in aggregates if row["eligible"]]
    if args.selected_out is not None:
        write_json(
            args.selected_out,
            {
                "selected_variant": eligible[0]["variant"] if eligible else None,
                "selected_ratio": canonical_ratio(args.ratio),
                "eligible_variant_count": len(eligible),
            },
        )
    if not args.allow_incomplete and not eligible:
        raise SystemExit("No Phase 3 variant is complete and valid across every dataset")
    print(f"Wrote {len(aggregates)} variant ranks to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rank_combinations.py")
    commands = parser.add_subparsers(dest="command", required=True)

    phase2a = commands.add_parser("rank-phase2a")
    phase2a.add_argument("--results-root", type=Path, required=True)
    phase2a.add_argument("--thresholds", type=Path)
    phase2a.add_argument("--ratio", default="20")
    phase2a.add_argument("--methods", nargs="+")
    phase2a.add_argument("--out", type=Path, required=True)
    phase2a.add_argument("--details-out", type=Path)
    phase2a.add_argument("--allow-incomplete", action="store_true")
    phase2a.set_defaults(func=cmd_rank_phase2a)

    phase2b = commands.add_parser("select-ratio")
    phase2b.add_argument("--results-root", type=Path, required=True)
    phase2b.add_argument("--thresholds", type=Path)
    phase2b.add_argument("--cells", type=Path, required=True)
    phase2b.add_argument("--methods", nargs="+")
    phase2b.add_argument("--ratios", nargs="+")
    phase2b.add_argument("--out", type=Path, required=True)
    phase2b.add_argument("--audit-out", type=Path)
    phase2b.set_defaults(func=cmd_select_ratio)

    phase3 = commands.add_parser("rank-phase3")
    phase3.add_argument("--results-root", type=Path, required=True)
    phase3.add_argument("--thresholds", type=Path)
    phase3.add_argument("--cells", type=Path, required=True)
    phase3.add_argument("--ratio", required=True)
    phase3.add_argument("--variants", nargs="+")
    phase3.add_argument("--out", type=Path, required=True)
    phase3.add_argument("--details-out", type=Path)
    phase3.add_argument("--selected-out", type=Path)
    phase3.add_argument("--allow-incomplete", action="store_true")
    phase3.set_defaults(func=cmd_rank_phase3)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
