from __future__ import annotations

import numpy as np
from sklearn.neighbors import NearestNeighbors


def _smote_class(values: np.ndarray, n_samples: int, *, k_neighbors: int, seed: int) -> np.ndarray:
    generator = np.random.default_rng(seed)
    features = np.asarray(values, dtype=float)
    if len(features) == 0:
        raise ValueError("Cannot run SMOTE on an empty class")
    if len(features) == 1:
        return np.repeat(features, n_samples, axis=0)
    neighbor_count = min(k_neighbors + 1, len(features))
    # Avoid materializing an (n_rows, n_rows, n_features) difference tensor.
    # For the Phase 1 pool that tensor exceeds 50 GiB before temporary arrays.
    nearest = NearestNeighbors(
        n_neighbors=neighbor_count,
        metric="euclidean",
        algorithm="auto",
    ).fit(features)
    neighbor_indices = nearest.kneighbors(
        features,
        return_distance=False,
    )
    output: list[np.ndarray] = []
    for _ in range(n_samples):
        source = int(generator.integers(0, len(features)))
        choices = neighbor_indices[source][1:] if len(neighbor_indices[source]) > 1 else neighbor_indices[source]
        neighbor = int(generator.choice(choices))
        interpolation = float(generator.random())
        output.append(features[source] + interpolation * (features[neighbor] - features[source]))
    return np.vstack(output)
