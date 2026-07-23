from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from torch import optim
from tqdm import tqdm

torch.set_num_threads(1)

MODEL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODEL_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from common.dataset_schema import canonical_payload_frame
from models.ctgan.preprocessing.config import CONFIGS
from models.ctgan.preprocessing.features import FEATURE_COLUMNS, feature_frame
from models.ctgan.preprocessing.transformer import CTGANTransformer
from models.ctgan.runtime.models import CTGANCritic, CTGANGenerator, conditional_loss, gradient_penalty
from models.ctgan.runtime.sampler import ConditionalSampler

FAMILIES = ("boolean", "union", "time", "error")
INTEGER_COLUMNS = {
    column
    for column in FEATURE_COLUMNS
    if column.startswith("num_") or column.startswith("has_")
    or column in {"length", "token_count", "max_token_len", "sql_keyword_count"}
}


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


def _round_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in INTEGER_COLUMNS:
        if column in result.columns:
            result[column] = np.clip(np.rint(result[column].astype(float)), 0, None).astype(int)
    for column in {"ratio_digits", "ratio_spaces", "ratio_special", "entropy", "avg_token_len"}:
        if column in result.columns:
            result[column] = np.clip(result[column].astype(float), 0, None)
    return result


def _load_attacks(path: Path, family: str) -> pd.DataFrame:
    frame = canonical_payload_frame(path, include_other=family == "all")
    frame = frame.loc[frame["label"].eq("attack")].copy()
    if family != "all":
        frame = frame.loc[frame["payload_type"].eq(family)].copy()
    frame = frame.reset_index(drop=True)
    if frame.empty:
        raise ValueError(f"No attack rows available for family={family!r}")
    return frame


def _retrieve_payloads(
    attacks: pd.DataFrame,
    attack_features: pd.DataFrame,
    generated_features: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    payload_rows: list[dict[str, object]] = []
    vector_frame = generated_features.copy()
    vector_frame["retrieval_source_id"] = ""
    vector_frame["retrieval_distance"] = np.nan
    for payload_type in vector_frame["payload_type"].astype(str).unique():
        source_mask = attacks["payload_type"].astype(str).eq(payload_type).to_numpy()
        generated_mask = vector_frame["payload_type"].astype(str).eq(payload_type).to_numpy()
        source_pool = attacks.loc[source_mask].reset_index(drop=True)
        if source_pool.empty:
            raise RuntimeError(f"No retrieval source rows for payload_type={payload_type!r}")
        source_vectors = attack_features.loc[source_mask, FEATURE_COLUMNS].to_numpy(dtype=float)
        query_vectors = vector_frame.loc[generated_mask, FEATURE_COLUMNS].to_numpy(dtype=float)
        scaler = StandardScaler()
        source_scaled = scaler.fit_transform(source_vectors)
        query_scaled = scaler.transform(query_vectors)
        nearest = NearestNeighbors(n_neighbors=1, metric="euclidean").fit(source_scaled)
        distances, indices = nearest.kneighbors(query_scaled)
        generated_indices = vector_frame.index[generated_mask]
        for generated_index, distance, source_index in zip(generated_indices, distances[:, 0], indices[:, 0]):
            source = source_pool.iloc[int(source_index)]
            output_id = str(vector_frame.at[generated_index, "id"])
            source_id = str(source["id"])
            vector_frame.at[generated_index, "retrieval_source_id"] = source_id
            vector_frame.at[generated_index, "retrieval_distance"] = float(distance)
            payload_rows.append(
                {
                    "id": output_id,
                    "label": "attack",
                    "payload_type": str(source["payload_type"]),
                    "payload": str(source["payload"]),
                    "retrieval_method": "nearest_attack_euclidean",
                    "retrieval_source_id": source_id,
                    "retrieval_distance": float(distance),
                }
            )
    payload_frame = pd.DataFrame(payload_rows).sort_values("id").reset_index(drop=True)
    vector_frame = vector_frame.sort_values("id").reset_index(drop=True)
    return payload_frame, vector_frame


def run_training(args: argparse.Namespace) -> None:
    base = CONFIGS[args.config]

    def setting(name: str):
        value = getattr(args, name, None)
        return getattr(base, name) if value is None else value

    epochs = int(setting("epochs"))
    batch_size = int(setting("batch_size"))
    z_dim = int(setting("z_dim"))
    hidden_dim = int(setting("hidden_dim"))
    pac = int(setting("pac"))
    critic_steps = int(setting("critic_steps"))
    lambda_gp = float(setting("lambda_gp"))
    cond_loss_weight = float(setting("cond_loss_weight"))
    learning_rate = float(setting("lr"))
    tau = float(setting("tau"))
    dropout = float(setting("dropout"))
    max_modes = int(setting("max_modes"))
    n_samples = int(setting("n_samples"))
    seed = int(args.seed)
    if batch_size % pac != 0:
        batch_size = pac * max(1, batch_size // pac)

    _seed_everything(seed)
    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    attacks = _load_attacks(args.dataset, args.family)
    features = feature_frame(attacks["payload"].astype(str).tolist())
    train_frame = pd.concat(
        [attacks[["label", "payload_type"]].reset_index(drop=True), features],
        axis=1,
    )
    transformer = CTGANTransformer(
        continuous_cols=FEATURE_COLUMNS,
        discrete_cols=["label", "payload_type"],
        max_modes=max_modes,
        random_state=seed,
    )
    transformer.fit(train_frame)
    transformed = torch.tensor(
        transformer.transform(train_frame, sample_modes=True),
        dtype=torch.float32,
        device=device,
    )
    sampler = ConditionalSampler(
        train_frame[["label", "payload_type"]].copy(),
        transformer,
        seed=seed,
    )
    generator = CTGANGenerator(
        z_dim,
        transformer.cond_dim,
        transformer,
        hidden_dim=hidden_dim,
        tau=tau,
    ).to(device)
    critic = CTGANCritic(
        transformer.output_dim,
        transformer.cond_dim,
        hidden_dim=hidden_dim,
        pac=pac,
        dropout=dropout,
    ).to(device)
    generator_optimizer = optim.Adam(generator.parameters(), lr=learning_rate, betas=(0.5, 0.9))
    critic_optimizer = optim.Adam(critic.parameters(), lr=learning_rate, betas=(0.5, 0.9))
    history: list[dict[str, float | int]] = []
    steps_per_epoch = max(1, math.ceil(len(train_frame) / batch_size))

    for epoch in tqdm(range(epochs), desc="CTGAN"):
        critic_losses: list[float] = []
        generator_losses: list[float] = []
        for _ in range(steps_per_epoch):
            for _ in range(critic_steps):
                condition_array, real_indices, _, _ = sampler.sample_train(batch_size)
                condition = torch.tensor(condition_array, dtype=torch.float32, device=device)
                real = transformed[torch.tensor(real_indices, dtype=torch.long, device=device)]
                noise = torch.randn(batch_size, z_dim, device=device)
                with torch.no_grad():
                    fake = generator(noise, condition)
                critic_loss = (
                    critic(fake, condition).mean()
                    - critic(real, condition).mean()
                    + gradient_penalty(critic, real, fake, condition, lambda_gp)
                )
                critic_optimizer.zero_grad(set_to_none=True)
                critic_loss.backward()
                critic_optimizer.step()
                critic_losses.append(float(critic_loss.detach().cpu()))

            condition_array, _, selected_columns, local_categories = sampler.sample_train(batch_size)
            condition = torch.tensor(condition_array, dtype=torch.float32, device=device)
            noise = torch.randn(batch_size, z_dim, device=device)
            fake = generator(noise, condition)
            generator_loss = -critic(fake, condition).mean() + cond_loss_weight * conditional_loss(
                fake,
                transformer,
                torch.tensor(selected_columns, dtype=torch.long, device=device),
                torch.tensor(local_categories, dtype=torch.long, device=device),
            )
            generator_optimizer.zero_grad(set_to_none=True)
            generator_loss.backward()
            generator_optimizer.step()
            generator_losses.append(float(generator_loss.detach().cpu()))

        history.append(
            {
                "epoch": epoch + 1,
                "critic_loss": float(np.mean(critic_losses)),
                "generator_loss": float(np.mean(generator_losses)),
            }
        )

    generator.eval()
    feature_chunks: list[pd.DataFrame] = []
    payload_types: list[str] = []
    remaining = n_samples
    target_family = None if args.family == "all" else args.family

    with torch.no_grad():
        while remaining > 0:
            rounded_size = ((remaining + pac - 1) // pac) * pac
            size = min(batch_size, rounded_size)
            condition_array, _, sampled_types = sampler.sample_generation(
                size,
                target_label="attack",
                target_payload_type=target_family,
            )
            condition = torch.tensor(condition_array, dtype=torch.float32, device=device)
            generated = generator(torch.randn(size, z_dim, device=device), condition).cpu().numpy()
            inverse = transformer.inverse_transform(generated)
            feature_chunks.append(inverse[FEATURE_COLUMNS])
            payload_types.extend(sampled_types)
            remaining -= size

    generated_features = pd.concat(feature_chunks, ignore_index=True).iloc[:n_samples].copy()
    generated_features = _round_features(generated_features)
    payload_types = payload_types[:n_samples]
    generated_features.insert(0, "payload_type", payload_types)
    generated_features.insert(0, "label", "attack")
    generated_features.insert(0, "id", [f"CTGAN_{index + 1:06d}" for index in range(n_samples)])
    generated_payloads, generated_features = _retrieve_payloads(attacks, features, generated_features)

    if len(generated_payloads) != n_samples:
        raise RuntimeError(f"Expected {n_samples} generated rows, got {len(generated_payloads)}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    generated_features.to_csv(args.out_dir / "generated_feature_vectors.csv", index=False)
    generated_payloads.to_csv(args.out_dir / "generated_payloads.csv", index=False)
    (args.out_dir / "generated_payloads.txt").write_text(
        "\n".join(generated_payloads["payload"].tolist()),
        encoding="utf-8",
    )
    pd.DataFrame(history).to_csv(args.out_dir / "training_history.csv", index=False)
    torch.save(generator.state_dict(), args.out_dir / "generator.pt")
    torch.save(critic.state_dict(), args.out_dir / "critic.pt")
    metadata = {
        "method": "ctgan",
        "dataset": str(args.dataset),
        "family": args.family,
        "seed": seed,
        "config": args.config,
        "device": str(device),
        "n_train_attack": int(len(attacks)),
        "n_samples_requested": n_samples,
        "n_samples_generated": int(len(generated_payloads)),
        "n_unique_generated_payloads": int(generated_payloads["payload"].nunique()),
        "input_family_counts": {str(key): int(value) for key, value in attacks["payload_type"].value_counts().items()},
        "output_family_counts": {str(key): int(value) for key, value in generated_payloads["payload_type"].value_counts().items()},
        "epochs": epochs,
        "batch_size": batch_size,
        "z_dim": z_dim,
        "hidden_dim": hidden_dim,
        "pac": pac,
        "critic_steps": critic_steps,
        "output_dim": transformer.output_dim,
        "condition_dim": transformer.cond_dim,
        "retrieval_method": "nearest_attack_euclidean",
        "duplicates_preserved": True,
        "stop_reason": "completed",
    }
    (args.out_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(generated_payloads)} CTGAN rows in {args.out_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", choices=sorted(CONFIGS), default="medium")
    parser.add_argument("--family", choices=("all", *FAMILIES), default="all")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--seed", type=int, default=88)
    integer_settings = (
        "epochs",
        "batch_size",
        "z_dim",
        "hidden_dim",
        "pac",
        "critic_steps",
        "n_samples",
        "max_modes",
    )
    float_settings = ("lambda_gp", "cond_loss_weight", "lr", "tau", "dropout")
    for name in integer_settings:
        parser.add_argument(f"--{name.replace('_', '-')}", type=_positive, default=None)
    for name in float_settings:
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=None)
    return parser


def main() -> None:
    run_training(build_parser().parse_args())


if __name__ == "__main__":
    main()
