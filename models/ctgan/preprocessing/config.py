from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CTGANConfig:
    epochs: int
    batch_size: int
    z_dim: int
    hidden_dim: int
    pac: int
    critic_steps: int
    lambda_gp: float
    cond_loss_weight: float
    lr: float
    tau: float
    dropout: float
    max_modes: int
    n_samples: int


CONFIGS: dict[str, CTGANConfig] = {
    "small": CTGANConfig(
        epochs=50,
        batch_size=500,
        z_dim=128,
        hidden_dim=256,
        pac=10,
        critic_steps=5,
        lambda_gp=10.0,
        cond_loss_weight=1.0,
        lr=2e-4,
        tau=0.2,
        dropout=0.15,
        max_modes=5,
        n_samples=500,
    ),
    "medium": CTGANConfig(
        epochs=300,
        batch_size=500,
        z_dim=128,
        hidden_dim=256,
        pac=10,
        critic_steps=5,
        lambda_gp=10.0,
        cond_loss_weight=1.0,
        lr=2e-4,
        tau=0.2,
        dropout=0.15,
        max_modes=5,
        n_samples=2000,
    ),
    "paperish": CTGANConfig(
        epochs=300,
        batch_size=500,
        z_dim=128,
        hidden_dim=256,
        pac=10,
        critic_steps=5,
        lambda_gp=10.0,
        cond_loss_weight=1.0,
        lr=2e-4,
        tau=0.2,
        dropout=0.15,
        max_modes=10,
        n_samples=10000,
    ),
}
