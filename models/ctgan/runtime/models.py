
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "preprocessing"))

from models.ctgan.preprocessing.transformer import CTGANTransformer


class _ResBlock(nn.Module):
    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.fc = nn.Linear(in_dim, out_dim)
        self.bn = nn.BatchNorm1d(out_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.cat([x, F.relu(self.bn(self.fc(x)))], dim=1)


class CTGANGenerator(nn.Module):
    def __init__(self, z_dim: int, cond_dim: int, transformer: CTGANTransformer,
                 hidden_dim: int = 256, tau: float = 0.2):
        super().__init__()
        self.z_dim = z_dim
        self.cond_dim = cond_dim
        self.transformer = transformer
        self.tau = tau

        in_dim = z_dim + cond_dim
        self.block1 = _ResBlock(in_dim, hidden_dim)
        self.block2 = _ResBlock(in_dim + hidden_dim, hidden_dim)
        final_dim = in_dim + 2 * hidden_dim

        self.heads = nn.ModuleList()
        self.head_kind: list[str] = []
        for info in transformer.continuous_info:
            self.heads.append(nn.Linear(final_dim, 1))
            self.head_kind.append("alpha")
            self.heads.append(nn.Linear(final_dim, info.n_modes))
            self.head_kind.append("beta")
        for info in transformer.discrete_info:
            self.heads.append(nn.Linear(final_dim, info.dim))
            self.head_kind.append("discrete")

    def forward(self, z: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        h = torch.cat([z, cond], dim=1)
        h = self.block1(h)
        h = self.block2(h)
        outs = []
        for head, kind in zip(self.heads, self.head_kind):
            logits = head(h)
            if kind == "alpha":
                outs.append(torch.tanh(logits))
            else:
                outs.append(F.gumbel_softmax(logits, tau=self.tau, hard=False, dim=1))
        return torch.cat(outs, dim=1)


class CTGANCritic(nn.Module):
    def __init__(self, row_dim: int, cond_dim: int, hidden_dim: int = 256,
                 pac: int = 10, dropout: float = 0.15):
        super().__init__()
        self.pac = pac
        in_dim = (row_dim + cond_dim) * pac
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.LeakyReLU(0.2),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LeakyReLU(0.2),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, row: torch.Tensor, cond: torch.Tensor) -> torch.Tensor:
        x = torch.cat([row, cond], dim=1)
        b = x.size(0)
        return self.net(x.view(b // self.pac, -1)).view(-1)


def conditional_loss(fake: torch.Tensor, transformer: CTGANTransformer,
                     selected_cols: torch.Tensor, local_cats: torch.Tensor) -> torch.Tensor:
    losses = []
    for col_id, info in enumerate(transformer.discrete_info):
        mask = selected_cols == col_id
        if mask.any():
            probs = fake[mask][:, info.slice]
            targets = local_cats[mask]
            chosen = probs[torch.arange(probs.size(0), device=probs.device), targets]
            losses.append(-torch.log(chosen + 1e-8).mean())
    return torch.stack(losses).mean() if losses else torch.tensor(0.0, device=fake.device)


def gradient_penalty(critic: CTGANCritic, real: torch.Tensor, fake: torch.Tensor,
                     cond: torch.Tensor, lambda_gp: float = 10.0) -> torch.Tensor:
    b = real.size(0)
    eps = torch.rand(b, 1, device=real.device)
    interp = (eps * real + (1.0 - eps) * fake).requires_grad_(True)
    scores = critic(interp, cond)
    grad = torch.autograd.grad(
        outputs=scores, inputs=interp,
        grad_outputs=torch.ones_like(scores),
        create_graph=True, retain_graph=True, only_inputs=True,
    )[0]
    return lambda_gp * ((grad.view(b, -1).norm(2, dim=1) - 1.0) ** 2).mean()
