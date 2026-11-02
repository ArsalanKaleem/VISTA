"""Relational GATv2 with edge features (Day 75). Code from Section 12.3.

Message passing uses node features only, never labels of validation/test nodes.
"""
from __future__ import annotations

import torch
import torch.nn as nn
from torch_geometric.nn import GATv2Conv


class VillageGAT(nn.Module):
    def __init__(self, d: int = 128, edge_dim: int = 6, heads: int = 4, layers: int = 2, dropout: float = 0.1):
        super().__init__()
        self.convs = nn.ModuleList([GATv2Conv(d, d // heads, heads=heads, edge_dim=edge_dim, dropout=dropout)
                                    for _ in range(layers)])
        self.norms = nn.ModuleList([nn.LayerNorm(d) for _ in range(layers)])

    def forward(self, z, edge_index, edge_attr):
        for conv, norm in zip(self.convs, self.norms):
            z = norm(z + torch.relu(conv(z, edge_index, edge_attr)))
        return z
