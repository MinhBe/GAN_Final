from __future__ import annotations

from dataclasses import dataclass

META_COLS = ["id", "label", "payload_type", "payload"]


@dataclass(frozen=True)
class Config:
    n_samples: int
    k_neighbors: int


CONFIGS: dict[str, Config] = {
    "small": Config(n_samples=200, k_neighbors=5),
    "medium": Config(n_samples=2000, k_neighbors=5),
    "paperish": Config(n_samples=10000, k_neighbors=5),
}
