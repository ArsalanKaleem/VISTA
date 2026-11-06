"""Day 13: settlement-evidence layers as Parquet and their coverage per taluka against PBS 2020.

    python scripts/settlement_sources.py

Writes
    data/village_inventory/raw/osm.parquet          OSM place points (Geofabrik 2026-07-12) inside Sindh
    data/village_inventory/raw/geonames.parquet     GeoNames populated places (feature class P) inside Sindh
    data/village_inventory/raw/footprints.parquet   Open Buildings v3 centroids, de-duplicated by plus_code
    data/village_inventory/source_coverage_by_taluka.csv
    documentation/licences_settlement_sources.md
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
RAW = VI / "raw"
OSM = ROOT / "data/raw/osm/geofabrik_pakistan_260712_shp/gis_osm_places_free_1.shp"
GN = ROOT / "data/raw/geonames/PK.zip"
OB = RAW / "footprints/open_buildings"
GN_COLS = ["geonameid", "name", "asciiname", "alternatenames", "lat", "lon", "fclass", "fcode", "cc", "cc2",
           "admin1", "admin2", "admin3", "admin4", "population", "elevation", "dem", "tz", "modified"]
RURAL_OSM = ["village", "hamlet", "isolated_dwelling", "farm", "locality"]

LICENCES = """# Licences of the settlement-evidence layers (Day 13)

| layer | source | licence | attribution |
|---|---|---|---|
| osm.parquet | OpenStreetMap via Geofabrik extract pakistan-260712 | ODbL 1.0 | (c) OpenStreetMap contributors |
| geonames.parquet | GeoNames PK dump | CC BY 4.0 | GeoNames, geonames.org |
| footprints.parquet | Google Open Buildings v3 (Earth Engine GOOGLE/Research/open-buildings/v3/polygons) | CC BY 4.0 and ODbL 1.0 (dual) | Google Open Buildings |
| admin spine | OCHA COD-AB Pakistan (HDX, valid 2022-09-09) | CC BY-IGO | OCHA / Survey of Pakistan |
| PBS tables | PBS Mouza Census 2020, Sindh report | public statistics | Pakistan Bureau of Statistics |
"""


def main() -> int:
    o3 = gpd.read_file(VI / "admin/admin_boundaries.gpkg", layer="ocha_adm3")
    sindh = o3[["adm3_pcode", "adm3_name", "adm2_name", "geometry"]]

    osm = gpd.read_file(OSM)
    osm = gpd.sjoin(osm.to_crs(4326), sindh, predicate="within").drop(columns="index_right")
    osm.to_parquet(RAW / "osm.parquet")

    with zipfile.ZipFile(GN) as z:
        gn = pd.read_csv(z.open("PK.txt"), sep="\t", header=None, names=GN_COLS, dtype={"admin1": str},
                         keep_default_na=False, na_values=[""], low_memory=False)
    gn = gn[gn.fclass == "P"]
    gn = gpd.GeoDataFrame(gn, geometry=gpd.points_from_xy(gn.lon, gn.lat), crs=4326)
    gn = gpd.sjoin(gn, sindh, predicate="within").drop(columns="index_right")
    gn.to_parquet(RAW / "geonames.parquet")

    files = sorted(OB.glob("open_buildings_*.csv"))
    ob = pd.concat([pd.read_csv(f, usecols=["lon", "lat", "area_m2", "confidence", "plus_code"]) for f in files],
                   ignore_index=True).drop_duplicates("plus_code", ignore_index=True)
    ob = gpd.GeoDataFrame(ob, geometry=gpd.points_from_xy(ob.lon, ob.lat), crs=4326)
    ob = gpd.sjoin(ob, sindh[["adm3_pcode", "geometry"]], predicate="within", how="left").drop(columns="index_right")
    ob = ob.drop_duplicates("plus_code")
    ob.to_parquet(RAW / "footprints.parquet")

    cov = sindh.drop(columns="geometry").copy()
    cov["osm_places"] = cov.adm3_pcode.map(osm.groupby("adm3_pcode").size()).fillna(0).astype(int)
    cov["osm_rural_places"] = cov.adm3_pcode.map(
        osm[osm.fclass.isin(RURAL_OSM)].groupby("adm3_pcode").size()).fillna(0).astype(int)
    cov["osm_named"] = cov.adm3_pcode.map(osm[osm.name.notna()].groupby("adm3_pcode").size()).fillna(0).astype(int)
    cov["geonames_places"] = cov.adm3_pcode.map(gn.groupby("adm3_pcode").size()).fillna(0).astype(int)
    cov["buildings"] = cov.adm3_pcode.map(ob.groupby("adm3_pcode").size()).fillna(0).astype(int)
    cw = pd.read_csv(VI / "admin/taluka_crosswalk.csv")
    t12 = pd.read_csv(VI / "pbs_sindh_tables/t1_2_settlements.csv")
    t12 = t12[t12.level == "taluka"][["name", "rural_populated_mouzas", "settlements_total"]]
    pbs = cw[["ocha_adm3_pcode", "pbs_taluka"]].merge(t12, left_on="pbs_taluka", right_on="name", how="left")
    cov = cov.merge(pbs.drop(columns="name"), left_on="adm3_pcode", right_on="ocha_adm3_pcode", how="left") \
        .drop(columns="ocha_adm3_pcode").rename(columns={"settlements_total": "pbs_settlements",
                                                          "rural_populated_mouzas": "pbs_mouzas"})
    for c in ("osm_rural_places", "geonames_places"):
        cov[f"{c}_per_pbs"] = (cov[c] / cov.pbs_settlements).round(2)
    cov.to_csv(VI / "source_coverage_by_taluka.csv", index=False)
    (ROOT / "documentation/licences_settlement_sources.md").write_text(LICENCES, encoding="utf-8")

    print(f"OSM places {len(osm):,} ({osm.fclass.value_counts().to_dict()})")
    print(f"GeoNames P {len(gn):,}; buildings {len(ob):,} (outside tehsils {int(ob.adm3_pcode.isna().sum()):,})")
    rural = cov[cov.pbs_settlements.notna()]
    print(f"talukas with PBS settlements: {len(rural)}; with 0 buildings: {int((cov.buildings == 0).sum())}")
    print(rural[["osm_rural_places_per_pbs", "geonames_places_per_pbs"]].describe().round(2).to_string())
    print("Sindh totals:", rural[["pbs_settlements", "osm_rural_places", "geonames_places", "buildings"]].sum().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
