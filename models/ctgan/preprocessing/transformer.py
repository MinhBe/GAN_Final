
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.mixture import BayesianGaussianMixture


@dataclass
class ContinuousInfo:
    name: str
    means: np.ndarray
    stds: np.ndarray
    weights: np.ndarray
    alpha_slice: slice
    beta_slice: slice

    @property
    def n_modes(self) -> int:
        return len(self.means)


@dataclass
class DiscreteInfo:
    name: str
    categories: list[str]
    slice: slice
    cond_offset: int

    @property
    def dim(self) -> int:
        return len(self.categories)


class CTGANTransformer:
    def __init__(self, continuous_cols: list[str], discrete_cols: list[str],
                 max_modes: int = 5, random_state: int = 88):
        self.continuous_cols = list(continuous_cols)
        self.discrete_cols = list(discrete_cols)
        self.max_modes = max_modes
        self.random_state = random_state
        self.continuous_info: list[ContinuousInfo] = []
        self.discrete_info: list[DiscreteInfo] = []
        self.output_dim: int = 0
        self.cond_dim: int = 0

    def fit(self, df: pd.DataFrame) -> "CTGANTransformer":
        self.continuous_info = []
        self.discrete_info = []
        cur = 0
        rng = np.random.default_rng(self.random_state)

        for col in self.continuous_cols:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0.0).values.astype(float)
            n_unique = len(np.unique(vals))

            if n_unique <= 1 or float(np.std(vals)) < 1e-8:
                means = np.array([float(np.mean(vals))], dtype=np.float32)
                stds = np.array([1.0], dtype=np.float32)
                weights = np.array([1.0], dtype=np.float32)
            else:
                n_comp = max(1, min(self.max_modes, n_unique))
                bgm = BayesianGaussianMixture(
                    n_components=n_comp, covariance_type="full",
                    weight_concentration_prior_type="dirichlet_process",
                    weight_concentration_prior=0.001, max_iter=35, n_init=1,
                    random_state=int(rng.integers(0, 2**31 - 1)), reg_covar=1e-6,
                )
                bgm.fit(vals.reshape(-1, 1))
                w = bgm.weights_.astype(np.float64)
                m = bgm.means_.reshape(-1).astype(np.float64)
                s = np.sqrt(np.maximum(bgm.covariances_.reshape(n_comp, -1)[:, 0], 1e-6)).astype(np.float64)
                active = w > max(0.005, 1.0 / (20 * n_comp))
                if not np.any(active):
                    active[np.argmax(w)] = True
                order = np.argsort(m[active])
                means = m[active][order].astype(np.float32)
                stds = s[active][order].astype(np.float32)
                weights = w[active][order].astype(np.float32)
                weights /= max(float(weights.sum()), 1e-12)

            info = ContinuousInfo(
                name=col, means=means, stds=stds, weights=weights,
                alpha_slice=slice(cur, cur + 1),
                beta_slice=slice(cur + 1, cur + 1 + len(means)),
            )
            cur += 1 + len(means)
            self.continuous_info.append(info)

        cond_cur = 0
        for col in self.discrete_cols:
            cats = sorted(str(x) for x in pd.Series(df[col]).dropna().astype(str).unique())
            if not cats:
                cats = ["__missing__"]
            info = DiscreteInfo(
                name=col, categories=cats,
                slice=slice(cur, cur + len(cats)),
                cond_offset=cond_cur,
            )
            cur += len(cats)
            cond_cur += len(cats)
            self.discrete_info.append(info)

        self.output_dim = cur
        self.cond_dim = cond_cur
        return self

    def _mode_probs(self, vals: np.ndarray, info: ContinuousInfo) -> np.ndarray:
        x = vals.reshape(-1, 1).astype(np.float64)
        means = info.means.reshape(1, -1).astype(np.float64)
        stds = np.maximum(info.stds.reshape(1, -1).astype(np.float64), 1e-6)
        w = info.weights.reshape(1, -1).astype(np.float64)
        logp = np.log(w + 1e-12) - np.log(stds) - 0.5 * ((x - means) / stds) ** 2
        logp -= logp.max(axis=1, keepdims=True)
        probs = np.exp(logp)
        probs /= np.maximum(probs.sum(axis=1, keepdims=True), 1e-12)
        return probs.astype(np.float32)

    def transform(self, df: pd.DataFrame, sample_modes: bool = True) -> np.ndarray:
        n = len(df)
        out = np.zeros((n, self.output_dim), dtype=np.float32)
        rng = np.random.default_rng(self.random_state)

        for info in self.continuous_info:
            vals = pd.to_numeric(df[info.name], errors="coerce").fillna(0.0).values.astype(float)
            probs = self._mode_probs(vals, info)
            if sample_modes and info.n_modes > 1:
                mode_ids = np.array([rng.choice(info.n_modes, p=p) for p in probs], dtype=int)
            else:
                mode_ids = probs.argmax(axis=1).astype(int)
            alpha = (vals - info.means[mode_ids]) / (4.0 * np.maximum(info.stds[mode_ids], 1e-6))
            out[:, info.alpha_slice] = np.clip(alpha, -0.99, 0.99).reshape(-1, 1)
            out[np.arange(n), info.beta_slice.start + mode_ids] = 1.0

        for info in self.discrete_info:
            vals = pd.Series(df[info.name]).astype(str).values
            cat_to_idx = {c: i for i, c in enumerate(info.categories)}
            idx = np.array([cat_to_idx.get(v, 0) for v in vals], dtype=int)
            out[np.arange(n), info.slice.start + idx] = 1.0
        return out

    def inverse_transform(self, data: np.ndarray) -> pd.DataFrame:
        arr = np.asarray(data, dtype=np.float32)
        rows = {}
        for info in self.continuous_info:
            alpha = arr[:, info.alpha_slice].reshape(-1)
            mode_ids = arr[:, info.beta_slice].argmax(axis=1)
            rows[info.name] = (alpha * 4.0 * info.stds[mode_ids] + info.means[mode_ids]).astype(float)
        for info in self.discrete_info:
            idx = arr[:, info.slice].argmax(axis=1)
            rows[info.name] = [info.categories[int(i)] for i in idx]
        return pd.DataFrame(rows)

    def discrete_col_index(self, name: str) -> int:
        for i, info in enumerate(self.discrete_info):
            if info.name == name:
                return i
        raise KeyError(name)
