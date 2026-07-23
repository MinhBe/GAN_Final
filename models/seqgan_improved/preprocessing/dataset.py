from __future__ import annotations

import torch
from torch.utils.data import Dataset as TorchDataset

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent))

from tokenizer import CharTokenizer


class Dataset(TorchDataset):
    def __init__(self, payloads, tokenizer: CharTokenizer, max_len: int) -> None:
        self.payloads = list(payloads)
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.payloads)

    def __getitem__(self, index):
        ids = self.tokenizer.encode_for_lm(self.payloads[index], self.max_len)
        return torch.tensor(ids, dtype=torch.long)
