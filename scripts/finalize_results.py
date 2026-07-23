from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


METHODS = ("smote", "gan", "ctgan", "seqgan_master", "seqgan_improved")
SQL_FIELDS = ("sql_parse_rate", "sql_structure_rate", "family_motif_coverage", "family_motif_hit_rate", "garbage_rate")
NOVELTY_FIELDS = (
    "exact_input_overlap", "normalized_input_overlap", "holdout_overlap", "normalized_holdout_overlap",
    "mean_nearest_similarity", "median_nearest_similarity", "p90_nearest_similarity",
    "nearest_char3_jaccard_mean", "nearest_token_jaccard_mean", "nearest_edit_similarity_mean", "nearest_feature_cosine_mean",
)
DIVERSITY_FIELDS = (
    "n_generated", "unique_rate", "self_bleu", "distinct_1", "distinct_2", "distinct_3",
    "dominant_payload_share", "lexical_diversity", "character_diversity", "token_diversity",
    "keyword_diversity", "operator_diversity", "function_diversity", "comment_style_diversity", "length_zone_diversity",
    "unique_nearest_payload_rate", "dominant_retrieved_payload_share", "nearest_input_distance_mean", "nearest_input_distance_median", "nearest_input_distance_p90",
)
RF_FIELDS = (
    "macro_f1", "attack_precision", "attack_recall", "attack_f1", "balanced_accuracy", "pr_auc",
    "delta_macro_f1", "delta_attack_recall", "delta_attack_f1", "delta_balanced_accuracy", "delta_pr_auc",
)
STABILITY_FIELDS = (
    "stop_reason", "collapse_rate", "generator_loss", "discriminator_loss", "reward_mean", "reward_variance",
    "gradient_norm", "training_time_seconds",
)


class FinalizeError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FinalizeError(f"Missing result: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FinalizeError(f"Expected JSON object: {path}")
    return data


def discover_run(run_dir: Path, method: str, family: str, scenario: str, ratio: str, variant_id: str = "") -> dict[str, object]:
    quality = read_json(run_dir / "quality_metrics.json")
    rf = read_json(run_dir / "rf_metrics.json")
    metadata = read_json(run_dir / "training_metadata.json")
    row: dict[str, object] = {"method": method, "family": family, "scenario": scenario, "ratio": ratio, "variant_id": variant_id, "run_dir": str(run_dir)}
    for field in (*SQL_FIELDS, *NOVELTY_FIELDS, *DIVERSITY_FIELDS):
        row[field] = quality.get(field)
    for field in RF_FIELDS:
        row[field] = rf.get(field)
    adversarial = metadata.get("adversarial_training", {})
    generation = metadata.get("generation", {})
    row["stop_reason"] = metadata.get("stop_reason", adversarial.get("stop_reason"))
    row["collapse_rate"] = generation.get("collapse_rate")
    row["generator_loss"] = adversarial.get("generator_loss_mean")
    row["discriminator_loss"] = adversarial.get("discriminator_loss_mean")
    row["reward_mean"] = adversarial.get("reward_mean")
    row["reward_variance"] = adversarial.get("reward_variance")
    gradients = [value for value in (adversarial.get("generator_gradient_norm_mean"), adversarial.get("discriminator_gradient_norm_mean")) if isinstance(value, (int, float))]
    row["gradient_norm"] = sum(gradients) / len(gradients) if gradients else None
    row["training_time_seconds"] = metadata.get("training_time_seconds", adversarial.get("training_time_seconds"))
    return row


def cells_from_frozen(path: Path) -> tuple[str, list[tuple[str, str]]]:
    manifest = read_json(path)
    ratio = str(manifest["selected_global_ratio"])
    cells = [(str(item["family"]), str(item["scenario"])) for item in manifest["files"]]
    if len(cells) != 8 or len(set(cells)) != 8:
        raise FinalizeError("Frozen manifest must contain eight unique family-scenario cells")
    return ratio, cells


def collect_independent(results_root: Path, frozen_manifest: Path, selected_variant: Path) -> list[dict[str, object]]:
    ratio, cells = cells_from_frozen(frozen_manifest)
    selected = read_json(selected_variant)
    variant_id = str(selected.get("selected_variant", selected.get("variant_id", "")))
    rows: list[dict[str, object]] = []
    for family, scenario in cells:
        for method in METHODS:
            base = results_root / "final" / method / family / scenario / f"R{ratio}"
            run_dir = base / variant_id if method == "seqgan_improved" else base
            rows.append(discover_run(run_dir, method, family, scenario, ratio, variant_id if method == "seqgan_improved" else ""))
    return rows


def collect_reused(results_root: Path, frozen_manifest: Path, selected_variant: Path) -> list[dict[str, object]]:
    ratio, cells = cells_from_frozen(frozen_manifest)
    selected = read_json(selected_variant)
    variant_id = str(selected.get("selected_variant", selected.get("variant_id", "")))
    rows: list[dict[str, object]] = []
    for family, scenario in cells:
        for method in METHODS:
            if method == "seqgan_improved":
                run_dir = results_root / "phase3" / method / family / scenario / f"R{ratio}" / variant_id
            else:
                run_dir = results_root / "phase2b" / method / family / scenario / f"R{ratio}"
            rows.append(discover_run(run_dir, method, family, scenario, ratio, variant_id if method == "seqgan_improved" else ""))
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = ("method", "family", "scenario", "ratio", "variant_id", "run_dir")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(*identity, *fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def finalize(results_root: Path, frozen_manifest: Path, selected_variant: Path, out_dir: Path, reuse: bool) -> list[dict[str, object]]:
    rows = collect_reused(results_root, frozen_manifest, selected_variant) if reuse else collect_independent(results_root, frozen_manifest, selected_variant)
    if len(rows) != 40:
        raise FinalizeError(f"Expected 40 final rows, found {len(rows)}")
    write_csv(out_dir / "sql_structural_quality.csv", rows, SQL_FIELDS)
    write_csv(out_dir / "novelty_overlap.csv", rows, NOVELTY_FIELDS)
    write_csv(out_dir / "diversity_collapse.csv", rows, DIVERSITY_FIELDS)
    write_csv(out_dir / "rf_utility.csv", rows, RF_FIELDS)
    write_csv(out_dir / "training_stability.csv", rows, STABILITY_FIELDS)
    write_csv(out_dir / "final_comparison.csv", rows, (*SQL_FIELDS, *NOVELTY_FIELDS, *DIVERSITY_FIELDS, *RF_FIELDS, *STABILITY_FIELDS))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--frozen-manifest", type=Path, default=Path("data/prepared/frozen/dataset_manifest.json"))
    parser.add_argument("--selected-variant", type=Path, default=Path("results/phase3/selected_seqgan_variant.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("results/final"))
    parser.add_argument("--reuse", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows = finalize(args.results_root, args.frozen_manifest, args.selected_variant, args.out_dir, args.reuse)
        print(f"Wrote final comparison for {len(rows)} runs to {args.out_dir}")
        return 0
    except (FinalizeError, OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
