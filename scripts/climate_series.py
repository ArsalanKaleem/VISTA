"""Days 35-36 (local part): CHIRPS and ERA5-Land series for every zone, SPI and SPEI, from the exported grids.

    python scripts/climate_series.py

Design (D003): the grids are coarse (CHIRPS 0.05 deg, ERA5-Land 0.1 deg) and shared by many hamlets, so the
monthly series are stored once per grid cell, and each zone carries area weights to the cells it overlaps
(exact polygon-cell intersection in EPSG:32642, the method validated on Day 26). A village series is the
weighted combination, computed on demand by src/preprocessing/climate.py. Nothing is interpolated.

Drought indices (cell level, 1981-2025):
  SPI-k  (k = 1, 3, 6, 12) from CHIRPS precipitation. Per calendar month, the k-month sum over the baseline
         1981-2010 (configs/gee.yaml periods.climate_baseline; ends before the 2018-2025 validation/test
         years) is fitted with a gamma distribution on the non-zero values and a zero probability p0
         (Stagge et al. 2015 mixed distribution); the CDF is mapped to the standard normal.
  SPEI-k from ERA5-Land P - PET on the ERA5 grid (one grid, no resampling). PET = -pev x 1000 mm: ERA5-Land
         potential_evaporation_sum is negative downward (checked on the data and recorded). Three-parameter
         log-logistic fitted by L-moments (Vicente-Serrano et al. 2010).
Parameters are saved (spi_params / spei_params) so the same baseline fit is reused on later years.

Outputs: data/climate/zonal_local/
  cells_chirps.parquet, cells_era5.parquet       long: cell_id, var, YYYYMM columns (float32)
  cell_index_<product>.parquet                   cell_id, row, col, lon, lat
  weights_<product>.parquet                      key (vid|zone), cell_id, w (m2)
  spi_cells.parquet, spei_cells.parquet          cell_id, scale, YYYYMM columns
  spi_params.parquet, spei_params.parquet
  climate_checks.csv                             PET sign, baseline mean/sd of the indices, zero-rain shares
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
import yaml
from scipy import stats
from scipy.special import ndtri

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
OUT = ROOT / "data/climate/zonal_local"
GRIDS = {"chirps": ROOT / "data/climate/chirps/grid", "era5": ROOT / "data/climate/era5/grid"}
UTM = 32642
SCALES = (1, 3, 6, 12)


def log(msg, t0):
    print(f"[{time.time() - t0:6.0f} s] {msg}", flush=True)


# --------------------------------------------------------------------------- cells
def cell_series(product: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """All bands of all yearly GeoTIFFs as cell x YYYYMM tables, one per variable."""
    files = sorted(GRIDS[product].glob(f"{product}_grid_*.tif"))
    with rasterio.open(files[0]) as r:
        h, w, t = r.height, r.width, r.transform
    rows, cols = np.divmod(np.arange(h * w), w)
    xs, ys = t * (cols + 0.5, rows + 0.5)
    index = pd.DataFrame({"cell_id": np.arange(h * w), "row": rows, "col": cols, "lon": xs, "lat": ys})
    per_var: dict[str, dict[str, np.ndarray]] = {}
    for f in files:
        with rasterio.open(f) as r:
            assert (r.height, r.width) == (h, w), f
            arr = r.read(masked=True).astype("float32").filled(np.nan)
            for b, name in enumerate(r.descriptions):
                var, ym = name.rsplit("_", 1)
                per_var.setdefault(var, {})[ym] = arr[b].ravel()
    tables = {}
    for var, d in per_var.items():
        months = sorted(d)
        tables[var] = pd.DataFrame(np.column_stack([d[m] for m in months]), columns=months)
        tables[var].insert(0, "cell_id", index.cell_id.values)
    long = pd.concat([tb.assign(var=v) for v, tb in tables.items()], ignore_index=True)
    return index, long, {"transform": t, "shape": (h, w)}


def weights(product: str, index: pd.DataFrame, meta: dict, zones: gpd.GeoDataFrame) -> pd.DataFrame:
    t = meta["transform"]
    h, w = meta["shape"]
    minx, miny, maxx, maxy = zones.total_bounds
    c0, r0 = ~t * (minx, maxy)
    c1, r1 = ~t * (maxx, miny)
    cols = np.arange(max(int(np.floor(c0)), 0), min(int(np.ceil(c1)), w))
    rows = np.arange(max(int(np.floor(r0)), 0), min(int(np.ceil(r1)), h))
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    x0, y0 = t * (cc, rr)
    x1, y1 = t * (cc + 1, rr + 1)
    cells = gpd.GeoDataFrame({"cell_id": rr * w + cc}, geometry=shapely.box(x0, y1, x1, y0), crs=4326)
    pairs = gpd.sjoin(zones[["key", "geometry"]], cells, predicate="intersects")
    inter = shapely.intersection(zones.geometry.loc[pairs.index].values, cells.geometry.loc[pairs.index_right].values)
    area = gpd.GeoSeries(inter, crs=4326).to_crs(UTM).area.values
    wdf = pd.DataFrame({"key": pairs.key.values, "cell_id": pairs.cell_id.values, "w": area})
    return wdf[wdf.w > 0].reset_index(drop=True)


# --------------------------------------------------------------------------- indices
def rolling_sum(x: np.ndarray, k: int) -> np.ndarray:
    """k-month trailing sum along axis 1; NaN where the window is incomplete."""
    if k == 1:
        return x.copy()
    c = np.cumsum(np.nan_to_num(x), axis=1)
    out = np.full_like(x, np.nan)
    out[:, k - 1:] = c[:, k - 1:] - np.concatenate([np.zeros((x.shape[0], 1)), c[:, :-k]], axis=1)
    bad = np.isnan(x)
    badk = np.zeros_like(bad)
    for i in range(k):
        badk[:, k - 1:] |= bad[:, i:x.shape[1] - k + 1 + i]
    out[badk] = np.nan
    return out


def spi_fit_transform(acc: np.ndarray, months: list[str], base: tuple[int, int]):
    """acc: cells x months accumulated precipitation. Gamma + zero mass per calendar month on baseline years."""
    yrs = np.array([int(m[:4]) for m in months])
    mon = np.array([int(m[4:]) for m in months])
    inb = (yrs >= base[0]) & (yrs <= base[1])
    z = np.full_like(acc, np.nan)
    params = []
    for m in range(1, 13):
        sel = mon == m
        b = acc[:, sel & inb]
        for ci in range(acc.shape[0]):
            v = b[ci][~np.isnan(b[ci])]
            if len(v) < 10:
                params.append((ci, m, np.nan, np.nan, np.nan))
                continue
            p0 = float((v <= 0).mean())
            pos = v[v > 0]
            if len(pos) >= 5 and pos.std() > 0:
                a, _, sc = stats.gamma.fit(pos, floc=0)
            else:
                a, sc = np.nan, np.nan
            params.append((ci, m, a, sc, p0))
            x = acc[ci, sel]
            if np.isfinite(a):
                g = stats.gamma.cdf(x, a, 0, sc)
            else:  # too few wet months to fit: empirical CDF among the baseline positives (Weibull plotting position)
                g = (np.searchsorted(np.sort(pos), x, side="right")) / (len(pos) + 1) if len(pos) else np.full_like(x, 0.5)
            # zero months sit at the centre of the zero mass (p0 / 2), positive months above it
            cdf = np.where(x <= 0, p0 / 2, p0 + (1 - p0) * g)
            cdf = np.clip(cdf, 0.0005, 0.9995)
            z[ci, sel] = ndtri(cdf)
    return z, pd.DataFrame(params, columns=["cell_idx", "month", "gamma_a", "gamma_scale", "p0"])


def loglogistic_lmom(v: np.ndarray):
    """3-parameter log-logistic by probability-weighted moments (Vicente-Serrano et al. 2010, eq. 10-13):
    w_s = mean((1 - F_i)^s D_i) with D ascending and F_i = (i - 0.35) / n."""
    from scipy.special import gamma as G
    v = np.sort(v)
    n = len(v)
    F = (np.arange(1, n + 1) - 0.35) / n
    w0, w1, w2 = v.mean(), np.mean((1 - F) * v), np.mean((1 - F) ** 2 * v)
    beta = (2 * w1 - w0) / (6 * w1 - w0 - 6 * w2)
    if not np.isfinite(beta) or beta <= 1 or beta > 50:
        return np.nan, np.nan, np.nan
    g1g2 = G(1 + 1 / beta) * G(1 - 1 / beta)
    alpha = (w0 - 2 * w1) * beta / g1g2
    gam = w0 - alpha * g1g2
    return alpha, beta, gam


def spei_fit_transform(acc: np.ndarray, months: list[str], base: tuple[int, int]):
    yrs = np.array([int(m[:4]) for m in months])
    mon = np.array([int(m[4:]) for m in months])
    inb = (yrs >= base[0]) & (yrs <= base[1])
    z = np.full_like(acc, np.nan)
    params = []
    for m in range(1, 13):
        sel = mon == m
        b = acc[:, sel & inb]
        for ci in range(acc.shape[0]):
            v = b[ci][~np.isnan(b[ci])]
            if len(v) < 10:
                params.append((ci, m, np.nan, np.nan, np.nan))
                continue
            a, be, g = loglogistic_lmom(v)
            params.append((ci, m, a, be, g))
            if not np.isfinite(a):
                continue
            x = acc[ci, sel]
            with np.errstate(divide="ignore", invalid="ignore"):
                cdf = 1 / (1 + (a / (x - g)) ** be)
            cdf = np.where(x <= g, 0.0005, cdf)
            cdf = np.clip(cdf, 0.0005, 0.9995)
            z[ci, sel] = ndtri(cdf)
    return z, pd.DataFrame(params, columns=["cell_idx", "month", "ll_alpha", "ll_beta", "ll_gamma"])


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "configs/gee.yaml").read_text())
    base = tuple(cfg["periods"]["climate_baseline"])
    checks = []

    zones = []
    for zone in ("core", "resource"):
        z = gpd.read_parquet(VI / f"zones/v1/zones_{zone}.parquet")[["vid", "geometry"]]
        z["key"] = z.vid + "|" + zone
        zones.append(z[["key", "geometry"]])
    zones = gpd.GeoDataFrame(pd.concat(zones, ignore_index=True), crs=4326)
    zones = zones[~zones.geometry.is_empty]
    log(f"{len(zones):,} zones", t0)

    series = {}
    for product in ("chirps", "era5"):
        index, long, meta = cell_series(product)
        index.to_parquet(OUT / f"cell_index_{product}.parquet", index=False)
        long.to_parquet(OUT / f"cells_{product}.parquet", index=False)
        series[product] = (index, long, meta)
        log(f"{product}: {long['var'].nunique()} vars x {long.shape[1] - 2} months on {len(index):,} cells", t0)
        w = weights(product, index, meta, zones)
        w.to_parquet(OUT / f"weights_{product}.parquet", index=False)
        nz = w.groupby("key").size()
        checks.append({"check": f"{product}_zones_with_weights", "value": int(nz.size), "note": f"of {len(zones):,}; median cells per zone {nz.median():.0f}"})
        log(f"{product}: weights for {nz.size:,} zones ({len(w):,} pairs)", t0)

    # SPI from CHIRPS precip
    idx, long, _ = series["chirps"]
    months = [c for c in long.columns if c not in ("cell_id", "var")]
    P = long[long["var"] == "precip"].set_index("cell_id")[months].values.astype("float64")
    valid = ~np.isnan(P).all(axis=1)
    checks.append({"check": "chirps_cells_with_data", "value": int(valid.sum()), "note": f"of {len(P)}"})
    checks.append({"check": "zero_rain_month_share_baseline", "value": round(float((P[valid][:, [int(m[:4]) <= base[1] for m in months]] <= 0).mean()), 4),
                   "note": "handled with a zero-mass term p0 per cell and calendar month"})
    spi_rows, spi_par = [], []
    for k in SCALES:
        z, par = spi_fit_transform(rolling_sum(P[valid], k), months, base)
        df = pd.DataFrame(z.astype("float32"), columns=months)
        df.insert(0, "cell_id", idx.cell_id.values[valid]); df.insert(1, "scale", k)
        spi_rows.append(df)
        par["cell_id"] = idx.cell_id.values[valid][par.cell_idx.values]; par["scale"] = k
        spi_par.append(par.drop(columns="cell_idx"))
        inb = [base[0] <= int(m[:4]) <= base[1] for m in months]
        zb = z[:, inb]
        checks.append({"check": f"spi{k}_baseline_mean", "value": round(float(np.nanmean(zb)), 3), "note": "expect about 0"})
        checks.append({"check": f"spi{k}_baseline_sd", "value": round(float(np.nanstd(zb)), 3), "note": "expect about 1"})
        log(f"SPI-{k} done", t0)
    pd.concat(spi_rows, ignore_index=True).to_parquet(OUT / "spi_cells.parquet", index=False)
    pd.concat(spi_par, ignore_index=True).to_parquet(OUT / "spi_params.parquet", index=False)

    # SPEI from ERA5 tp - PET
    idx, long, _ = series["era5"]
    months_e = [c for c in long.columns if c not in ("cell_id", "var")]
    tp = long[long["var"] == "tp"].set_index("cell_id")[months_e].values.astype("float64")
    pev = long[long["var"] == "pev"].set_index("cell_id")[months_e].values.astype("float64")
    pev_med = float(np.nanmedian(pev))
    sign = -1.0 if pev_med < 0 else 1.0
    checks.append({"check": "era5_pev_median", "value": round(pev_med, 5), "note": f"PET = {'-' if sign < 0 else '+'}pev x 1000 mm (ERA5-Land flux sign)"})
    tp_med = float(np.nanmedian(tp))
    unit = 1000.0 if abs(tp_med) < 5 else 1.0  # metres -> mm unless already mm
    checks.append({"check": "era5_tp_median", "value": round(tp_med, 5), "note": f"x{unit:.0f} to mm"})
    D = tp * unit - sign * pev * unit
    valid_e = ~np.isnan(D).all(axis=1)
    spei_rows, spei_par = [], []
    for k in SCALES:
        z, par = spei_fit_transform(rolling_sum(D[valid_e], k), months_e, base)
        df = pd.DataFrame(z.astype("float32"), columns=months_e)
        df.insert(0, "cell_id", idx.cell_id.values[valid_e]); df.insert(1, "scale", k)
        spei_rows.append(df)
        par["cell_id"] = idx.cell_id.values[valid_e][par.cell_idx.values]; par["scale"] = k
        spei_par.append(par.drop(columns="cell_idx"))
        inb = [base[0] <= int(m[:4]) <= base[1] for m in months_e]
        zb = z[:, inb]
        checks.append({"check": f"spei{k}_baseline_mean", "value": round(float(np.nanmean(zb)), 3), "note": "expect about 0"})
        checks.append({"check": f"spei{k}_baseline_sd", "value": round(float(np.nanstd(zb)), 3), "note": "expect about 1"})
        checks.append({"check": f"spei{k}_cells_fit_failed", "value": int(par.ll_alpha.isna().sum()), "note": "cell-months without an L-moment fit"})
        log(f"SPEI-{k} done", t0)
    pd.concat(spei_rows, ignore_index=True).to_parquet(OUT / "spei_cells.parquet", index=False)
    pd.concat(spei_par, ignore_index=True).to_parquet(OUT / "spei_params.parquet", index=False)
    pd.DataFrame(checks).to_csv(OUT / "climate_checks.csv", index=False)
    print(pd.DataFrame(checks).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
