from __future__ import annotations

import sys
from pathlib import Path as _Path
from time import perf_counter

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

sys.path.insert(0, str(_Path(__file__).resolve().parent))

from discriminator import Disc
from generator import Gen
from train_utils import limited_batches, real_sequences


def discriminator_l2_loss(discriminator: Disc, l2_reg_lambda: float) -> torch.Tensor:
    if l2_reg_lambda <= 0:
        return torch.zeros((), device=discriminator.fc.weight.device)
    return 0.5 * float(l2_reg_lambda) * (
        discriminator.fc.weight.pow(2).sum() + discriminator.fc.bias.pow(2).sum()
    )


def pretrain_gen(
    generator: Gen,
    loader: DataLoader,
    epochs: int,
    lr: float,
    max_batches_per_epoch: int | None,
    device: torch.device,
) -> dict[str, float | int]:
    started = perf_counter()
    if epochs <= 0:
        return {
            "epochs": 0,
            "batches": 0,
            "loss_mean": 0.0,
            "loss_final": 0.0,
            "gradient_norm_mean": 0.0,
            "duration_seconds": 0.0,
        }
    print("\n[1/3] pretrain G", flush=True)
    generator.train()
    optimizer = optim.Adam(generator.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss(ignore_index=generator.pad_id)
    loss_sum = 0.0
    grad_sum = 0.0
    batches = 0
    final_loss = 0.0
    for epoch in range(1, epochs + 1):
        epoch_loss = 0.0
        epoch_batches = 0
        for batch in limited_batches(loader, max_batches_per_epoch):
            batch = batch.to(device)
            logits, _ = generator(batch[:, :-1])
            loss = criterion(logits.reshape(-1, generator.vocab_size), batch[:, 1:].reshape(-1))
            optimizer.zero_grad()
            loss.backward()
            grad_norm = torch.nn.utils.clip_grad_norm_(generator.parameters(), 5.0)
            optimizer.step()
            value = float(loss.item())
            epoch_loss += value
            loss_sum += value
            grad_sum += float(grad_norm)
            epoch_batches += 1
            batches += 1
        final_loss = epoch_loss / max(1, epoch_batches)
        print(f"G epoch={epoch}/{epochs} loss={final_loss:.4f}", flush=True)
    return {
        "epochs": int(epochs),
        "batches": batches,
        "loss_mean": loss_sum / max(1, batches),
        "loss_final": final_loss,
        "gradient_norm_mean": grad_sum / max(1, batches),
        "duration_seconds": perf_counter() - started,
    }


def train_disc(
    generator: Gen,
    discriminator: Disc,
    loader: DataLoader,
    d_steps: int,
    k_epochs: int,
    lr: float,
    max_batches_per_epoch: int | None,
    max_len: int,
    device: torch.device,
    l2_reg_lambda: float = 0.0,
    label_smoothing: float = 0.0,
) -> dict[str, float | int]:
    started = perf_counter()
    if d_steps <= 0 or k_epochs <= 0:
        return {
            "steps": 0,
            "epochs": 0,
            "batches": 0,
            "loss_mean": 0.0,
            "loss_final": 0.0,
            "gradient_norm_mean": 0.0,
            "duration_seconds": 0.0,
        }
    generator.eval()
    optimizer = optim.Adam(discriminator.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss(label_smoothing=float(label_smoothing))
    disc_batch_size = int(getattr(loader, "batch_size", None) or 64)
    loss_sum = 0.0
    grad_sum = 0.0
    batches = 0
    final_loss = 0.0
    completed_epochs = 0
    for d_step in range(1, d_steps + 1):
        inputs: list[torch.Tensor] = []
        labels: list[torch.Tensor] = []
        with torch.no_grad():
            for batch in limited_batches(loader, max_batches_per_epoch):
                real = real_sequences(batch.to(device))
                size = real.size(0)
                inputs.extend([real, generator.sample(size, max_len)])
                labels.extend(
                    [
                        torch.ones(size, dtype=torch.long, device=device),
                        torch.zeros(size, dtype=torch.long, device=device),
                    ]
                )
        if not inputs:
            continue
        x = torch.cat(inputs)
        y = torch.cat(labels)
        permutation = torch.randperm(y.size(0), device=device)
        x = x[permutation]
        y = y[permutation]
        usable = y.size(0) // disc_batch_size * disc_batch_size
        if usable <= 0:
            continue
        x = x[:usable]
        y = y[:usable]
        for epoch in range(1, k_epochs + 1):
            discriminator.train()
            epoch_loss = 0.0
            epoch_batches = 0
            for start in range(0, usable, disc_batch_size):
                logits = discriminator(x[start : start + disc_batch_size])
                ce_loss = criterion(logits, y[start : start + disc_batch_size])
                loss = ce_loss + discriminator_l2_loss(discriminator, l2_reg_lambda)
                optimizer.zero_grad()
                loss.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(discriminator.parameters(), 5.0)
                optimizer.step()
                value = float(loss.item())
                epoch_loss += value
                loss_sum += value
                grad_sum += float(grad_norm)
                epoch_batches += 1
                batches += 1
            completed_epochs += 1
            final_loss = epoch_loss / max(1, epoch_batches)
            print(
                f"D step={d_step}/{d_steps} epoch={epoch}/{k_epochs} loss={final_loss:.4f} "
                f"l2={float(l2_reg_lambda):.4f} label_smoothing={float(label_smoothing):.3f}",
                flush=True,
            )
    return {
        "steps": int(d_steps),
        "epochs": completed_epochs,
        "batches": batches,
        "loss_mean": loss_sum / max(1, batches),
        "loss_final": final_loss,
        "gradient_norm_mean": grad_sum / max(1, batches),
        "duration_seconds": perf_counter() - started,
    }
