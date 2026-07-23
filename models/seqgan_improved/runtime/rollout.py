from __future__ import annotations

import copy

import torch

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parent))

from discriminator import Disc
from generator import Gen


class Rollout:
    def __init__(
        self,
        generator: Gen,
        discriminator: Disc,
        rollout_num: int = 16,
        temperature: float = 1.0,
        update_rate: float = 0.8,
    ) -> None:
        self.generator = generator
        self.beta = copy.deepcopy(generator).to(generator.device)
        self.discriminator = discriminator
        self.rollout_num = max(1, int(rollout_num))
        self.temperature = temperature
        self.update_rate = float(update_rate)
        self.update_params(hard=True)

    def update_params(self, hard: bool = False) -> None:
        with torch.no_grad():
            for beta, theta in zip(self.beta.parameters(), self.generator.parameters()):
                beta.copy_(theta) if hard else beta.mul_(self.update_rate).add_(theta, alpha=1.0 - self.update_rate)
            for beta, theta in zip(self.beta.buffers(), self.generator.buffers()):
                beta.copy_(theta)
        self.beta.eval()

    @torch.no_grad()
    def get_reward(self, sequences: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        was_training = self.discriminator.training
        self.discriminator.eval()
        self.beta.eval()

        B, T = sequences.size()
        device = sequences.device
        rewards = torch.zeros(B, T, device=device)

        # sequences co dinh trong suot mot lan get_reward() -> tinh hidden state
        # cua beta tai MOI do dai prefix chi mot lan (O(T)), thay vi replay lai tu
        # dau cho tung prefix_len (O(T^2)). Xem docstring cua cache_prefix_states.
        prefix_states = self.beta.cache_prefix_states(sequences)

        # "done" (da gap eos/pad) tinh san cho moi do dai prefix cung mot luot,
        # dung dung ngu nghia voi vong replay cu (chi phu thuoc sequences co dinh,
        # khong phu thuoc phan sinh ngau nhien).
        terminal = sequences.eq(self.beta.eos_id) | sequences.eq(self.beta.pad_id)
        done_upto = torch.cummax(terminal, dim=1).values  # done_upto[:, t] ung voi da xu ly t+1 token dau

        rollout_num = self.rollout_num
        for prefix_len in range(1, T):
            hidden = prefix_states[prefix_len]
            last_token = sequences[:, prefix_len - 1]
            prefix_done = done_upto[:, prefix_len - 1]

            # Vector hoa vong rollout_num: nhan batch B len B*rollout_num va goi
            # continue_batched DUNG MOT LAN, thay vi goi rollout_num=16 lan tuan tu.
            h, c = hidden
            rep_hidden = (
                h.repeat_interleave(rollout_num, dim=1),
                c.repeat_interleave(rollout_num, dim=1),
            )
            rep_token = last_token.repeat_interleave(rollout_num, dim=0)
            rep_done = prefix_done.repeat_interleave(rollout_num, dim=0)
            rep_prefix = sequences[:, :prefix_len].repeat_interleave(rollout_num, dim=0)

            tails = self.beta.continue_batched(
                rep_hidden,
                rep_token,
                remaining_len=T - prefix_len,
                temperature=self.temperature,
                done=rep_done,
            )
            completed = torch.cat([rep_prefix, tails], dim=1)  # (B*rollout_num, T)
            scores = self.discriminator.prob_real(completed).view(B, rollout_num)
            rewards[:, prefix_len - 1] = scores.mean(dim=1)

        rewards[:, T - 1] = self.discriminator.prob_real(sequences)
        if mask is not None:
            rewards = rewards * mask.to(rewards.device)
        if was_training:
            self.discriminator.train()
        return rewards

