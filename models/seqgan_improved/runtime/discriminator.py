from __future__ import annotations

from typing import Sequence

import torch
import torch.nn as nn
import torch.nn.functional as F





ORIGINAL_FILTER_SIZES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20)
ORIGINAL_FILTER_COUNTS: tuple[int, ...] = (100, 200, 200, 200, 200, 100, 100, 100, 100, 100, 160, 160)
AUTHOR_FILTER_SIZES: tuple[int, ...] = ORIGINAL_FILTER_SIZES
AUTHOR_FILTER_COUNTS: tuple[int, ...] = ORIGINAL_FILTER_COUNTS



BALANCED_FILTER_SIZES: tuple[int, ...] = ORIGINAL_FILTER_SIZES
BALANCED_FILTER_COUNTS: tuple[int, ...] = (32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32)


TINY_FILTER_SIZES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10)
TINY_FILTER_COUNTS: tuple[int, ...] = (16, 16, 16, 16, 16, 16, 16, 16)

FILTER_PROFILES: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "original": (ORIGINAL_FILTER_SIZES, ORIGINAL_FILTER_COUNTS),
    "balanced": (BALANCED_FILTER_SIZES, BALANCED_FILTER_COUNTS),
    "tiny": (TINY_FILTER_SIZES, TINY_FILTER_COUNTS),
}


FILTER_SIZES: tuple[int, ...] = BALANCED_FILTER_SIZES
FILTER_COUNTS: tuple[int, ...] = BALANCED_FILTER_COUNTS


class Highway(nn.Module):
    def __init__(self, size: int, bias: float = 0.0) -> None:
        super().__init__()
        self.proj = nn.Linear(size, size)
        self.gate = nn.Linear(size, size)
        nn.init.constant_(self.gate.bias, bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = F.relu(self.proj(x))
        t = torch.sigmoid(self.gate(x))
        return t * h + (1.0 - t) * x


class Disc(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        pad_id: int,
        seq_len: int,
        embed_dim: int = 64,
        filter_sizes: Sequence[int] | None = None,
        num_filters: int | Sequence[int] | None = None,
        dropout: float = 0.35,
        profile: str = "balanced",
    ) -> None:
        super().__init__()
        self.pad_id = pad_id
        self.seq_len = seq_len
        self.capacity_profile = str(profile or "balanced")

        if self.capacity_profile not in FILTER_PROFILES:
            raise ValueError(f"Unknown discriminator profile={profile!r}; expected one of {sorted(FILTER_PROFILES)}")
        profile_sizes, profile_counts = FILTER_PROFILES[self.capacity_profile]
        sizes = tuple(int(x) for x in (filter_sizes if filter_sizes is not None else profile_sizes))
        if num_filters is None:
            
            count_by_size = {int(s): int(c) for s, c in zip(profile_sizes, profile_counts)}
            counts = tuple(count_by_size.get(int(size), int(profile_counts[-1])) for size in sizes)
        elif isinstance(num_filters, int):
            counts = (int(num_filters),) * len(sizes)
        else:
            counts = tuple(int(x) for x in num_filters)
        if len(counts) != len(sizes):
            raise ValueError("num_filters and filter_sizes length mismatch.")

        pairs = [(size, count) for size, count in zip(sizes, counts) if size <= seq_len] or [(1, counts[0])]
        self.filter_sizes = tuple(size for size, _ in pairs)
        self.num_filters_per_size = tuple(count for _, count in pairs)
        self.total_filters = int(sum(self.num_filters_per_size))

        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.convs = nn.ModuleList(
            [nn.Conv2d(1, count, (size, embed_dim)) for size, count in pairs]
        )
        dim = self.total_filters
        self.highway = Highway(dim)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(dim, 2)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        
        
        
        
        
        valid_len = input_ids.ne(self.pad_id).sum(dim=1).clamp(min=1)  

        emb = self.embedding(input_ids).unsqueeze(1)
        pooled = []
        for conv, size in zip(self.convs, self.filter_sizes):
            h = F.relu(conv(emb)).squeeze(3)  
            out_len = h.size(2)
            
            
            positions = torch.arange(out_len, device=h.device).unsqueeze(0)  
            window_end = positions + size
            is_valid = window_end <= valid_len.unsqueeze(1)  
            
            
            
            has_any_valid = is_valid.any(dim=1, keepdim=True)
            fill_mask = (~is_valid) & has_any_valid
            if fill_mask.any():
                h = h.masked_fill(fill_mask.unsqueeze(1), torch.finfo(h.dtype).min)
            pooled.append(F.max_pool1d(h, kernel_size=out_len).squeeze(2))
        x = torch.cat(pooled, dim=1)
        x = self.dropout(self.highway(x))
        return self.fc(x)

    def prob_real(self, input_ids: torch.Tensor) -> torch.Tensor:
        return F.softmax(self.forward(input_ids), dim=1)[:, 1]

    def capacity_summary(self) -> dict[str, object]:
        return {
            "profile": self.capacity_profile,
            "seq_len": self.seq_len,
            "filter_sizes": list(self.filter_sizes),
            "num_filters_per_size": list(self.num_filters_per_size),
            "total_filters": self.total_filters,
        }

