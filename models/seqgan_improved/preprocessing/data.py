from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from common.dataset_schema import canonical_payload_frame


def load_payload_dataset(path: str | Path) -> pd.DataFrame:
    return canonical_payload_frame(path, include_other=True)[["payload", "label", "payload_type"]]


def attack_payloads(df: pd.DataFrame, max_train_attack: int | None, seed: int, family: str = "all") -> list[str]:
    labels = set(df["label"].astype(str))
    if labels != {"attack"}:
        raise ValueError(f"Generator datasets must contain only attack rows, got {sorted(labels)}")
    attacks = df[df["label"].eq("attack")]
    if family != "all":
        observed = set(attacks["payload_type"].astype(str))
        if observed != {family}:
            raise ValueError(f"Expected only family={family!r}, got {sorted(observed)}")
    payloads = attacks["payload"].dropna().astype(str).tolist()
    if not payloads:
        raise ValueError("No attack payloads found")
    if max_train_attack is not None and len(payloads) > max_train_attack:
        payloads = pd.Series(payloads).sample(n=max_train_attack, random_state=seed).tolist()
    return payloads
