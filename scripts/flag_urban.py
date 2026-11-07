"""Day 16 (inventory QC): urban / rural class for every settlement cluster from GHSL SMOD.

    python scripts/flag_urban.py

Input  data/context/ghsl/ghsl_smod_sindh.tif (gee job smod_grid; 1 km Mollweide, bands smod_1975..smod_2030)
       data/village_inventory/settlements/settlements_v0_named.parquet
Output adds columns to settlements_v0_named.parquet in place:
       smod_2000, smod_2010, smod_2020  SMOD L2 code at the cluster's building-weighted centroid
       smod_max_2020                    highest code under the polygon (catches cities whose centroid is in a park)
       settlement_class                 urban_centre | urban_cluster | peri_urban | rural
       in_rural_population              True for clusters the rural models use (D007)
       data/village_inventory/settlements/urban_flag_summary.csv

SMOD L2 codes: 30 urban centre; 23 dense, 22 semi-dense urban cluster; 21 suburban / peri-urban;
13 rural cluster; 12 low-density rural; 11 very low-density rural; 10 water; 0 no data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "data/village_inventory/settlements"
TIF = ROOT / "data/context/ghsl/ghsl_smod_sindh.tif"
MEGA = 5000  # buildings: chained city fabric regardless of SMOD


def main() -> int:
    st = gpd.read_parquet(SET / "settlements_v0_named.parquet")
    with rasterio.open(TIF) as r:
        bands = {d: i + 1 for i, d in enumerate(r.descriptions)}
        pts = gpd.GeoSeries(gpd.points_from_xy(st.lon, st.lat), crs=4326).to_crs(r.crs)
        xy = list(zip(pts.x, pts.y))
        for y in (2000, 2010, 2020):
            st[f"smod_{y}"] = np.array([v[0] for v in r.sample(xy, indexes=bands[f"smod_{y}"])], dtype=np.uint8)
        # highest 2020 code under each polygon: rasterise cluster ids on the 1 km grid (all_touched)
        a = r.read(bands["smod_2020"])
        poly = st.to_crs(r.crs)
        ids = rasterio.features.rasterize(((g, i + 1) for i, g in enumerate(poly.geometry)), out_shape=a.shape,
                                          transform=r.transform, all_touched=True, dtype="int32")
        # rasterize keeps one id per cell; clusters too small to own a cell fall back to the centroid value
        cell_max = pd.Series(a[ids > 0]).groupby(ids[ids > 0] - 1).max()
    st["smod_max_2020"] = np.maximum(st.smod_2020.values, cell_max.reindex(range(len(st))).fillna(0).values).astype(np.uint8)
    c = st.smod_2020
    st["settlement_class"] = np.select(
        [(c == 30) | (st.n_buildings >= MEGA), c.isin([22, 23]), c == 21], ["urban_centre", "urban_cluster",
                                                                            "peri_urban"], "rural")
    st["in_rural_population"] = st.settlement_class.isin(["rural", "peri_urban"])
    st.to_parquet(SET / "settlements_v0_named.parquet")

    summ = st.groupby("settlement_class").agg(clusters=("cluster", "size"), buildings=("n_buildings", "sum"),
                                              median_buildings=("n_buildings", "median")).reset_index()
    summ["building_share"] = (summ.buildings / summ.buildings.sum()).round(3)
    summ.to_csv(SET / "urban_flag_summary.csv", index=False)
    print(summ.to_string(index=False))
    rural = st[st.in_rural_population]
    print(f"rural population: {len(rural):,} hamlets, {rural.village_tier.nunique():,} villages, "
          f"{rural.n_buildings.sum():,} buildings; largest {rural.n_buildings.max():,}")
    moved = st[(st.smod_2000 <= 13) & (st.smod_2020 >= 21)]
    print(f"rural in 2000 -> urban/peri-urban by 2020: {len(moved):,} clusters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
