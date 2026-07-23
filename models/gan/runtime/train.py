from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

MODEL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODEL_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.dataset_schema import canonical_payload_frame
from models.gan.preprocessing.features import make_feature_dataframe
from models.gan.runtime.models import Discriminator, Generator

FAMILIES = ("boolean", "union", "time", "error")
FAMILY_ORDER = (*FAMILIES, "other")


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def _load_attacks(path: Path, family: str) -> pd.DataFrame:
    frame = canonical_payload_frame(path, include_other=family == "all")
    frame = frame.loc[frame["label"].eq("attack")].copy()
    if family != "all":
        frame = frame.loc[frame["payload_type"].eq(family)].copy()
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"No attack rows available for family={family!r}")
    return frame


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


def _train_gan(
    vectors: np.ndarray,
    n_samples: int,
    args: argparse.Namespace,
    device: torch.device,
    seed: int,
) -> tuple[Generator, np.ndarray, dict[str, float]]:
    _seed_everything(seed)
    batch_size = min(args.batch_size, len(vectors))
    loader_generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(
        TensorDataset(torch.tensor(vectors, dtype=torch.float32)),
        batch_size=batch_size,
        shuffle=True,
        drop_last=False,
        generator=loader_generator,
    )
    generator = Generator(args.noise_dim, vectors.shape[1], args.hidden_dim).to(device)
    discriminator = Discriminator(vectors.shape[1], args.hidden_dim).to(device)
    generator_optimizer = torch.optim.Adam(generator.parameters(), lr=args.lr, betas=(0.5, 0.999))
    discriminator_optimizer = torch.optim.Adam(discriminator.parameters(), lr=args.lr, betas=(0.5, 0.999))
    criterion = nn.BCELoss()
    last_generator_loss = 0.0
    last_discriminator_loss = 0.0

    for _ in range(args.epochs):
        for (real,) in loader:
            real = real.to(device)
            size = real.size(0)
            real_labels = torch.ones(size, 1, device=device)
            fake_labels = torch.zeros(size, 1, device=device)
            noise = torch.randn(size, args.noise_dim, device=device)
            fake = generator(noise).detach()
            discriminator_loss = criterion(discriminator(real), real_labels) + criterion(discriminator(fake), fake_labels)
            discriminator_optimizer.zero_grad(set_to_none=True)
            discriminator_loss.backward()
            discriminator_optimizer.step()
            noise = torch.randn(size, args.noise_dim, device=device)
            generator_loss = criterion(discriminator(generator(noise)), real_labels)
            generator_optimizer.zero_grad(set_to_none=True)
            generator_loss.backward()
            generator_optimizer.step()
            last_generator_loss = float(generator_loss.detach().cpu())
            last_discriminator_loss = float(discriminator_loss.detach().cpu())

    generator.eval()
    chunks: list[np.ndarray] = []
    remaining = n_samples
    with torch.no_grad():
        while remaining > 0:
            size = min(512, remaining)
            chunks.append(generator(torch.randn(size, args.noise_dim, device=device)).cpu().numpy())
            remaining -= size
    return generator, np.vstack(chunks), {
        "generator_loss": last_generator_loss,
        "discriminator_loss": last_discriminator_loss,
    }


def run(args: argparse.Namespace) -> None:
    _seed_everything(args.seed)
    attacks = _load_attacks(args.dataset, args.family)
    feature_frame = make_feature_dataframe(attacks["payload"].astype(str).tolist())
    feature_names = feature_frame.columns.tolist()
    scaler = StandardScaler()
    normalized = scaler.fit_transform(feature_frame.to_numpy(dtype=float))
    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    allocations = _allocate(attacks, args.n_samples, args.family)
    payload_rows: list[dict[str, object]] = []
    vector_rows: list[dict[str, object]] = []
    losses: dict[str, dict[str, float]] = {}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for family, family_n in allocations.items():
        mask = np.ones(len(attacks), dtype=bool) if family == "all" else attacks["payload_type"].eq(family).to_numpy()
        pool = attacks.loc[mask].reset_index(drop=True)
        pool_vectors = normalized[mask]
        generator, synthetic_normalized, family_losses = _train_gan(
            pool_vectors,
            family_n,
            args,
            device,
            args.seed,
        )
        torch.save(generator.state_dict(), args.out_dir / f"generator_{family}.pt")
        losses[family] = family_losses
        nearest = NearestNeighbors(n_neighbors=1, metric="euclidean").fit(pool_vectors)
        distances, indices = nearest.kneighbors(synthetic_normalized)
        synthetic_raw = scaler.inverse_transform(synthetic_normalized)

        for synthetic_vector, distance, index in zip(synthetic_raw, distances[:, 0], indices[:, 0]):
            source = pool.iloc[int(index)]
            output_id = f"GAN_{len(payload_rows) + 1:06d}"
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

    if len(payload_rows) != args.n_samples:
        raise RuntimeError(f"Expected {args.n_samples} generated rows, got {len(payload_rows)}")

    payload_frame = pd.DataFrame(payload_rows)
    vector_frame = pd.DataFrame(vector_rows)
    payload_frame.to_csv(args.out_dir / "generated_payloads.csv", index=False)
    vector_frame.to_csv(args.out_dir / "generated_feature_vectors.csv", index=False)
    (args.out_dir / "generated_payloads.txt").write_text(
        "\n".join(payload_frame["payload"].tolist()),
        encoding="utf-8",
    )
    joblib.dump(scaler, args.out_dir / "scaler.joblib")
    metadata = {
        "method": "gan",
        "dataset": str(args.dataset),
        "family": args.family,
        "seed": args.seed,
        "device": str(device),
        "n_train_attack": int(len(attacks)),
        "n_samples_requested": args.n_samples,
        "n_samples_generated": int(len(payload_frame)),
        "n_unique_generated_payloads": int(payload_frame["payload"].nunique()),
        "input_family_counts": {str(key): int(value) for key, value in attacks["payload_type"].value_counts().items()},
        "output_family_counts": {str(key): int(value) for key, value in payload_frame["payload_type"].value_counts().items()},
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "noise_dim": args.noise_dim,
        "hidden_dim": args.hidden_dim,
        "learning_rate": args.lr,
        "feature_count": len(feature_names),
        "final_losses": losses,
        "duplicates_preserved": True,
        "stop_reason": "completed",
    }
    (args.out_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(payload_frame)} GAN retrieval rows in {args.out_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--family", choices=("all", *FAMILIES), default="all")
    parser.add_argument("--n-samples", type=_positive, default=2000)
    parser.add_argument("--epochs", type=_positive, default=100)
    parser.add_argument("--batch-size", type=_positive, default=64)
    parser.add_argument("--noise-dim", type=_positive, default=32)
    parser.add_argument("--hidden-dim", type=_positive, default=128)
    parser.add_argument("--lr", type=float, default=0.0002)
    parser.add_argument("--seed", type=int, default=88)
    parser.add_argument("--cpu", action="store_true")
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
