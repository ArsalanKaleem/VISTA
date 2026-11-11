"""Days 35-36: rolling sums, SPI baseline moments on synthetic data, and the weighted village combination."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from climate_series import rolling_sum, spi_fit_transform, spei_fit_transform  # noqa: E402
from src.preprocessing.climate import ClimateStore  # noqa: E402


def _months(y0, y1):
    return [f"{y}{m:02d}" for y in range(y0, y1 + 1) for m in range(1, 13)]


def test_rolling_sum_matches_pandas():
    x = np.random.default_rng(0).gamma(2, 10, size=(3, 60))
    x[1, 5] = np.nan
    got = rolling_sum(x, 3)
    want = pd.DataFrame(x.T).rolling(3).sum().values.T  # NaN where any of the 3 is NaN
    assert np.allclose(np.nan_to_num(got, nan=-1), np.nan_to_num(want, nan=-1))


def test_spi_baseline_moments_and_zero_mass():
    rng = np.random.default_rng(1)
    months = _months(1981, 2025)
    n = len(months)
    p = rng.gamma(1.5, 20, size=(4, n))
    p[:, [i for i, m in enumerate(months) if m[4:] in ("01", "02", "11", "12")]] *= rng.random(1) * 0.05  # dry months
    p[p < 1] = 0.0
    z, par = spi_fit_transform(rolling_sum(p, 1), months, (1981, 2010))
    inb = np.array([1981 <= int(m[:4]) <= 2010 for m in months])
    assert abs(np.nanmean(z[:, inb])) < 0.15 and 0.75 < np.nanstd(z[:, inb]) < 1.25
    assert (par.p0 >= 0).all() and (par.p0 <= 1).all() and np.isfinite(z).all()


def test_spei_baseline_moments():
    rng = np.random.default_rng(2)
    months = _months(1981, 2025)
    d = rng.normal(-50, 30, size=(3, len(months)))
    z, par = spei_fit_transform(rolling_sum(d, 3), months, (1981, 2010))
    inb = np.array([1981 <= int(m[:4]) <= 2010 for m in months])
    assert abs(np.nanmean(z[:, inb])) < 0.15 and 0.75 < np.nanstd(z[:, inb]) < 1.25


def test_weighted_combination(tmp_path):
    cells = pd.DataFrame({"cell_id": [0, 1, 2], "var": "precip", "202301": [10.0, 20.0, np.nan], "202302": [1.0, 3.0, 5.0]})
    w = pd.DataFrame({"key": ["a|core", "a|core", "b|core"], "cell_id": [0, 1, 2], "w": [1.0, 3.0, 2.0]})
    cells.to_parquet(tmp_path / "cells_chirps.parquet", index=False)
    w.to_parquet(tmp_path / "weights_chirps.parquet", index=False)
    out = ClimateStore(tmp_path).series("chirps", "precip", ["a|core", "b|core"])
    assert np.isclose(out.loc["a|core", "202301"], (10 * 1 + 20 * 3) / 4)
    assert np.isclose(out.loc["a|core", "202302"], (1 * 1 + 3 * 3) / 4)
    assert np.isnan(out.loc["b|core", "202301"]) and np.isclose(out.loc["b|core", "202302"], 5.0)
