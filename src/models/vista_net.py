"""VISTA-Net fusion skeleton with ablation switches (Days 74-77). Code from Section 12.3."""
from __future__ import annotations

import torch
import torch.nn as nn


class CrossModalFusion(nn.Module):
    def __init__(self, d: int = 128, heads: int = 4, use_cross: bool = True):
        super().__init__()
        self.use_cross = use_cross
        self.attn = nn.MultiheadAttention(d, heads, batch_first=True)
        self.gate = nn.Linear(2 * d, d)
        self.concat = nn.Sequential(nn.Linear(2 * d, d), nn.GELU())
        self.norm = nn.LayerNorm(d)

    def forward(self, h_t, kv, kv_mask=None):
        # h_t: [B, L, d] temporal tokens; kv: [B, T_s + L, d] spatial + climate tokens
        if self.use_cross:
            a, _ = self.attn(h_t, kv, kv, key_padding_mask=kv_mask)
            g = torch.sigmoid(self.gate(torch.cat([h_t, a], dim=-1)))
            out = g * a + (1 - g) * h_t
        else:  # concat control: pooled kv appended to every temporal token
            pooled = kv.mean(dim=1, keepdim=True).expand_as(h_t)
            out = self.concat(torch.cat([h_t, pooled], dim=-1))
        return self.norm(out).mean(dim=1)  # z: [B, d]


class Heads(nn.Module):
    def __init__(self, d: int = 128, horizons: int = 3, targets: int = 3, n_cls: int = 3):
        super().__init__()
        self.reg = nn.Linear(d, horizons * targets * 2)  # mu and log-variance
        self.cls = nn.Linear(d, n_cls)
        self.h, self.k = horizons, targets

    def forward(self, z):
        r = self.reg(z).view(-1, self.h, self.k, 2)
        return r[..., 0], r[..., 1].clamp(-6, 4), self.cls(z)


def gaussian_nll(mu, logvar, y, mask):
    loss = 0.5 * (logvar + (y - mu) ** 2 * torch.exp(-logvar))
    return (loss * mask).sum() / mask.sum().clamp(min=1)
