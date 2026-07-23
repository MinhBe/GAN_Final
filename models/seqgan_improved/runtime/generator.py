from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class Gen(nn.Module):
    def __init__(
        self,
        vocab_size: int,
        bos_id: int,
        eos_id: int,
        pad_id: int,
        embed_dim: int = 64,
        hidden_dim: int = 128,
        num_layers: int = 1,
    ) -> None:
        super().__init__()
        self.vocab_size = vocab_size
        self.bos_id = bos_id
        self.eos_id = eos_id
        self.pad_id = pad_id
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.lstm = nn.LSTM(embed_dim, hidden_dim, num_layers=num_layers, batch_first=True)
        self.output = nn.Linear(hidden_dim, vocab_size)

    @property
    def device(self) -> torch.device:
        return next(self.parameters()).device

    def init_hidden(self, batch_size: int):
        h = torch.zeros(self.num_layers, batch_size, self.hidden_dim, device=self.device)
        c = torch.zeros(self.num_layers, batch_size, self.hidden_dim, device=self.device)
        return h, c

    def forward(self, input_ids: torch.Tensor, hidden=None):
        if hidden is None:
            hidden = self.init_hidden(input_ids.size(0))
        emb = self.embedding(input_ids)
        out, hidden = self.lstm(emb, hidden)
        return self.output(out), hidden

    def step(self, token: torch.Tensor, hidden):
        emb = self.embedding(token).unsqueeze(1)
        out, hidden = self.lstm(emb, hidden)
        return self.output(out.squeeze(1)), hidden

    def _mask_logits(self, logits: torch.Tensor, allow_pad: bool = False) -> torch.Tensor:
        logits = logits.clone()
        logits[:, self.bos_id] = -1e9
        if not allow_pad:
            logits[:, self.pad_id] = -1e9
        return logits

    @torch.no_grad()
    def sample(self, batch_size: int, max_len: int, temperature: float = 1.0) -> torch.Tensor:
        seq, _, _ = self.sample_with_log_probs(batch_size, max_len, temperature)
        return seq

    def sample_with_log_probs(self, batch_size: int, max_len: int, temperature: float = 1.0):
        hidden = self.init_hidden(batch_size)
        token = torch.full((batch_size,), self.bos_id, dtype=torch.long, device=self.device)
        done = torch.zeros(batch_size, dtype=torch.bool, device=self.device)
        seq: list[torch.Tensor] = []
        logp: list[torch.Tensor] = []
        mask: list[torch.Tensor] = []

        for _ in range(max_len):
            logits, hidden = self.step(token, hidden)
            logits = self._mask_logits(logits)
            prob = F.softmax(logits / max(temperature, 1e-6), dim=-1)
            dist = torch.distributions.Categorical(probs=prob)
            nxt = dist.sample()
            lp = dist.log_prob(nxt)
            active = ~done
            nxt = torch.where(active, nxt, torch.full_like(nxt, self.pad_id))
            lp = torch.where(active, lp, torch.zeros_like(lp))
            seq.append(nxt)
            logp.append(lp)
            mask.append(active.float())
            done = done | nxt.eq(self.eos_id)
            token = nxt

        return torch.stack(seq, 1), torch.stack(logp, 1), torch.stack(mask, 1)

    @torch.no_grad()
    def rollout_from_prefix(self, prefix: torch.Tensor, max_len: int, temperature: float = 1.0) -> torch.Tensor:
        batch_size, prefix_len = prefix.size()
        out = torch.full((batch_size, max_len), self.pad_id, dtype=torch.long, device=self.device)
        if prefix_len > 0:
            out[:, :prefix_len] = prefix[:, :prefix_len]

        hidden = self.init_hidden(batch_size)
        token = torch.full((batch_size,), self.bos_id, dtype=torch.long, device=self.device)
        done = torch.zeros(batch_size, dtype=torch.bool, device=self.device)

        for i in range(prefix_len):
            _, hidden = self.step(token, hidden)
            token = prefix[:, i]
            done = done | token.eq(self.eos_id) | token.eq(self.pad_id)

        tail = self.continue_batched(hidden, token, max_len - prefix_len, temperature=temperature, done=done)
        if max_len - prefix_len > 0:
            out[:, prefix_len:] = tail
        return out

    @torch.no_grad()
    def cache_prefix_states(
        self, sequences: torch.Tensor
    ) -> list[tuple[torch.Tensor, torch.Tensor] | None]:
        """Chay generator (beta) MOT LAN DUY NHAT qua toan bo `sequences` co dinh,
        theo kieu teacher-forcing, de lay san hidden/cell state LSTM tai moi do dai
        prefix cung luc.

        Day la diem thay the cho phan "replay" trong `rollout_from_prefix` cu:
        thay vi voi moi prefix_len lai chay lai tu dau (for i in range(prefix_len):
        step(...)) -- ton O(T) buoc moi lan va lap lai cho T-1 gia tri prefix_len
        (tong O(T^2)) -- o day ta chi chay dung mot luot O(T) va luu lai trang thai
        sau moi buoc. sequences khong doi trong mot lan get_reward() nen ket qua
        thu duoc giong het viec replay lai tung phan, chi khac la khong lap lai
        phan tinh toan da biet.

        Tra ve list `states` do dai (seq_len + 1); `states[L]` (L = 1..seq_len) la
        tuple (h, c) dung bang trang thai ma vong lap replay cu tao ra sau khi da
        'an' L token (BOS + sequences[:, :L-1]). `states[0]` la None (khong dung vi
        prefix_len luon >= 1 trong get_reward).
        """
        batch_size, seq_len = sequences.size()
        hidden = self.init_hidden(batch_size)
        token = torch.full((batch_size,), self.bos_id, dtype=torch.long, device=self.device)
        states: list[tuple[torch.Tensor, torch.Tensor] | None] = [None]
        for t in range(seq_len):
            _, hidden = self.step(token, hidden)
            states.append(hidden)
            token = sequences[:, t]
        return states

    @torch.no_grad()
    def continue_batched(
        self,
        hidden,
        start_token: torch.Tensor,
        remaining_len: int,
        temperature: float = 1.0,
        done: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Sinh tiep `remaining_len` token cho TOAN BO batch cung luc, xuat phat tu
        (hidden, start_token) da cho san.

        Day la diem "vector hoa vong rollout_num": thay vi goi ham nay (hay
        rollout_from_prefix cu) `rollout_num` lan lien tiep -- moi lan mot lenh
        Python/kernel rieng -- tang goi (Rollout.get_reward) nhan prefix + hidden
        state da cache thanh batch kich thuoc B*rollout_num roi goi ham nay dung
        mot lan. Batch cang lon thi moi buoc step() cang tan dung GPU tot hon,
        thay vi de GPU cho Python phong hang ngan kernel nho tuan tu.

        `done`: mask (batch,) cho biet nhung dong nao da ket thuc (gap eos/pad)
        TRUOC KHI buoc sinh nay bat dau -- vi du do chinh prefix co dinh da chua
        eos/pad. Neu khong truyen, coi nhu chua co dong nao ket thuc.
        """
        batch_size = start_token.size(0)
        out = torch.full((batch_size, max(0, remaining_len)), self.pad_id, dtype=torch.long, device=self.device)
        if remaining_len <= 0:
            return out
        if done is None:
            done = torch.zeros(batch_size, dtype=torch.bool, device=self.device)
        else:
            done = done.clone()
        token = start_token
        for pos in range(remaining_len):
            logits, hidden = self.step(token, hidden)
            logits = self._mask_logits(logits)
            prob = F.softmax(logits / max(temperature, 1e-6), dim=-1)
            nxt = torch.multinomial(prob, 1).squeeze(1)
            nxt = torch.where(done, torch.full_like(nxt, self.pad_id), nxt)
            out[:, pos] = nxt
            done = done | nxt.eq(self.eos_id)
            token = nxt
        return out

