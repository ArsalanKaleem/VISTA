"""Spatial blocks and folds (Days 63, 65, 81). Code from Section 12.3.

H3 hexagon blocks, folds balanced by ecoregion, buffer rings removed from training.
Block resolution is set from the semivariogram range on Day 63 (res 4 ~ 1,770 km2).
"""
from __future__ import annotations

import h3
import numpy as np
import pandas as pd


def assign_blocks(df: pd.DataFrame, res: int = 4) -> pd.DataFrame:
    df = df.copy()
    df["block"] = [h3.latlng_to_cell(la, lo, res) for la, lo in zip(df.lat, df.lon)]
    return df


def make_folds(df: pd.DataFrame, n_folds: int = 5, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    blocks = df.groupby("block").agg(region=("ecoregion", lambda x: x.mode().iat[0]),
                                     n=("vid", "size")).reset_index()
    blocks["fold"] = -1
    for _, g in blocks.groupby("region"):
        order = g.sample(frac=1.0, random_state=int(rng.integers(1e9))).sort_values("n", ascending=False)
        for k, idx in enumerate(order.index):
            blocks.loc[idx, "fold"] = k % n_folds
    return df.merge(blocks[["block", "fold"]], on="block")


def train_mask(df: pd.DataFrame, test_fold: int, buffer_rings: int = 1) -> pd.Series:
    test_blocks = set(df.loc[df.fold == test_fold, "block"])
    excluded = set(test_blocks)
    for b in test_blocks:
        excluded |= set(h3.grid_disk(b, buffer_rings))
    return ~df["block"].isin(excluded)
