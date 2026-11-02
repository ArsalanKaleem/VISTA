"""Build core/resource zones from settlement polygons and write an upload-ready file.

Pilot use (tomorrow): settlement polygons from the `provisional_settlements` GEE job
(Drive folder vista_gee_settlements, prov_settlements_*.geojson) ->
    python scripts/make_zones.py data/village_inventory/settlements/prov_settlements_*.geojson \
        --out data/village_inventory/zones/pilot_zones_v0.geojson
Production (Day 23): the frozen settlements_v1 GeoParquet with VIDs.

r_max: 2 km by default and 4 km for Thar desert talukas (Section 5.6; Day 44 tests it).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.village_mapping.ids import make_vids  # noqa: E402
from src.village_mapping.zones import make_zones, zones_long  # noqa: E402

DESERT_TALUKAS = {"MITHI", "CHACHRO", "DIPLO", "NAGAR PARKAR", "UMER KOT", "SAMARO", "KUNRI"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--r-max", type=float, default=2000.0)
    ap.add_argument("--r-max-desert", type=float, default=4000.0)
    ap.add_argument("--core-buf", type=float, default=100.0)
    args = ap.parse_args()

    admin = ROOT / "data" / "village_inventory" / "admin"
    talukas = gpd.read_file(admin / "sindh_adm3.geojson")
    districts = gpd.read_file(admin / "sindh_adm2.geojson")
    talukas["taluka_code"] = [f"{i:03d}" for i in range(len(talukas))]
    districts["district_code"] = [f"{i:02d}" for i in range(len(districts))]

    settl = gpd.GeoDataFrame(pd.concat([gpd.read_file(p) for p in args.inputs], ignore_index=True), crs=4326)
    cent = settl.copy()
    cent["geometry"] = settl.to_crs(32642).centroid.to_crs(4326)
    cent = cent.sjoin(talukas[["shapeName", "taluka_code", "geometry"]].rename(columns={"shapeName": "taluka_name"}),
                      how="left", predicate="within").drop(columns="index_right")
    cent = cent.sjoin(districts[["district_code", "geometry"]], how="left", predicate="within").drop(columns="index_right")
    settl["taluka_name"] = cent["taluka_name"].values
    settl["vid"] = make_vids(list(zip(cent["district_code"].fillna("99"), cent["taluka_code"].fillna("999"),
                                      cent.geometry.y, cent.geometry.x)))

    parts = []
    for tname, grp in settl.groupby("taluka_name"):
        r_max = args.r_max_desert if str(tname).upper() in DESERT_TALUKAS else args.r_max
        z = make_zones(grp, talukas[talukas.shapeName == tname], r_max=r_max, core_buf=args.core_buf)
        parts.append(zones_long(z))
        print(f"  {tname}: {len(grp)} settlements, r_max {r_max:.0f} m")
    zones = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=32642)
    # Voronoi clipping leaves a few self-touching rings; repair before the EE upload
    zones["geometry"] = zones.geometry.make_valid().buffer(0)
    zones = zones[~zones.geometry.is_empty].to_crs(4326)
    zones["geometry"] = zones.geometry.make_valid().buffer(0)  # again: reprojection can re-break rings
    args.out.parent.mkdir(parents=True, exist_ok=True)
    zones.to_file(args.out, driver="GeoJSON")
    print(f"wrote {args.out} ({len(zones)} zone features)")
    print(zones.groupby("zone")["area_m2"].describe().round(0))


if __name__ == "__main__":
    main()
