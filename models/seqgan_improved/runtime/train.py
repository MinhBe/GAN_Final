from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path as _Path
from time import perf_counter

import pandas as pd
import torch

torch.set_num_threads(1)

_MODEL_ROOT = _Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MODEL_ROOT / "runtime"))
sys.path.insert(0, str(_MODEL_ROOT / "preprocessing"))
sys.path.insert(0, str(_MODEL_ROOT.parent.parent / "export" / "payload_export"))

from adversarial import adv_train
from common.ingestion import classify_family
from config import CONFIGS, SeqGANConfig
from data import attack_payloads, load_payload_dataset
from discriminator import Disc
from epoch_logger import EpochLogger
from features import make_feature_dataframe
from generator import Gen
from holdout import ngram_overlap
from pretrain import pretrain_gen, train_disc
from seqgan_sql_validity import batch_pass_rate
from tokenizer import RawCharacterTokenizer, make_tokenizer
from train_utils import make_loader, seed_everything


def cfg(args: argparse.Namespace, base: SeqGANConfig, name: str):
    value = getattr(args, name)
    return getattr(base, name) if value is None else value


def _latest_adv_checkpoint_path(*directories) -> Path | None:
    candidates: list[Path] = []
    for directory in directories:
        if directory is None or str(directory).strip() == "":
            continue
        path = Path(directory)
        if not path.exists():
            continue
        latest = path / "latest_adversarial.pt"
        if latest.exists():
            candidates.append(latest)
        candidates.extend(sorted(path.glob("adversarial_epoch_*.pt"), key=lambda item: item.stat().st_mtime, reverse=True))
    return candidates[0] if candidates else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _payload_hash(payloads: list[str]) -> str:
    digest = hashlib.sha256()
    for payload in payloads:
        encoded = str(payload).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def build_models(
    args: argparse.Namespace,
    base: SeqGANConfig,
    tokenizer: RawCharacterTokenizer,
    max_len: int,
    device: torch.device,
) -> tuple[Gen, Disc]:
    generator = Gen(
        vocab_size=tokenizer.vocab_size,
        bos_id=tokenizer.bos_id,
        eos_id=tokenizer.eos_id,
        pad_id=tokenizer.pad_id,
        embed_dim=cfg(args, base, "embed_dim"),
        hidden_dim=cfg(args, base, "hidden_dim"),
        num_layers=cfg(args, base, "num_layers"),
    ).to(device)
    discriminator = Disc(
        vocab_size=tokenizer.vocab_size,
        pad_id=tokenizer.pad_id,
        seq_len=max_len,
        embed_dim=cfg(args, base, "disc_embed_dim"),
        num_filters=args.num_filters,
        dropout=cfg(args, base, "dropout"),
        profile=cfg(args, base, "disc_filter_profile"),
    ).to(device)
    return generator, discriminator


def decode(
    generator: Gen,
    tokenizer: RawCharacterTokenizer,
    n_samples: int,
    max_len: int,
    batch_size: int,
    temperature: float,
) -> tuple[list[str], dict[str, float | int]]:
    if n_samples < 0:
        raise ValueError("n_samples must not be negative")
    generator.eval()
    output: list[str] = []
    with torch.no_grad():
        while len(output) < n_samples:
            current_batch = min(batch_size, n_samples - len(output))
            sequences = generator.sample(current_batch, max_len=max_len, temperature=temperature)
            for row in sequences.cpu().tolist():
                output.append(tokenizer.decode(row))
    counts = Counter(output)
    unique_count = len(counts)
    dominant_share = max(counts.values()) / len(output) if output else 0.0
    return output, {
        "requested": n_samples,
        "generated": len(output),
        "empty_count": sum(not value for value in output),
        "unique_count": unique_count,
        "unique_rate": unique_count / len(output) if output else 0.0,
        "collapse_rate": 1.0 - unique_count / len(output) if output else 1.0,
        "dominant_payload_share": dominant_share,
    }


def save_outputs(
    out_dir: Path,
    generated: list[str],
    tokenizer: RawCharacterTokenizer,
    generator: Gen,
    discriminator: Disc,
    metadata: dict[str, object],
) -> None:
    family = str(metadata["family"])
    method = str(metadata["method"])
    run_id = str(metadata["run_id"])
    output_families = [classify_family(payload) for payload in generated] if family == "all" else [family] * len(generated)
    generated_frame = pd.DataFrame(
        {
            "label": ["attack"] * len(generated),
            "payload": generated,
            "family": output_families,
            "payload_type": output_families,
            "method": [method] * len(generated),
            "run_id": [run_id] * len(generated),
            "sample_index": list(range(len(generated))),
        }
    )
    generated_frame.to_csv(out_dir / "generated_payloads.csv", index=False)
    features = make_feature_dataframe(generated)
    pd.concat([generated_frame.reset_index(drop=True), features.reset_index(drop=True)], axis=1).to_csv(
        out_dir / "generated_feature_vectors.csv",
        index=False,
    )
    tokenizer.save(out_dir / "tokenizer.json")
    torch.save(generator.state_dict(), out_dir / "generator.pt")
    torch.save(discriminator.state_dict(), out_dir / "discriminator.pt")
    (out_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_training(args: argparse.Namespace) -> dict[str, object]:
    started_at = datetime.now(timezone.utc)
    started_clock = perf_counter()
    base = CONFIGS[args.config]
    if args.family == "all" and args.generator_reward_mode == "on":
        raise ValueError("SQL structure reward requires a concrete attack family")
    seed = int(cfg(args, base, "seed"))
    max_len = int(cfg(args, base, "max_len"))
    batch_size = int(cfg(args, base, "batch_size"))
    temperature = float(cfg(args, base, "temperature"))
    max_batches = cfg(args, base, "max_batches_per_epoch")
    g_pretrain_epochs = int(cfg(args, base, "g_pretrain_epochs"))
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    seed_everything(seed)
    if torch.cuda.is_available():
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    args.out_dir.mkdir(parents=True, exist_ok=True)
    training_frame = load_payload_dataset(args.dataset)
    holdout_frame = load_payload_dataset(args.holdout_ref)
    training_payloads = attack_payloads(training_frame, cfg(args, base, "max_train_attack"), seed, args.family)
    holdout_payloads = attack_payloads(holdout_frame, None, seed, args.family)
    intersection = set(training_payloads).intersection(holdout_payloads)
    if intersection:
        raise ValueError(f"Training data and fixed holdout overlap by {len(intersection)} exact payloads")
    tokenizer = make_tokenizer(args.tokenizer_mode).build_vocab(training_payloads)
    loader = make_loader(training_payloads, tokenizer, max_len=max_len, batch_size=batch_size, seed=seed)
    generator, discriminator = build_models(args, base, tokenizer, max_len, device)
    resume_checkpoint = (
        _latest_adv_checkpoint_path(args.checkpoint_dir, args.checkpoint_copy_dir)
        if args.resume_latest
        else None
    )
    if resume_checkpoint:
        generator_pretrain_stats: dict[str, object] = {"skipped_for_resume": True}
        discriminator_pretrain_stats: dict[str, object] = {"skipped_for_resume": True}
    else:
        generator_pretrain_stats = pretrain_gen(
            generator=generator,
            loader=loader,
            epochs=g_pretrain_epochs,
            lr=cfg(args, base, "gen_lr"),
            max_batches_per_epoch=max_batches,
            device=device,
        )
        print("\n[2/3] pretrain D", flush=True)
        discriminator_pretrain_stats = train_disc(
            generator=generator,
            discriminator=discriminator,
            loader=loader,
            d_steps=cfg(args, base, "d_pretrain_steps"),
            k_epochs=cfg(args, base, "d_pretrain_epochs"),
            lr=cfg(args, base, "dis_lr"),
            max_batches_per_epoch=max_batches,
            max_len=max_len,
            device=device,
            l2_reg_lambda=cfg(args, base, "l2_reg_lambda"),
            label_smoothing=cfg(args, base, "disc_label_smoothing"),
        )
    effective_reward_alpha = 1.0 if args.generator_reward_mode == "off" else float(args.reward_alpha)
    run_id = "__".join(
        [
            args.method,
            args.phase,
            args.family,
            args.scenario,
            args.ratio,
            args.variant_id,
            args.tokenizer_mode,
            f"len{max_len}",
            f"gpre{g_pretrain_epochs}",
            f"reward_{args.generator_reward_mode}",
            f"seed{seed}",
        ]
    )
    logger = EpochLogger(
        args.out_dir / "logs",
        run_id=run_id,
        method=args.method,
        phase=args.phase,
        family=args.family,
        scenario=args.scenario,
        ratio=args.ratio,
        variant_id=args.variant_id,
        seed=seed,
        tokenizer_mode=args.tokenizer_mode,
        sequence_length=max_len,
        g_pretrain_epochs=g_pretrain_epochs,
        generator_reward_mode=args.generator_reward_mode,
        reward_alpha=effective_reward_alpha,
    )
    try:
        adversarial_stats = adv_train(
            generator=generator,
            discriminator=discriminator,
            loader=loader,
            adv_epochs=cfg(args, base, "adv_epochs"),
            g_steps=cfg(args, base, "g_steps"),
            d_steps=cfg(args, base, "d_steps"),
            d_epochs=cfg(args, base, "d_epochs"),
            batch_size=batch_size,
            max_len=max_len,
            rollout_num=cfg(args, base, "rollout_num"),
            gen_lr=cfg(args, base, "gen_lr") * args.adv_gen_lr_scale,
            dis_lr=cfg(args, base, "dis_lr"),
            l2_reg_lambda=cfg(args, base, "l2_reg_lambda"),
            temperature=temperature,
            max_batches_per_epoch=max_batches,
            device=device,
            tokenizer=tokenizer,
            family=args.family,
            logger=logger,
            train_payloads=training_payloads,
            holdout_payloads=holdout_payloads,
            generator_reward_mode=args.generator_reward_mode,
            reward_alpha=effective_reward_alpha,
            disc_label_smoothing=cfg(args, base, "disc_label_smoothing"),
            disable_early_stop=args.disable_early_stop,
            checkpoint_dir=args.checkpoint_dir,
            checkpoint_copy_dir=args.checkpoint_copy_dir,
            checkpoint_every=args.checkpoint_every,
            checkpoint_keep=args.checkpoint_keep,
            resume_latest=args.resume_latest,
        )
    finally:
        logger.close()
    generated, generation_stats = decode(
        generator,
        tokenizer,
        cfg(args, base, "n_samples"),
        max_len,
        batch_size,
        temperature,
    )
    tier_rates = batch_pass_rate(generated, args.family)
    final_overlap_train = ngram_overlap(generated, training_payloads)
    final_overlap_holdout = ngram_overlap(generated, holdout_payloads)
    finished_at = datetime.now(timezone.utc)
    hyperparameters = {
        "max_len": max_len,
        "batch_size": batch_size,
        "embed_dim": cfg(args, base, "embed_dim"),
        "hidden_dim": cfg(args, base, "hidden_dim"),
        "num_layers": cfg(args, base, "num_layers"),
        "g_pretrain_epochs": g_pretrain_epochs,
        "d_pretrain_steps": cfg(args, base, "d_pretrain_steps"),
        "d_pretrain_epochs": cfg(args, base, "d_pretrain_epochs"),
        "adv_epochs": cfg(args, base, "adv_epochs"),
        "g_steps": cfg(args, base, "g_steps"),
        "d_steps": cfg(args, base, "d_steps"),
        "d_epochs": cfg(args, base, "d_epochs"),
        "rollout_num": cfg(args, base, "rollout_num"),
        "gen_lr": cfg(args, base, "gen_lr"),
        "adversarial_gen_lr": cfg(args, base, "gen_lr") * args.adv_gen_lr_scale,
        "dis_lr": cfg(args, base, "dis_lr"),
        "l2_reg_lambda": cfg(args, base, "l2_reg_lambda"),
        "temperature": temperature,
        "n_samples": cfg(args, base, "n_samples"),
        "max_batches_per_epoch": max_batches,
        "disc_filter_profile": cfg(args, base, "disc_filter_profile"),
        "disc_label_smoothing": cfg(args, base, "disc_label_smoothing"),
        "disc_embed_dim": cfg(args, base, "disc_embed_dim"),
        "dropout": cfg(args, base, "dropout"),
    }
    metadata: dict[str, object] = {
        "schema_version": 2,
        "run_id": run_id,
        "method": args.method,
        "phase": args.phase,
        "family": args.family,
        "scenario": args.scenario,
        "ratio": args.ratio,
        "variant_id": args.variant_id,
        "config": args.config,
        "seed": seed,
        "tokenizer_mode": args.tokenizer_mode,
        "tokenizer_vocab_size": tokenizer.vocab_size,
        "generator_reward_mode": args.generator_reward_mode,
        "reward_alpha": effective_reward_alpha,
        "dataset": str(args.dataset),
        "dataset_sha256": _sha256(args.dataset),
        "holdout_ref": str(args.holdout_ref),
        "holdout_sha256": _sha256(args.holdout_ref),
        "training_payload_count": len(training_payloads),
        "training_payload_sha256": _payload_hash(training_payloads),
        "holdout_payload_count": len(holdout_payloads),
        "holdout_payload_sha256": _payload_hash(holdout_payloads),
        "hyperparameters": hyperparameters,
        "discriminator_capacity": discriminator.capacity_summary(),
        "generator_pretrain": generator_pretrain_stats,
        "discriminator_pretrain": discriminator_pretrain_stats,
        "adversarial_training": adversarial_stats,
        "generation": generation_stats,
        "final_structure_rates": tier_rates,
        "final_ngram_overlap_train": final_overlap_train,
        "final_ngram_overlap_holdout": final_overlap_holdout,
        "stop_reason": adversarial_stats["stop_reason"],
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "training_time_seconds": perf_counter() - started_clock,
        "device": str(device),
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
        "artifacts": {
            "generated_payloads": "generated_payloads.csv",
            "generated_feature_vectors": "generated_feature_vectors.csv",
            "tokenizer": "tokenizer.json",
            "generator": "generator.pt",
            "discriminator": "discriminator.pt",
            "epoch_metrics": "logs/epoch_metrics.csv",
        },
    }
    save_outputs(args.out_dir, generated, tokenizer, generator, discriminator, metadata)
    print(f"saved {len(generated)} raw samples to {args.out_dir / 'generated_payloads.csv'}", flush=True)
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--holdout-ref", type=Path, required=True)
    parser.add_argument("--family", required=True, choices=["all", "boolean", "union", "time", "error"])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--ratio", default="full")
    parser.add_argument("--phase", default="standalone")
    parser.add_argument("--variant-id", default="UNSPECIFIED")
    parser.add_argument("--method", choices=["seqgan_master", "seqgan_improved"], default="seqgan_improved")
    parser.add_argument("--tokenizer-mode", choices=["raw_character", "sql_aware"], default="raw_character")
    parser.add_argument("--generator-reward-mode", choices=["off", "on"], default="off")
    parser.add_argument("--reward-alpha", type=float, default=0.7)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", choices=sorted(CONFIGS), default="seqgan_improved")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--seed", type=int, default=88)
    parser.add_argument("--max-len", "--sequence-length", dest="max_len", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--embed-dim", type=int, default=None)
    parser.add_argument("--hidden-dim", type=int, default=None)
    parser.add_argument("--num-layers", type=int, default=None)
    parser.add_argument("--num-filters", type=int, default=None)
    parser.add_argument("--disc-embed-dim", type=int, default=None)
    parser.add_argument("--disc-filter-profile", choices=["balanced", "tiny", "original"], default=None)
    parser.add_argument("--disc-label-smoothing", type=float, default=None)
    parser.add_argument("--dropout", type=float, default=None)
    parser.add_argument("--g-pretrain-epochs", type=int, default=None)
    parser.add_argument("--d-pretrain-epochs", type=int, default=None)
    parser.add_argument("--d-pretrain-steps", type=int, default=None)
    parser.add_argument("--adv-epochs", type=int, default=None)
    parser.add_argument("--g-steps", type=int, default=None)
    parser.add_argument("--d-steps", type=int, default=None)
    parser.add_argument("--d-epochs", type=int, default=None)
    parser.add_argument("--rollout-num", type=int, default=None)
    parser.add_argument("--gen-lr", type=float, default=None)
    parser.add_argument("--dis-lr", type=float, default=None)
    parser.add_argument("--l2-reg-lambda", type=float, default=None)
    parser.add_argument("--adv-gen-lr-scale", type=float, default=1.0)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--n-samples", type=int, default=None)
    parser.add_argument("--max-train-attack", type=int, default=None)
    parser.add_argument("--max-batches-per-epoch", type=int, default=None)
    parser.add_argument("--disable-early-stop", action="store_true")
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--checkpoint-copy-dir", type=Path, default=None)
    parser.add_argument("--checkpoint-every", type=int, default=1)
    parser.add_argument("--checkpoint-keep", type=int, default=3)
    parser.add_argument("--resume-latest", action="store_true")
    return parser


def main() -> None:
    run_training(build_parser().parse_args())


if __name__ == "__main__":
    main()
