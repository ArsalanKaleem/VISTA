"""Day 20: records without coordinates, and a coordinate-quality class for every village.

    python scripts/quality_classes.py      (after dedupe_inventory.py)

Records without a settlement cluster (they never get a VID, so they are listed, never forced):
  * named places (OSM / GeoNames) with no hamlet within the matching radius. The GeoNames radius (500 m)
    equals the 95th percentile of GeoNames position error on 2,149 verified pairs (Day 19, p95 = 502 m), so it
    is kept. Each is explained by the Open Buildings count within that radius:
        buildings_1_4 -> settlement below the 5-building minimum
        no_buildings  -> no building detected (abandoned, misplaced point, or missed by Open Buildings)
  * dehs of the Board of Revenue list that no hamlet name matched (Day 17)

Quality class (every VID):
  Q1 corroborated  >= 10 buildings and a name from an independent point source (OSM / GeoNames)
  Q2 robust        >= 10 buildings, mean Open Buildings confidence >= 0.70, no corroborating name
  Q3 weak          5-9 buildings, or mean confidence < 0.70
The 10-building cut is checked against the corroboration rate by size (quality_thresholds.csv): a size bin
where independent sources rarely confirm a settlement is treated as weak.

Outputs
  data/village_inventory/registry/unmatched_records.csv
  data/village_inventory/registry/quality_summary.csv          by district: classes, excluded share
  outputs/tables/day20_quality_thresholds.csv
  registry: quality_class column in place
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
REG = VI / "registry"
TAB = ROOT / "outputs/tables"
CRS = 32642
RADIUS = {"osm": 250, "geonames": 500}
MIN_Q2, CONF_Q2 = 10, 0.70


def main() -> int:
    reg = gpd.read_parquet(REG / "village_registry.parquet")
    if "name_status" not in reg:
        raise SystemExit("run scripts/dedupe_inventory.py first")
    named = reg.name.notna()

    # ---- threshold evidence: corroboration by size and confidence bins
    bins = [5, 7, 10, 15, 25, 50, 100, 10**7]
    reg["size_bin"] = pd.cut(reg.n_buildings, bins, right=False, labels=["5-6", "7-9", "10-14", "15-24", "25-49",
                                                                          "50-99", "100+"])
    reg["conf_bin"] = pd.cut(reg.mean_conf, [0, 0.70, 0.73, 0.76, 0.80, 1.0], labels=["<0.70", "0.70-0.73",
                                                                                      "0.73-0.76", "0.76-0.80", ">=0.80"])
    rural = reg.in_rural_population
    th = pd.concat([
        reg[rural].assign(named=named[rural]).groupby("size_bin", observed=True).agg(
            hamlets=("vid", "size"), corroborated=("named", "mean")).reset_index().rename(columns={"size_bin": "bin"})
        .assign(dimension="n_buildings"),
        reg[rural].assign(named=named[rural]).groupby("conf_bin", observed=True).agg(
            hamlets=("vid", "size"), corroborated=("named", "mean")).reset_index().rename(columns={"conf_bin": "bin"})
        .assign(dimension="mean_conf")])
    th["corroborated"] = th.corroborated.round(3)
    TAB.mkdir(parents=True, exist_ok=True)
    th[["dimension", "bin", "hamlets", "corroborated"]].to_csv(TAB / "day20_quality_thresholds.csv", index=False)
    print(th[["dimension", "bin", "hamlets", "corroborated"]].to_string(index=False))

    # ---- quality classes
    q2_ok = (reg.n_buildings >= MIN_Q2) & (reg.mean_conf >= CONF_Q2)
    reg["quality_class"] = np.select([q2_ok & named, q2_ok], ["Q1", "Q2"], "Q3")
    reg.drop(columns=["size_bin", "conf_bin"]).to_parquet(REG / "village_registry.parquet")

    # ---- unmatched named places, explained by the building count around them
    na = pd.read_parquet(VI / "settlements/names_alt.parquet")
    matched = {("osm", s) for s in na[na.source == "osm"].source_id} | \
              {("geonames", s) for s in na[na.source == "geonames"].source_id}
    osm = gpd.read_parquet(VI / "raw/osm.parquet")
    osm = osm[osm.name.notna() & osm.fclass.isin(["village", "hamlet", "town", "city", "suburb", "locality", "farm",
                                                    "isolated_dwelling"])]
    osm = osm.assign(source="osm", source_id=osm.osm_id.astype(str), place_class=osm.fclass)
    gn = gpd.read_parquet(VI / "raw/geonames.parquet")
    gn = gn.assign(source="geonames", source_id=gn.geonameid.astype(str), place_class=gn.fcode)
    cols = ["source", "source_id", "name", "place_class", "adm3_pcode", "adm3_name", "adm2_name", "geometry"]
    pts = pd.concat([osm[cols], gn[cols]], ignore_index=True)
    pts = gpd.GeoDataFrame(pts, geometry="geometry", crs=4326)
    um = pts[[(s, i) not in matched for s, i in zip(pts.source, pts.source_id)]].to_crs(CRS).reset_index(drop=True)
    fp = pd.read_parquet(VI / "raw/footprints.parquet", columns=["lon", "lat"])
    from pyproj import Transformer
    bx, by = Transformer.from_crs(4326, CRS, always_xy=True).transform(fp.lon.values, fp.lat.values)
    tree = cKDTree(np.c_[bx, by])
    xy = np.c_[um.geometry.x, um.geometry.y]
    rad = um.source.map(RADIUS).values
    um["buildings_within_radius"] = [len(tree.query_ball_point(p, r)) for p, r in zip(xy, rad)]
    hp = reg.to_crs(CRS)
    near = gpd.sjoin_nearest(um[["geometry"]], hp[["vid", "geometry"]], distance_col="d", how="left")
    near = near[~near.index.duplicated()]
    um["nearest_vid"], um["nearest_vid_m"] = near.vid, near.d.round(0)
    um["reason"] = np.where(um.buildings_within_radius == 0, "no_buildings", "buildings_1_4")
    um["record_type"] = "named_place"
    um = pd.DataFrame(um.to_crs(4326).assign(lon=lambda d: d.geometry.x, lat=lambda d: d.geometry.y)
                      .drop(columns="geometry"))
    dehs = pd.read_csv(VI / "deh/bor_dehs.csv")
    anchors = pd.read_csv(VI / "deh/deh_anchors.csv")
    nd = dehs[~dehs.sno.isin(anchors.sno)]
    nd = pd.DataFrame({"record_type": "deh", "source": "bor_deh_list", "source_id": nd.sno.astype(str), "name": nd.deh,
                       "place_class": np.where(nd.under_sea, "deh_under_sea", "deh"), "adm3_pcode": nd.ocha_pcode,
                       "adm2_name": nd.district, "adm3_name": nd.taluka,
                       "reason": np.where(nd.ocha_pcode.isna(), "taluka_not_on_spine", "no_name_match")})
    out = pd.concat([um, nd], ignore_index=True)
    out.to_csv(REG / "unmatched_records.csv", index=False)

    # ---- summary by district
    g = reg.groupby("adm2_name", dropna=False)
    qs = g.quality_class.value_counts().unstack(fill_value=0)
    qs["hamlets"] = qs.sum(axis=1)
    qs["excluded_urban_share"] = g.in_rural_population.apply(lambda s: 1 - s.mean()).round(3)
    rq = reg[reg.in_rural_population].groupby("adm2_name").quality_class.apply(lambda s: (s == "Q3").mean())
    qs["rural_q3_share"] = rq.round(3)
    qs["rural_q12_buildings_share"] = reg[reg.in_rural_population].groupby("adm2_name").apply(
        lambda d: d[d.quality_class != "Q3"].n_buildings.sum() / d.n_buildings.sum(), include_groups=False).round(3)
    qs.reset_index().to_csv(REG / "quality_summary.csv", index=False)

    r = reg[reg.in_rural_population]
    print(reg.quality_class.value_counts().sort_index().to_string())
    print(f"rural: Q1 {int((r.quality_class == 'Q1').sum()):,}, Q2 {int((r.quality_class == 'Q2').sum()):,}, "
          f"Q3 {int((r.quality_class == 'Q3').sum()):,}; Q1-Q2 hold "
          f"{r[r.quality_class != 'Q3'].n_buildings.sum() / r.n_buildings.sum():.1%} of rural buildings")
    print(out.groupby(["record_type", "reason"]).size().to_string())
    return 0 if reg.quality_class.notna().all() else 1


if __name__ == "__main__":
    sys.exit(main())
