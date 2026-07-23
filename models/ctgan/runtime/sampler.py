
from __future__ import annotations

import numpy as np
import pandas as pd

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "preprocessing"))

from models.ctgan.preprocessing.transformer import CTGANTransformer


class ConditionalSampler:
    def __init__(self, df: pd.DataFrame, transformer: CTGANTransformer, seed: int = 88):
        self.df = df.reset_index(drop=True)
        self.transformer = transformer
        self.rng = np.random.default_rng(seed)
        self.n = len(df)

        self.col_probs: list[np.ndarray] = []
        self.row_by_value: list[list[np.ndarray]] = []

        for info in transformer.discrete_info:
            vals = df[info.name].astype(str).values
            counts = np.array([(vals == cat).sum() for cat in info.categories], dtype=np.float64)
            log_probs = np.log(np.maximum(counts, 1.0) + 1.0)
            log_probs /= max(float(log_probs.sum()), 1e-12)
            self.col_probs.append(log_probs)
            self.row_by_value.append([
                np.where(vals == cat)[0] if (vals == cat).any() else np.arange(self.n)
                for cat in info.categories
            ])

    def sample_train(self, batch_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        nd = len(self.transformer.discrete_info)
        selected_cols = self.rng.integers(0, nd, size=batch_size)
        local_cats = np.zeros(batch_size, dtype=np.int64)
        row_indices = np.zeros(batch_size, dtype=np.int64)
        cond = np.zeros((batch_size, self.transformer.cond_dim), dtype=np.float32)

        for i, col_id in enumerate(selected_cols):
            col_id = int(col_id)
            info = self.transformer.discrete_info[col_id]
            cat_id = int(self.rng.choice(info.dim, p=self.col_probs[col_id]))
            local_cats[i] = cat_id
            cond[i, info.cond_offset + cat_id] = 1.0
            row_indices[i] = int(self.rng.choice(self.row_by_value[col_id][cat_id]))

        return cond, row_indices, selected_cols.astype(np.int64), local_cats

    def sample_generation(
        self,
        batch_size: int,
        target_label: str | None = None,
        target_payload_type: str | None = None,
    ) -> tuple[np.ndarray, list[str], list[str]]:
        type_info = self.transformer.discrete_info[self.transformer.discrete_col_index("payload_type")]
        vals = self.df["payload_type"].astype(str).values

        if target_payload_type is not None:
            if target_payload_type not in type_info.categories:
                raise ValueError(f"Unknown payload_type: {target_payload_type!r}. Known: {type_info.categories}")
            chosen_types = [target_payload_type] * batch_size
        else:
            allowed = [t for t in type_info.categories if not (
                (target_label == "attack" and t == "normal") or
                (target_label == "normal" and t != "normal")
            )]
            if not allowed:
                allowed = list(type_info.categories)
            counts = np.array([(vals == t).sum() for t in allowed], dtype=np.float64)
            probs = np.log(counts + 1.0)
            probs /= max(float(probs.sum()), 1e-12)
            chosen_types = [str(self.rng.choice(allowed, p=probs)) for _ in range(batch_size)]

        cond = np.zeros((batch_size, self.transformer.cond_dim), dtype=np.float32)
        labels_out: list[str] = []
        for i, typ in enumerate(chosen_types):
            local = type_info.categories.index(typ)
            cond[i, type_info.cond_offset + local] = 1.0
            labels_out.append("normal" if typ == "normal" else "attack")

        return cond, labels_out, chosen_types
