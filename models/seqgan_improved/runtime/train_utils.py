from __future__ import annotations

import random
from typing import Iterable

import numpy as np
import torch
from torch.utils.data import DataLoader

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "preprocessing"))

from dataset import Dataset
from tokenizer import CharTokenizer


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def make_loader(payloads: list[str], tokenizer: CharTokenizer, max_len: int, batch_size: int, seed: int) -> DataLoader:
    dataset = Dataset(payloads, tokenizer, max_len)
    gen = torch.Generator().manual_seed(seed)
    return DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=len(dataset) >= batch_size, generator=gen)


def limited_batches(loader: DataLoader, max_batches: int | None) -> Iterable[torch.Tensor]:
    for idx, batch in enumerate(loader):
        if max_batches is not None and idx >= max_batches:
            break
        yield batch


def real_sequences(batch_lm: torch.Tensor) -> torch.Tensor:
    return batch_lm[:, 1:]
