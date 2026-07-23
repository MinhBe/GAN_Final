from __future__ import annotations

import csv
import json
from pathlib import Path


class EpochLogger:
    COLUMNS = [
        "run_id",
        "method",
        "phase",
        "family",
        "scenario",
        "ratio",
        "variant_id",
        "seed",
        "tokenizer_mode",
        "sequence_length",
        "g_pretrain_epochs",
        "generator_reward_mode",
        "reward_alpha",
        "epoch",
        "generator_loss",
        "discriminator_loss",
        "discriminator_reward_mean",
        "sql_structure_reward_mean",
        "reward_mean",
        "reward_variance",
        "generator_gradient_norm",
        "discriminator_gradient_norm",
        "unique_rate",
        "collapse_rate",
        "dominant_payload_share",
        "garbage_rate",
        "wellformed_rate",
        "sql_structure_rate",
        "nearest_train_ngram_overlap",
        "nearest_holdout_ngram_overlap",
        "epoch_time_seconds",
        "snapshot_samples_json",
        "stop_reason",
    ]

    def __init__(
        self,
        out_dir: Path,
        run_id: str,
        method: str,
        phase: str,
        family: str,
        scenario: str,
        ratio: str,
        variant_id: str,
        seed: int,
        tokenizer_mode: str,
        sequence_length: int,
        g_pretrain_epochs: int,
        generator_reward_mode: str,
        reward_alpha: float,
    ) -> None:
        self.path = Path(out_dir) / "epoch_metrics.csv"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.context = {
            "run_id": run_id,
            "method": method,
            "phase": phase,
            "family": family,
            "scenario": scenario,
            "ratio": ratio,
            "variant_id": variant_id,
            "seed": seed,
            "tokenizer_mode": tokenizer_mode,
            "sequence_length": sequence_length,
            "g_pretrain_epochs": g_pretrain_epochs,
            "generator_reward_mode": generator_reward_mode,
            "reward_alpha": reward_alpha,
        }
        is_new = not self.path.exists()
        self._handle = self.path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=self.COLUMNS)
        if is_new:
            self._writer.writeheader()
            self._handle.flush()

    def log(
        self,
        epoch: int,
        generator_loss: float,
        discriminator_loss: float,
        discriminator_reward_mean: float,
        sql_structure_reward_mean: float,
        reward_mean: float,
        reward_variance: float,
        generator_gradient_norm: float,
        discriminator_gradient_norm: float,
        unique_rate: float,
        dominant_payload_share: float,
        tier_rates: dict[str, float],
        nearest_train_ngram_overlap: float,
        nearest_holdout_ngram_overlap: float,
        epoch_time_seconds: float,
        snapshot_samples: list[str],
        stop_reason: str = "",
    ) -> None:
        row = dict(self.context)
        row.update(
            {
                "epoch": epoch,
                "generator_loss": generator_loss,
                "discriminator_loss": discriminator_loss,
                "discriminator_reward_mean": discriminator_reward_mean,
                "sql_structure_reward_mean": sql_structure_reward_mean,
                "reward_mean": reward_mean,
                "reward_variance": reward_variance,
                "generator_gradient_norm": generator_gradient_norm,
                "discriminator_gradient_norm": discriminator_gradient_norm,
                "unique_rate": unique_rate,
                "collapse_rate": 1.0 - unique_rate,
                "dominant_payload_share": dominant_payload_share,
                "garbage_rate": tier_rates.get("garbage", 0.0),
                "wellformed_rate": tier_rates.get("wellformed", 0.0),
                "sql_structure_rate": tier_rates.get("injection_shaped", 0.0),
                "nearest_train_ngram_overlap": nearest_train_ngram_overlap,
                "nearest_holdout_ngram_overlap": nearest_holdout_ngram_overlap,
                "epoch_time_seconds": epoch_time_seconds,
                "snapshot_samples_json": json.dumps(snapshot_samples, ensure_ascii=False),
                "stop_reason": stop_reason,
            }
        )
        self._writer.writerow(row)
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
