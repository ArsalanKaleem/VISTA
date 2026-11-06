"""Day 26 acceptance: does the GEE zonal pipeline reproduce independent local checks?

Checklist (documentation/day_tracker.csv, Day 26):
  1. Pilot export reproduces a local rasterio check within tolerance
  2. Retry logic tested by failure
  3. Manifest tracks all tasks
Plus an external agreement check against the SWAI village indicators (prior project).

1. Exact area-weighted zone means are recomputed locally from the wave 1 CHIRPS/ERA5 GeoTIFFs
   (cell polygons intersected with zone polygons) and compared with the GEE zonal CSVs.
4. SWAI: rainfall/dry-season rainfall are recomputed from the local CHIRPS grids at the 5,159 SWAI
   village points (same data and method: must match); elevation and NDVI are compared for the SWAI
   villages that fall inside pilot zones (different methods: agreement, not identity).

    python scripts/day26_acceptance.py
Writes documentation/day26_acceptance.md, outputs/tables/day26_*.csv and the long-format pilot
store data/processed/pilot_v0/<product>.parquet.
"""
from __future__ import annotations

import csv
import glob
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gee_to_long import to_long  # noqa: E402

ZONES = ROOT / "data/village_inventory/zones/pilot_zones_v0.geojson"
ZDIR = {"satellite": ROOT / "data/satellite/zonal/pilot_v0", "climate": ROOT / "data/climate/zonal/pilot_v0"}
GRID = {"chirps": ROOT / "data/climate/chirps/grid/chirps_grid_{y}.tif",
        "era5": ROOT / "data/climate/era5/grid/era5_grid_{y}.tif"}
PRIOR = ROOT / "data/reference/prior_work"
TABLES = ROOT / "outputs/tables"
UTM = 32642
# per-variable tolerance: |gee - local| <= max(abs_tol, rel_tol * |local|)
TOL = {"precip": (0.5, 0.02), "rdays": (0.25, 0.02), "t2m": (0.1, 0.0), "tp": (0.0005, 0.02)}
PASS_SHARE = 0.95


def product_csvs(product: str) -> pd.DataFrame:
    sub = "climate" if product in ("chirps_zonal", "era5_zonal") else "satellite"
    files = sorted(glob.glob(str(ZDIR[sub] / product / "*.csv")))
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def cell_polygons(path: Path, bounds) -> gpd.GeoDataFrame:
    """Grid cells of a north-up GeoTIFF covering `bounds` as polygons with their row/col."""
    with rasterio.open(path) as r:
        t = r.transform
        c0, r0 = ~t * (bounds[0], bounds[3])
        c1, r1 = ~t * (bounds[2], bounds[1])
        cols = range(max(int(np.floor(c0)), 0), min(int(np.ceil(c1)), r.width))
        rows = range(max(int(np.floor(r0)), 0), min(int(np.ceil(r1)), r.height))
    recs = []
    for i in rows:
        for j in cols:
            x0, y0 = t * (j, i)
            x1, y1 = t * (j + 1, i + 1)
            recs.append((i, j, shapely.box(x0, y1, x1, y0)))
    return gpd.GeoDataFrame(recs, columns=["row", "col", "geometry"], crs=4326)


def area_weights(zones: gpd.GeoDataFrame, cells: gpd.GeoDataFrame) -> pd.DataFrame:
    """Intersection area (m2) of every zone with every grid cell it touches."""
    pairs = gpd.sjoin(zones[["key", "geometry"]], cells, predicate="intersects")
    inter = shapely.intersection(zones.geometry.loc[pairs.index].values,
                                 cells.geometry.loc[pairs["index_right"]].values)
    area = gpd.GeoSeries(inter, crs=4326).to_crs(UTM).area.values
    return pd.DataFrame({"key": pairs["key"].values, "row": pairs["row"].values,
                         "col": pairs["col"].values, "w": area})


def local_zone_means(path: Path, bands: list[str], weights: pd.DataFrame) -> pd.DataFrame:
    with rasterio.open(path) as r:
        names = list(r.descriptions)
        out = {}
        for b in bands:
            arr = r.read(names.index(b) + 1, masked=True).astype("float64").filled(np.nan)
            v = arr[weights["row"].values, weights["col"].values]
            ok = ~np.isnan(v)
            num = pd.Series(np.where(ok, v * weights["w"].values, 0.0)).groupby(weights["key"].values).sum()
            den = pd.Series(np.where(ok, weights["w"].values, 0.0)).groupby(weights["key"].values).sum()
            out[b] = num / den.replace(0, np.nan)
    return pd.DataFrame(out)


def compare(gee: pd.Series, local: pd.Series, var: str) -> dict:
    d = pd.concat([gee.rename("gee"), local.rename("local")], axis=1).dropna()
    a, rel = TOL[var]
    diff = (d.gee - d["local"]).abs()
    within = diff <= np.maximum(a, rel * d["local"].abs())
    return dict(n=len(d), pearson_r=round(pearsonr(d.gee, d["local"])[0], 5) if len(d) > 2 else np.nan,
                mae=round(diff.mean(), 5), p95_abs_diff=round(diff.quantile(0.95), 5),
                share_within_tol=round(within.mean(), 4), tol=f"max({a}, {rel:.0%} of local)")


def check_local_rasters(zones: gpd.GeoDataFrame) -> pd.DataFrame:
    zones = zones.copy()
    zones["key"] = zones["vid"] + "|" + zones["zone"]
    zones = zones.set_index(pd.RangeIndex(len(zones)))
    rows = []
    for prod, grid, vars_ in [("chirps_zonal", "chirps", ["precip", "rdays"]), ("era5_zonal", "era5", ["t2m", "tp"])]:
        path = Path(str(GRID[grid]).format(y=2023))
        cells = cell_polygons(path, zones.total_bounds)
        w = area_weights(zones, cells)
        bands = [f"{v}_2023{m:02d}" for v in vars_ for m in range(1, 13)]
        loc = local_zone_means(path, bands, w)
        g = product_csvs(prod)
        g["key"] = g["vid"] + "|" + g["zone"]
        g = g.set_index("key")
        for v in vars_:
            gee = pd.concat([g[f"{v}_2023{m:02d}_mean"].rename(m) for m in range(1, 13)], axis=1).stack()
            lc = pd.concat([loc[f"{v}_2023{m:02d}"].rename(m) for m in range(1, 13)], axis=1).stack()
            for zt in ("core", "resource", "all"):
                idx = gee.index if zt == "all" else gee.index[gee.index.get_level_values(0).str.endswith(zt)]
                rows.append(dict(product=prod, variable=v, zone=zt, **compare(gee.loc[idx], lc.reindex(idx), v)))
    return pd.DataFrame(rows)


def chirps_points(points: gpd.GeoDataFrame, years: range, months: list[int]) -> pd.Series:
    """Mean annual CHIRPS sum over `months` at points (nearest cell), from the local grids."""
    xy = list(zip(points.geometry.x, points.geometry.y))
    total = np.zeros(len(points))
    for y in years:
        with rasterio.open(str(GRID["chirps"]).format(y=y)) as r:
            names = list(r.descriptions)
            idx = [names.index(f"precip_{y}{m:02d}") + 1 for m in months]
            vals = np.array([v for v in r.sample(xy, indexes=idx)], dtype="float64")
            total += vals.sum(axis=1)
    return pd.Series(total / len(years), index=points.index)


def check_swai(zones: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v = gpd.read_file(PRIOR / "rhai/sindh_villages.gpkg").to_crs(4326).set_index("village_id")
    rain = pd.read_csv(PRIOR / "swai/village_rainfall_v2.csv").set_index("village_id")["rainfall_mm"]
    dry = pd.read_csv(PRIOR / "swai/village_dryrain.csv").set_index("village_id")["dry_rain_mm"]
    elev = pd.read_csv(PRIOR / "swai/village_elevation_v2.csv").set_index("village_id")["elevation_m"]
    ndvi = pd.read_csv(PRIOR / "swai/village_ndwi.csv").set_index("village_id")["NDVI"]
    rows, pairs = [], []

    def add(name, a, b, method, exact):
        d = pd.concat([a.rename("swai"), b.rename("vista")], axis=1).dropna()
        diff = (d.swai - d.vista).abs()
        rows.append(dict(check=name, method=method, n=len(d), pearson_r=round(pearsonr(d.swai, d.vista)[0], 4),
                         spearman_rho=round(spearmanr(d.swai, d.vista)[0], 4), mae=round(diff.mean(), 3),
                         median_abs_diff=round(diff.median(), 3), mean_bias=round((d.vista - d.swai).mean(), 3),
                         expect="near-identical" if exact else "agreement"))
        pairs.append(d.assign(check=name))

    years = range(2020, 2025)
    add("annual rainfall 2020-24 (mm)", rain, chirps_points(v, years, list(range(1, 13))),
        "local CHIRPS grids at all SWAI points vs SWAI GEE export", True)
    add("dry-season rainfall Nov-May 2020-24 (mm)", dry, chirps_points(v, years, [1, 2, 3, 4, 5, 11, 12]),
        "local CHIRPS grids at all SWAI points vs SWAI GEE export", True)

    # villages inside pilot zones: SRTM elevation (point vs core mean), S2 NDVI 2023 (1 km buffer vs resource)
    res = zones[zones.zone == "resource"][["vid", "geometry"]]
    j = gpd.sjoin(v[["geometry"]], res, predicate="within")
    vid_of = j["vid"]
    ter = product_csvs("terrain_zonal").query("zone == 'core'").set_index("vid")["elev_srtm_mean"]
    s2 = product_csvs("s2_zonal").query("zone == 'resource'").set_index("vid")
    s2_ndvi = s2[[f"ndvi_2023{m:02d}_mean" for m in range(1, 13)]].mean(axis=1)
    add("elevation (m)", elev.loc[vid_of.index], pd.Series(ter.reindex(vid_of.values).values, index=vid_of.index),
        "SWAI SRTM at point vs VISTA SRTM mean over core zone", False)
    add("S2 NDVI 2023", ndvi.loc[vid_of.index], pd.Series(s2_ndvi.reindex(vid_of.values).values, index=vid_of.index),
        "SWAI annual composite in 1 km buffer vs VISTA mean of monthly means over resource zone", False)
    return pd.DataFrame(rows), pd.concat(pairs)


def check_manifest() -> tuple[dict, pd.DataFrame]:
    with (ROOT / "experiments/gee_task_manifest.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    latest = {}
    for r in rows:
        latest[r["description"]] = r
    pilot = {d: r for d, r in latest.items() if "pilot_v0" in d and r["job"] != "upload"}
    done = {d for d, r in pilot.items() if r["state"] in ("SUCCEEDED", "COMPLETED")}
    failed = {d for d, r in pilot.items() if r["state"].startswith("FAILED")}
    local = {Path(p).stem: p for sub in ZDIR.values() for p in glob.glob(str(sub / "*" / "*.csv"))}
    missing_local = sorted(done - set(local))
    untracked = sorted(set(local) - set(pilot))
    retry = [dict(failed_task=d, error=pilot[d]["error"],
                  replaced_by=", ".join(sorted(x for x in done if x.rsplit("_c", 1)[0] == d.rsplit("_c", 1)[0]
                                               and _inside(x, d))))
             for d in sorted(failed)]
    stats = dict(manifest_rows=len(rows), pilot_tasks=len(pilot), pilot_succeeded=len(done),
                 pilot_failed_then_split=len(failed), local_csvs=len(local),
                 succeeded_without_local_file=len(missing_local), local_files_not_in_manifest=len(untracked))
    return stats, pd.DataFrame(retry)


def _inside(child: str, parent: str) -> bool:
    a, b = map(int, child.rsplit("_c", 1)[1].split("-"))
    lo, hi = map(int, parent.rsplit("_c", 1)[1].split("-"))
    return lo <= a <= b <= hi and (a, b) != (lo, hi)


def write_long_store() -> pd.DataFrame:
    out_dir = ROOT / "data/processed/pilot_v0"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for sub in ZDIR.values():
        for d in sorted(sub.glob("*_zonal")):
            lg = to_long(product_csvs(d.name), d.name)
            lg.to_parquet(out_dir / f"{d.name}.parquet", index=False)
            rows.append(dict(product=d.name, rows=len(lg), villages=lg.vid.nunique(), bands=lg.band.nunique(),
                             missing=round(lg.value.isna().mean(), 4)))
    return pd.DataFrame(rows)


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    zones = gpd.read_file(ZONES)
    print("1. local raster check ...")
    local = check_local_rasters(zones)
    local.to_csv(TABLES / "day26_local_raster_check.csv", index=False)
    allz = local[local.zone == "all"]
    ok1 = bool((allz.share_within_tol >= PASS_SHARE).all())
    print("2-3. manifest and retry ...")
    stats, retry = check_manifest()
    retry.to_csv(TABLES / "day26_retry_evidence.csv", index=False)
    ok2 = len(retry) > 0 and (retry.replaced_by != "").all()
    ok3 = stats["succeeded_without_local_file"] == 0 and stats["local_files_not_in_manifest"] == 0
    print("4. SWAI agreement ...")
    swai, pairs = check_swai(zones)
    swai.to_csv(TABLES / "day26_swai_agreement.csv", index=False)
    pairs.to_csv(TABLES / "day26_swai_pairs.csv")
    print("5. long-format store ...")
    store = write_long_store()

    tick = lambda ok: "PASS" if ok else "FAIL"  # noqa: E731
    report = f"""# Day 26 acceptance: GEE zonal-statistics framework

Pilot: zones/pilot_v0, which is 8,245 provisional villages (Mithi, Sanghar, Shah Bunder) and 16,489 core/resource zones.
Generated by `scripts/day26_acceptance.py`.

| checklist item | result |
|---|---|
| Pilot export reproduces a local rasterio check within tolerance | **{tick(ok1)}** |
| Retry logic tested by failure | **{tick(ok2)}** (real failures, see 2) |
| Manifest tracks all tasks | **{tick(ok3)}** |

## 1. Local rasterio check (CHIRPS and ERA5-Land, 2023, 12 months)

The GEE zonal means (`*_zonal`, sampled at 100 m) are compared with exact area-weighted zone means
computed locally from the wave 1 GeoTIFFs: cell polygons are intersected with the zone polygons, with
areas measured in UTM 42N. A product passes when at least {PASS_SHARE:.0%} of zone-months are within tolerance.

{md(local)}

## 2. Retry and recovery

The tasks below failed for real (timeouts on 1,000-village groups). Re-running the wave replaced each one
with smaller chunk groups, and all of those succeeded. A wave 1 GRACE failure was fixed and resubmitted
under the same name.

{md(retry)}

## 3. Manifest audit

{md(pd.DataFrame([stats]))}

## 4. External agreement with SWAI (prior project)

The rainfall rows use identical data (CHIRPS, 2020-24) and must match. The elevation and NDVI rows use
different methods (SWAI: a point or a 1 km buffer, and an annual composite; VISTA: zone means and the
mean of monthly means), so they show agreement rather than identity.

{md(swai)}

## 5. Long-format pilot store (`data/processed/pilot_v0/<product>.parquet`)

{md(store)}
"""
    (ROOT / "documentation/day26_acceptance.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
