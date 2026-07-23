from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from pathlib import Path as _Path
from time import perf_counter

import torch
import torch.optim as optim
from torch.utils.data import DataLoader

_MODEL_ROOT = _Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODEL_ROOT / "runtime"))
sys.path.insert(0, str(_MODEL_ROOT / "preprocessing"))
sys.path.insert(0, str(_MODEL_ROOT.parent.parent / "export" / "payload_export"))

from discriminator import Disc
from epoch_logger import EpochLogger
from generator import Gen
from holdout import ngram_overlap
from pretrain import train_disc
from rollout import Rollout
from seqgan_sql_validity import batch_parser_reward, batch_pass_rate
from tokenizer import RawCharacterTokenizer

EARLY_STOP_THRESHOLD = 0.05
EARLY_STOP_PATIENCE = 3
SNAPSHOT_N = 50


def combine_generator_rewards(
    discriminator_reward: torch.Tensor,
    sql_structure_reward: torch.Tensor,
    mode: str,
    reward_alpha: float,
) -> torch.Tensor:
    if mode not in {"off", "on"}:
        raise ValueError("generator reward mode must be 'off' or 'on'")
    if not 0.0 <= float(reward_alpha) <= 1.0:
        raise ValueError("reward_alpha must be in [0, 1]")
    if mode == "off":
        return discriminator_reward
    return float(reward_alpha) * discriminator_reward + (1.0 - float(reward_alpha)) * sql_structure_reward


def _as_path(value) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return Path(value)


def _checkpoint_candidates(*directories) -> list[Path]:
    output: list[Path] = []
    for directory in directories:
        path = _as_path(directory)
        if not path or not path.exists():
            continue
        latest = path / "latest_adversarial.pt"
        if latest.exists():
            output.append(latest)
        output.extend(sorted(path.glob("adversarial_epoch_*.pt"), key=lambda item: item.stat().st_mtime, reverse=True))
    seen: set[str] = set()
    result: list[Path] = []
    for path in output:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            result.append(path)
    return result


def _save_checkpoint_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, path)


def _copy_checkpoint(source: Path, destination_dir: Path | None) -> None:
    if not destination_dir:
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    latest = destination_dir / "latest_adversarial.pt"
    latest_temporary = latest.with_suffix(latest.suffix + ".tmp")
    shutil.copy2(source, latest_temporary)
    os.replace(latest_temporary, latest)


def _prune_checkpoints(directory: Path | None, keep: int) -> None:
    if not directory or keep <= 0 or not directory.exists():
        return
    checkpoints = sorted(directory.glob("adversarial_epoch_*.pt"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in checkpoints[keep:]:
        try:
            path.unlink()
        except OSError:
            pass


def _decode_batch(tokenizer: RawCharacterTokenizer, sequences) -> list[str]:
    output: list[str] = []
    for row in sequences:
        ids = row.detach().cpu().tolist() if hasattr(row, "detach") else row
        output.append(tokenizer.decode(ids))
    return output


def _diversity(payloads: list[str]) -> tuple[float, float]:
    if not payloads:
        return 0.0, 0.0
    counts = Counter(payloads)
    return len(counts) / len(payloads), max(counts.values()) / len(payloads)


def adv_train(
    generator: Gen,
    discriminator: Disc,
    loader: DataLoader,
    adv_epochs: int,
    g_steps: int,
    d_steps: int,
    d_epochs: int,
    batch_size: int,
    max_len: int,
    rollout_num: int,
    gen_lr: float,
    dis_lr: float,
    l2_reg_lambda: float,
    temperature: float,
    max_batches_per_epoch: int | None,
    device: torch.device,
    tokenizer: RawCharacterTokenizer,
    family: str,
    logger: EpochLogger,
    train_payloads: list[str],
    holdout_payloads: list[str],
    generator_reward_mode: str = "off",
    reward_alpha: float = 0.7,
    disc_label_smoothing: float = 0.0,
    disable_early_stop: bool = False,
    checkpoint_dir: str | Path | None = None,
    checkpoint_copy_dir: str | Path | None = None,
    checkpoint_every: int = 1,
    checkpoint_keep: int = 3,
    resume_latest: bool = False,
) -> dict[str, object]:
    started = perf_counter()
    if adv_epochs <= 0:
        return {
            "stop_reason": "completed",
            "epochs_completed": 0,
            "generator_loss_mean": 0.0,
            "generator_loss_final": 0.0,
            "discriminator_loss_mean": 0.0,
            "discriminator_loss_final": 0.0,
            "reward_mean": 0.0,
            "reward_variance": 0.0,
            "generator_gradient_norm_mean": 0.0,
            "discriminator_gradient_norm_mean": 0.0,
            "training_time_seconds": 0.0,
        }
    combine_generator_rewards(
        torch.zeros(1),
        torch.zeros(1),
        generator_reward_mode,
        reward_alpha,
    )
    print("\n[3/3] adversarial", flush=True)
    print(
        f"generator_reward_mode={generator_reward_mode} reward_alpha={float(reward_alpha):.3f} "
        f"d_steps={d_steps} d_epochs={d_epochs}",
        flush=True,
    )
    optimizer = optim.Adam(generator.parameters(), lr=gen_lr)
    rollout = Rollout(generator, discriminator, rollout_num=rollout_num, temperature=temperature, update_rate=0.8)
    local_checkpoint_dir = _as_path(checkpoint_dir)
    copy_checkpoint_dir = _as_path(checkpoint_copy_dir)
    if local_checkpoint_dir:
        local_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    if copy_checkpoint_dir:
        copy_checkpoint_dir.mkdir(parents=True, exist_ok=True)
    start_epoch = 1
    low_reward_streak = 0
    stop_reason = "completed"
    if resume_latest:
        candidates = _checkpoint_candidates(local_checkpoint_dir, copy_checkpoint_dir)
        if candidates:
            checkpoint_path = candidates[0]
            checkpoint = torch.load(checkpoint_path, map_location=device)
            generator.load_state_dict(checkpoint["generator_state"])
            discriminator.load_state_dict(checkpoint["discriminator_state"])
            if "rollout_beta_state" in checkpoint:
                rollout.beta.load_state_dict(checkpoint["rollout_beta_state"])
            if "gen_optimizer_state" in checkpoint:
                optimizer.load_state_dict(checkpoint["gen_optimizer_state"])
            low_reward_streak = int(checkpoint.get("low_reward_streak", 0))
            start_epoch = int(checkpoint["epoch"]) + 1
            print(f"Resumed adversarial checkpoint {checkpoint_path} at epoch {start_epoch}", flush=True)
    epoch_summaries: list[dict[str, float]] = []
    for epoch in range(start_epoch, adv_epochs + 1):
        epoch_started = perf_counter()
        generator.train()
        discriminator.eval()
        generator_loss_sum = 0.0
        discriminator_reward_sum = 0.0
        sql_reward_sum = 0.0
        reward_sum = 0.0
        reward_square_sum = 0.0
        reward_count = 0
        generator_gradient_sum = 0.0
        for _ in range(g_steps):
            sequences, log_probabilities, mask = generator.sample_with_log_probs(
                batch_size,
                max_len,
                temperature=temperature,
            )
            discriminator_reward = rollout.get_reward(sequences.detach(), mask=mask.detach())
            generated_texts = _decode_batch(tokenizer, sequences)
            sql_values = batch_parser_reward(generated_texts, family)
            sql_reward = torch.tensor(
                sql_values,
                dtype=discriminator_reward.dtype,
                device=discriminator_reward.device,
            ).view(-1, 1).expand_as(discriminator_reward)
            combined_reward = combine_generator_rewards(
                discriminator_reward,
                sql_reward,
                generator_reward_mode,
                reward_alpha,
            )
            denominator = mask.sum().clamp_min(1.0)
            loss = -((log_probabilities * combined_reward.detach() * mask).sum() / denominator)
            optimizer.zero_grad()
            loss.backward()
            gradient_norm = torch.nn.utils.clip_grad_norm_(generator.parameters(), 5.0)
            optimizer.step()
            valid = mask.bool()
            valid_reward = combined_reward[valid]
            generator_loss_sum += float(loss.item())
            discriminator_reward_sum += float(discriminator_reward[valid].sum().item())
            sql_reward_sum += float(sql_reward[valid].sum().item())
            reward_sum += float(valid_reward.sum().item())
            reward_square_sum += float(valid_reward.square().sum().item())
            reward_count += int(valid_reward.numel())
            generator_gradient_sum += float(gradient_norm)
        rollout.update_params()
        generator_loss = generator_loss_sum / max(1, g_steps)
        discriminator_reward_mean = discriminator_reward_sum / max(1, reward_count)
        sql_reward_mean = sql_reward_sum / max(1, reward_count)
        reward_mean = reward_sum / max(1, reward_count)
        reward_variance = max(0.0, reward_square_sum / max(1, reward_count) - reward_mean**2)
        generator_gradient_norm = generator_gradient_sum / max(1, g_steps)
        generator.eval()
        with torch.no_grad():
            snapshot_sequences = generator.sample(SNAPSHOT_N, max_len=max_len, temperature=temperature)
        snapshot_texts = _decode_batch(tokenizer, snapshot_sequences)
        tier_rates = batch_pass_rate(snapshot_texts, family)
        unique_rate, dominant_share = _diversity(snapshot_texts)
        overlap_train = ngram_overlap(snapshot_texts, train_payloads)
        overlap_holdout = ngram_overlap(snapshot_texts, holdout_payloads)
        if not disable_early_stop and discriminator_reward_mean < EARLY_STOP_THRESHOLD:
            low_reward_streak += 1
        else:
            low_reward_streak = 0
        will_stop = not disable_early_stop and low_reward_streak >= EARLY_STOP_PATIENCE
        discriminator_stats = train_disc(
            generator=generator,
            discriminator=discriminator,
            loader=loader,
            d_steps=d_steps,
            k_epochs=d_epochs,
            lr=dis_lr,
            max_batches_per_epoch=max_batches_per_epoch,
            max_len=max_len,
            device=device,
            l2_reg_lambda=l2_reg_lambda,
            label_smoothing=disc_label_smoothing,
        )
        discriminator_loss = float(discriminator_stats["loss_mean"])
        discriminator_gradient_norm = float(discriminator_stats["gradient_norm_mean"])
        epoch_time = perf_counter() - epoch_started
        current_stop_reason = "vanishing_reward" if will_stop else ""
        logger.log(
            epoch=epoch,
            generator_loss=generator_loss,
            discriminator_loss=discriminator_loss,
            discriminator_reward_mean=discriminator_reward_mean,
            sql_structure_reward_mean=sql_reward_mean,
            reward_mean=reward_mean,
            reward_variance=reward_variance,
            generator_gradient_norm=generator_gradient_norm,
            discriminator_gradient_norm=discriminator_gradient_norm,
            unique_rate=unique_rate,
            dominant_payload_share=dominant_share,
            tier_rates=tier_rates,
            nearest_train_ngram_overlap=overlap_train,
            nearest_holdout_ngram_overlap=overlap_holdout,
            epoch_time_seconds=epoch_time,
            snapshot_samples=snapshot_texts,
            stop_reason=current_stop_reason,
        )
        summary = {
            "generator_loss": generator_loss,
            "discriminator_loss": discriminator_loss,
            "discriminator_reward_mean": discriminator_reward_mean,
            "sql_structure_reward_mean": sql_reward_mean,
            "reward_mean": reward_mean,
            "reward_variance": reward_variance,
            "generator_gradient_norm": generator_gradient_norm,
            "discriminator_gradient_norm": discriminator_gradient_norm,
            "unique_rate": unique_rate,
            "dominant_payload_share": dominant_share,
            "epoch_time_seconds": epoch_time,
        }
        epoch_summaries.append(summary)
        print(
            f"ADV epoch={epoch}/{adv_epochs} g_loss={generator_loss:.4f} d_loss={discriminator_loss:.4f} "
            f"reward={reward_mean:.4f} reward_var={reward_variance:.4f} unique={unique_rate:.4f}",
            flush=True,
        )
        if local_checkpoint_dir and (
            int(checkpoint_every) <= 1 or epoch % int(checkpoint_every) == 0 or will_stop
        ):
            checkpoint_payload = {
                "epoch": epoch,
                "adv_epochs": adv_epochs,
                "generator_state": generator.state_dict(),
                "discriminator_state": discriminator.state_dict(),
                "rollout_beta_state": rollout.beta.state_dict(),
                "gen_optimizer_state": optimizer.state_dict(),
                "low_reward_streak": low_reward_streak,
                "stop_reason": "vanishing_reward" if will_stop else "completed",
                "generator_reward_mode": generator_reward_mode,
                "reward_alpha": float(reward_alpha),
                "epoch_metrics": summary,
            }
            epoch_path = local_checkpoint_dir / f"adversarial_epoch_{epoch:04d}.pt"
            latest_path = local_checkpoint_dir / "latest_adversarial.pt"
            _save_checkpoint_atomic(epoch_path, checkpoint_payload)
            _save_checkpoint_atomic(latest_path, checkpoint_payload)
            _copy_checkpoint(epoch_path, copy_checkpoint_dir)
            _prune_checkpoints(local_checkpoint_dir, int(checkpoint_keep))
            _prune_checkpoints(copy_checkpoint_dir, int(checkpoint_keep))
        if will_stop:
            stop_reason = "vanishing_reward"
            break
    completed = len(epoch_summaries)
    final = epoch_summaries[-1] if epoch_summaries else {}

    def mean_value(key: str) -> float:
        return sum(float(row[key]) for row in epoch_summaries) / max(1, completed)

    return {
        "stop_reason": stop_reason,
        "epochs_completed": completed,
        "generator_loss_mean": mean_value("generator_loss") if completed else 0.0,
        "generator_loss_final": float(final.get("generator_loss", 0.0)),
        "discriminator_loss_mean": mean_value("discriminator_loss") if completed else 0.0,
        "discriminator_loss_final": float(final.get("discriminator_loss", 0.0)),
        "reward_mean": mean_value("reward_mean") if completed else 0.0,
        "reward_variance": mean_value("reward_variance") if completed else 0.0,
        "generator_gradient_norm_mean": mean_value("generator_gradient_norm") if completed else 0.0,
        "discriminator_gradient_norm_mean": mean_value("discriminator_gradient_norm") if completed else 0.0,
        "final_unique_rate": float(final.get("unique_rate", 0.0)),
        "final_dominant_payload_share": float(final.get("dominant_payload_share", 0.0)),
        "training_time_seconds": perf_counter() - started,
    }
