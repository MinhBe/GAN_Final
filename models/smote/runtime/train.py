from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

MODEL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODEL_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.dataset_schema import canonical_payload_frame
from models.smote.preprocessing.config import CONFIGS, META_COLS
from models.smote.preprocessing.features import build_features, feature_columns
from models.smote.runtime.smote import _smote_class

FAMILIES = ("boolean", "union", "time", "error")
FAMILY_ORDER = (*FAMILIES, "other")


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _load_attacks(path: Path, family: str) -> pd.DataFrame:
    frame = canonical_payload_frame(path, include_other=family == "all")
    frame = frame.loc[frame["label"].eq("attack")].copy()
    if family != "all":
        frame = frame.loc[frame["payload_type"].eq(family)].copy()
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"No attack rows available for family={family!r}")
    return frame[META_COLS]


def _allocate(frame: pd.DataFrame, n_samples: int, requested_family: str) -> dict[str, int]:
    if requested_family == "all":
        return {"all": n_samples}
    counts = {
        family: int((frame["payload_type"] == family).sum())
        for family in FAMILY_ORDER
        if (frame["payload_type"] == family).any()
    }
    total = sum(counts.values())
    raw = {family: n_samples * count / total for family, count in counts.items()}
    allocated = {family: int(math.floor(value)) for family, value in raw.items()}
    remaining = n_samples - sum(allocated.values())
    order = sorted(counts, key=lambda family: (-(raw[family] - allocated[family]), FAMILY_ORDER.index(family)))
    for family in order[:remaining]:
        allocated[family] += 1
    return {family: count for family, count in allocated.items() if count > 0}


def run(args: argparse.Namespace) -> None:
    base = CONFIGS[args.config]
    n_samples = args.n_samples if args.n_samples is not None else int(base.n_samples)
    k_neighbors = args.k_neighbors if args.k_neighbors is not None else int(base.k_neighbors)
    attacks = _load_attacks(args.dataset, args.family)
    features = build_features(attacks)
    feature_names = feature_columns(features)
    scaler = StandardScaler()
    normalized = scaler.fit_transform(features[feature_names].to_numpy(dtype=float))
    normalized_frame = attacks.copy()
    normalized_frame[feature_names] = normalized
    allocations = _allocate(attacks, n_samples, args.family)
    payload_rows: list[dict[str, object]] = []
    vector_rows: list[dict[str, object]] = []

    for family, family_n in allocations.items():
        mask = np.ones(len(normalized_frame), dtype=bool) if family == "all" else normalized_frame["payload_type"].eq(family).to_numpy()
        pool = attacks.loc[mask].reset_index(drop=True)
        pool_vectors = normalized_frame.loc[mask, feature_names].to_numpy(dtype=float)
        synthetic_normalized = _smote_class(
            pool_vectors,
            family_n,
            k_neighbors=k_neighbors,
            seed=args.seed,
        )
        nearest = NearestNeighbors(n_neighbors=1, metric="euclidean").fit(pool_vectors)
        distances, indices = nearest.kneighbors(synthetic_normalized)
        synthetic_raw = scaler.inverse_transform(synthetic_normalized)

        for synthetic_vector, distance, index in zip(synthetic_raw, distances[:, 0], indices[:, 0]):
            source = pool.iloc[int(index)]
            output_id = f"SMOTE_{len(payload_rows) + 1:06d}"
            metadata = {
                "id": output_id,
                "label": "attack",
                "payload_type": str(source["payload_type"]),
                "payload": str(source["payload"]),
                "retrieval_method": "nearest_attack_euclidean",
                "retrieval_source_id": str(source["id"]),
                "retrieval_distance": float(distance),
            }
            payload_rows.append(metadata)
            vector_rows.append(metadata | {name: float(value) for name, value in zip(feature_names, synthetic_vector)})

    if len(payload_rows) != n_samples:
        raise RuntimeError(f"Expected {n_samples} generated rows, got {len(payload_rows)}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload_frame = pd.DataFrame(payload_rows)
    vector_frame = pd.DataFrame(vector_rows)
    payload_frame.to_csv(args.out_dir / "generated_payloads.csv", index=False)
    vector_frame.to_csv(args.out_dir / "generated_feature_vectors.csv", index=False)
    (args.out_dir / "generated_payloads.txt").write_text(
        "\n".join(payload_frame["payload"].tolist()),
        encoding="utf-8",
    )
    metadata = {
        "method": "smote",
        "dataset": str(args.dataset),
        "family": args.family,
        "seed": args.seed,
        "config": args.config,
        "n_train_attack": int(len(attacks)),
        "n_samples_requested": n_samples,
        "n_samples_generated": int(len(payload_frame)),
        "n_unique_generated_payloads": int(payload_frame["payload"].nunique()),
        "input_family_counts": {str(key): int(value) for key, value in attacks["payload_type"].value_counts().items()},
        "output_family_counts": {str(key): int(value) for key, value in payload_frame["payload_type"].value_counts().items()},
        "k_neighbors": k_neighbors,
        "feature_count": len(feature_names),
        "duplicates_preserved": True,
        "stop_reason": "completed",
    }
    (args.out_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(payload_frame)} SMOTE retrieval rows in {args.out_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", choices=sorted(CONFIGS), default="medium")
    parser.add_argument("--family", choices=("all", *FAMILIES), default="all")
    parser.add_argument("--n-samples", type=_positive, default=None)
    parser.add_argument("--k-neighbors", type=_positive, default=None)
    parser.add_argument("--seed", type=int, default=88)
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
