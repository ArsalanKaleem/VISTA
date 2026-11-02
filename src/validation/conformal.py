"""Conformalised quantile regression with a spatially blocked calibration set (Days 76, 86)."""
from __future__ import annotations

import numpy as np


def cqr_offset(y_cal, q_lo_cal, q_hi_cal, alpha: float = 0.1) -> float:
    scores = np.maximum(q_lo_cal - y_cal, y_cal - q_hi_cal)
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def coverage(y, lo, hi) -> float:
    return float(np.mean((y >= lo) & (y <= hi)))


def interval_width(lo, hi) -> float:
    return float(np.mean(hi - lo))
