from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from common.dataset_schema import canonical_payload_frame, normalize_label
from models.seqgan_improved.preprocessing.features import make_feature_dataframe


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _role_payloads(path: Path, expected_label: str) -> list[str]:
    frame = canonical_payload_frame(path, include_other=True)
    labels = set(frame["label"].astype(str))
    if labels != {expected_label}:
        raise ValueError(f"{path} must contain only {expected_label!r} rows, got {sorted(labels)}")
    payloads = frame["payload"].astype(str).tolist()
    if not payloads:
        raise ValueError(f"{path} contains no payloads")
    return payloads


def _generated_payloads(path: Path) -> list[str]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "payload" not in frame.columns:
        raise ValueError(f"{path} must contain a payload column")
    if "label" in frame.columns:
        labels = {normalize_label(value) for value in frame["label"]}
        if labels and labels != {"attack"}:
            raise ValueError(f"{path} must contain only attack rows, got {sorted(labels)}")
    payloads = frame.loc[frame["payload"].str.strip().ne(""), "payload"].tolist()
    if not payloads:
        raise ValueError(f"{path} contains no generated payloads")
    return payloads


def _fit(
    train_features: pd.DataFrame,
    train_labels: np.ndarray,
    seed: int,
    n_estimators: int,
) -> RandomForestClassifier:
    model = RandomForestClassifier(
        n_estimators=n_estimators,
        random_state=seed,
        n_jobs=-1,
        class_weight="balanced_subsample",
    )
    model.fit(train_features, train_labels)
    return model


def _metrics(
    model: RandomForestClassifier,
    test_features: pd.DataFrame,
    test_labels: np.ndarray,
) -> dict[str, float]:
    predictions = model.predict(test_features)
    attack_index = list(model.classes_).index(1)
    attack_scores = model.predict_proba(test_features)[:, attack_index]
    return {
        "macro_f1": float(f1_score(test_labels, predictions, average="macro", zero_division=0)),
        "attack_precision": float(precision_score(test_labels, predictions, pos_label=1, zero_division=0)),
        "attack_recall": float(recall_score(test_labels, predictions, pos_label=1, zero_division=0)),
        "attack_f1": float(f1_score(test_labels, predictions, pos_label=1, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(test_labels, predictions)),
        "pr_auc": float(average_precision_score(test_labels, attack_scores)),
    }


def evaluate(args: argparse.Namespace) -> dict[str, object]:
    normal_train = _role_payloads(args.normal_train, "normal")
    normal_test = _role_payloads(args.normal_test, "normal")
    attack_train = _role_payloads(args.attack_train, "attack")
    attack_holdout = _role_payloads(args.attack_holdout, "attack")
    generated = _generated_payloads(args.generated)
    baseline_payloads = [*normal_train, *attack_train]
    baseline_labels = np.array([0] * len(normal_train) + [1] * len(attack_train), dtype=int)
    test_payloads = [*normal_test, *attack_holdout]
    test_labels = np.array([0] * len(normal_test) + [1] * len(attack_holdout), dtype=int)
    generated_labels = np.ones(len(generated), dtype=int)
    baseline_features = make_feature_dataframe(baseline_payloads)
    test_features = make_feature_dataframe(test_payloads)
    generated_features = make_feature_dataframe(generated)
    baseline_model = _fit(baseline_features, baseline_labels, args.seed, args.n_estimators)
    baseline_metrics = _metrics(baseline_model, test_features, test_labels)
    augmented_features = pd.concat([baseline_features, generated_features], ignore_index=True)
    augmented_labels = np.concatenate([baseline_labels, generated_labels])
    augmented_model = _fit(augmented_features, augmented_labels, args.seed, args.n_estimators)
    augmented_metrics = _metrics(augmented_model, test_features, test_labels)
    deltas = {
        key: float(augmented_metrics[key] - baseline_metrics[key])
        for key in augmented_metrics
    }
    result: dict[str, object] = {
        "seed": args.seed,
        "n_estimators": args.n_estimators,
        "counts": {
            "normal_train": len(normal_train),
            "normal_test": len(normal_test),
            "attack_train": len(attack_train),
            "attack_holdout": len(attack_holdout),
            "generated_attack": len(generated),
        },
        "baseline": baseline_metrics,
        "augmented": augmented_metrics,
        "deltas": deltas,
        **augmented_metrics,
        **{f"delta_{key}": value for key, value in deltas.items()},
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-train", type=Path, required=True)
    parser.add_argument("--normal-test", type=Path, required=True)
    parser.add_argument("--attack-train", type=Path, required=True)
    parser.add_argument("--attack-holdout", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=88)
    parser.add_argument("--n-estimators", type=_positive, default=300)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = evaluate(args)
    output = args.out if args.out.suffix.lower() == ".json" else args.out / "rf_metrics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote fixed-holdout RF metrics to {output}")


if __name__ == "__main__":
    main()
