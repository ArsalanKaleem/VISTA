"""Skill vs climatology with block bootstrap (Days 66, 81-83; Section 11.4)."""
from __future__ import annotations

import numpy as np


def skill_score(y, pred, clim) -> float:
    """SS = 1 - MSE_model / MSE_climatology."""
    mse_m = np.mean((y - pred) ** 2)
    mse_c = np.mean((y - clim) ** 2)
    return 1.0 - mse_m / mse_c


def block_bootstrap(metric_fn, blocks, y, pred, clim, n_boot: int = 1000, seed: int = 0):
    """Resample spatial blocks with replacement; returns the 2.5/50/97.5 percentiles."""
    rng = np.random.default_rng(seed)
    ub = np.unique(blocks)
    out = []
    for _ in range(n_boot):
        pick = rng.choice(ub, size=len(ub), replace=True)
        idx = np.concatenate([np.where(blocks == b)[0] for b in pick])
        out.append(metric_fn(y[idx], pred[idx], clim[idx]))
    return np.percentile(out, [2.5, 50, 97.5])
