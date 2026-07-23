from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeqGANConfig:
    max_len: int
    batch_size: int
    embed_dim: int
    hidden_dim: int
    num_layers: int
    g_pretrain_epochs: int
    d_pretrain_steps: int
    d_pretrain_epochs: int
    adv_epochs: int
    g_steps: int
    d_steps: int
    d_epochs: int
    rollout_num: int
    gen_lr: float
    dis_lr: float
    l2_reg_lambda: float
    temperature: float
    n_samples: int
    max_train_attack: int | None
    max_batches_per_epoch: int | None
    seed: int
    disc_filter_profile: str
    disc_label_smoothing: float
    disc_embed_dim: int
    dropout: float


SEQGAN_MASTER = SeqGANConfig(
    max_len=20,
    batch_size=64,
    embed_dim=32,
    hidden_dim=32,
    num_layers=1,
    g_pretrain_epochs=120,
    d_pretrain_steps=50,
    d_pretrain_epochs=3,
    adv_epochs=200,
    g_steps=1,
    d_steps=5,
    d_epochs=3,
    rollout_num=16,
    gen_lr=1e-2,
    dis_lr=1e-4,
    l2_reg_lambda=0.2,
    temperature=1.0,
    n_samples=10000,
    max_train_attack=None,
    max_batches_per_epoch=None,
    seed=88,
    disc_filter_profile="original",
    disc_label_smoothing=0.0,
    disc_embed_dim=64,
    dropout=0.25,
)

SEQGAN_IMPROVED = SeqGANConfig(
    max_len=20,
    batch_size=64,
    embed_dim=32,
    hidden_dim=32,
    num_layers=1,
    g_pretrain_epochs=120,
    d_pretrain_steps=50,
    d_pretrain_epochs=3,
    adv_epochs=200,
    g_steps=1,
    d_steps=5,
    d_epochs=3,
    rollout_num=16,
    gen_lr=1e-2,
    dis_lr=1e-4,
    l2_reg_lambda=0.2,
    temperature=1.0,
    n_samples=10000,
    max_train_attack=None,
    max_batches_per_epoch=None,
    seed=88,
    disc_filter_profile="balanced",
    disc_label_smoothing=0.05,
    disc_embed_dim=64,
    dropout=0.25,
)

CONFIGS: dict[str, SeqGANConfig] = {
    "seqgan_master": SEQGAN_MASTER,
    "seqgan_improved": SEQGAN_IMPROVED,
}
