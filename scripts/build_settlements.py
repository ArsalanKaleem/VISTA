"""Days 14-15: settlement clusters from Open Buildings centroids, pilots and province-wide.

    python scripts/build_settlements.py pilot        # local vs GEE provisional polygons (3 pilots)
    python scripts/build_settlements.py sensitivity  # dilate_m x min_buildings grid on the pilots
    python scripts/build_settlements.py province     # all of Sindh -> settlements_v0.parquet
    python scripts/build_settlements.py counts       # per-taluka counts from the saved parquet

Inputs: data/village_inventory/raw/footprints/open_buildings/*.csv (lon, lat, area_m2, confidence,
plus_code; confidence >= 0.65 already applied in Earth Engine). Talukas overlap at their edges, so
buildings are de-duplicated by plus_code before clustering.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.village_mapping.settlements import CRS, Params, cluster  # noqa: E402

OB = ROOT / "data/village_inventory/raw/footprints/open_buildings"
SET = ROOT / "data/village_inventory/settlements"
ADMIN = ROOT / "data/village_inventory/admin"
PBS = ROOT / "data/village_inventory/pbs_sindh_tables"
TAB = ROOT / "outputs/tables"
PILOTS = {"MITHI": "MITHI TALUKA", "SANGHAR": "SANGHAR", "SHAH_BUNDER": "SHAH BUNDER TALUKA"}  # file tag -> PBS name
TO_UTM = Transformer.from_crs(4326, CRS, always_xy=True)


def load(files: list[Path]) -> pd.DataFrame:
    parts = [pd.read_csv(f, usecols=["lon", "lat", "area_m2", "confidence", "plus_code"]) for f in files]
    df = pd.concat(parts, ignore_index=True).drop_duplicates("plus_code", ignore_index=True)
    df["x"], df["y"] = TO_UTM.transform(df.lon.values, df.lat.values)
    return df


def run(df: pd.DataFrame, prm: Params, polygons: bool = True):
    member, cl = cluster(df.x.values, df.y.values, prm, polygons=polygons)
    df = df.assign(cluster=member)
    k = df[df.cluster >= 0]
    extra = k.groupby("cluster").agg(building_area_m2=("area_m2", "sum"), mean_conf=("confidence", "mean"))
    cl = cl.merge(extra, left_on="cluster", right_index=True)
    return df, cl


def pbs_settlements() -> pd.DataFrame:
    """PBS 2020 settlements per OCHA tehsil (crosswalk from Day 12)."""
    cw = pd.read_csv(ADMIN / "taluka_crosswalk.csv")
    t12 = pd.read_csv(PBS / "t1_2_settlements.csv")
    t12 = t12[t12.level == "taluka"][["name", "rural_populated_mouzas", "settlements_total"]]
    return cw.merge(t12, left_on="pbs_taluka", right_on="name", how="left")


def cmd_pilot(_):
    TAB.mkdir(parents=True, exist_ok=True)
    rows = []
    for tag in PILOTS:
        df, cl = run(load([OB / f"open_buildings_{tag}.csv"]), Params())
        gee = gpd.read_file(SET / f"prov_settlements_{tag}.geojson").to_crs(CRS)
        gee["geometry"] = gee.geometry.make_valid()
        lu, gu = cl.union_all(), gee.union_all()
        inter = lu.intersection(gu).area
        # one-to-one: share of GEE polygons whose largest local overlap holds most of its buildings
        j = gpd.sjoin(gee[["n_buildings", "geometry"]], cl[["cluster", "n_buildings", "geometry"]],
                      predicate="intersects", how="left", lsuffix="gee", rsuffix="loc")
        hit = j.groupby(level=0).cluster.nunique()
        rows.append({
            "taluka": tag, "buildings": len(df), "local_clusters": len(cl), "gee_clusters": len(gee),
            "local_buildings_in_clusters": int(cl.n_buildings.sum()),
            "gee_buildings_in_clusters": int(gee.n_buildings.sum()),
            "local_area_km2": round(lu.area / 1e6, 2), "gee_area_km2": round(gu.area / 1e6, 2),
            "area_iou": round(inter / lu.union(gu).area, 3),
            "gee_clusters_with_1_local": int((hit == 1).sum()),
            "gee_clusters_with_0_local": int((hit == 0).sum()),
            "gee_clusters_split_into_2plus": int((hit >= 2).sum()),
        })
        print(rows[-1])
    out = pd.DataFrame(rows)
    out.to_csv(TAB / "day14_local_vs_gee.csv", index=False)
    print(out.to_string(index=False))


def cmd_sensitivity(_):
    TAB.mkdir(parents=True, exist_ok=True)
    pbs = pbs_settlements().set_index("ocha_adm3_pcode")
    o3 = gpd.read_file(ADMIN / "admin_boundaries.gpkg", layer="ocha_adm3").to_crs(CRS).set_index("adm3_pcode")
    rows = []
    for tag, pbs_name in PILOTS.items():
        pcode = pbs.index[pbs.pbs_taluka == pbs_name][0]
        # PBS counts refer to the OCHA tehsil: cluster only buildings inside it (seams cut, as in PBS)
        df = load([OB / f"open_buildings_{tag}.csv"])
        inside = gpd.GeoSeries(gpd.points_from_xy(df.x, df.y), crs=CRS).within(o3.loc[pcode].geometry)
        df = df[inside.values].reset_index(drop=True)
        p = pbs.loc[pcode]
        for d in (20, 40, 60, 100, 150, 250):
            t = time.time()
            # components do not depend on min_buildings: cluster once, then filter
            _, all_cl = run(df, Params(dilate_m=d, min_buildings=1), polygons=False)
            for mb in (3, 5, 10, 20, 50):
                cl = all_cl[all_cl.n_buildings >= mb]
                rows.append({"taluka": tag, "ocha_pcode": pcode, "dilate_m": d, "min_buildings": mb,
                             "buildings": len(df), "clusters": len(cl),
                             "share_buildings_clustered": round(cl.n_buildings.sum() / len(df), 3),
                             "median_buildings": float(cl.n_buildings.median()) if len(cl) else 0,
                             "pbs_settlements": p.settlements_total, "pbs_mouzas": p.rural_populated_mouzas,
                             "ratio_to_pbs": round(len(cl) / p.settlements_total, 2), "sec": round(time.time() - t, 1)})
        print(tag, "done")
    out = pd.DataFrame(rows)
    out.to_csv(TAB / "day14_parameter_sensitivity.csv", index=False)
    print(out.pivot_table(index=["dilate_m"], columns=["taluka", "min_buildings"], values="ratio_to_pbs").to_string())


def per_taluka(cl: pd.DataFrame) -> pd.DataFrame:
    """Counts per OCHA tehsil vs PBS 2020. Clusters outside every tehsil are one 'outside' row."""
    per = cl.assign(adm3_pcode=cl.adm3_pcode.fillna("outside")).groupby(
        ["adm2_name", "adm3_pcode", "adm3_name"], dropna=False).agg(
        clusters=("cluster", "size"), villages=("village_tier", "nunique"), buildings=("n_buildings", "sum"),
        median_buildings=("n_buildings", "median"), largest_cluster=("n_buildings", "max"),
        area_km2=("area_m2", lambda a: a.sum() / 1e6)).reset_index()
    pbs = pbs_settlements()
    pbs = pbs[pbs.ocha_adm3_pcode.notna()][["ocha_adm3_pcode", "pbs_taluka", "settlements_total",
                                            "rural_populated_mouzas"]]
    per = per.merge(pbs, left_on="adm3_pcode", right_on="ocha_adm3_pcode", how="left").drop(columns="ocha_adm3_pcode")
    per["ratio_to_pbs"] = (per.clusters / per.settlements_total).round(2)
    per["village_ratio_to_pbs"] = (per.villages / per.settlements_total).round(2)
    per.round(3).to_csv(SET / "settlement_counts_by_taluka.csv", index=False)
    return per


def cmd_counts(_):
    cl = gpd.read_parquet(SET / "settlements_v0.parquet").to_crs(CRS)
    per = per_taluka(cl)
    r = per[per.settlements_total.notna()]
    print(f"{len(per)} rows; clusters {per.clusters.sum():,}, villages {cl.village_tier.nunique():,}, "
          f"buildings {per.buildings.sum():,}; PBS settlements matched {r.settlements_total.sum():,.0f}")
    print(r[["ratio_to_pbs", "village_ratio_to_pbs"]].describe().round(2).to_string())


def cmd_province(args):
    t0 = time.time()
    files = sorted(OB.glob("open_buildings_*.csv"))
    df = load(files)
    print(f"{len(files)} files, {len(df):,} unique buildings ({time.time() - t0:.0f} s)")
    prm = Params(dilate_m=args.dilate_m, min_buildings=args.min_buildings)
    df, cl = run(df, prm, polygons=True)
    print(f"{len(cl):,} clusters >= {prm.min_buildings} buildings ({time.time() - t0:.0f} s)")
    # village tier (Day 14 two-tier definition): hamlets merged at a wider dilation. A hamlet is
    # connected at 40 m, hence at any wider dilation, so all its buildings share one village id.
    vmember, _ = cluster(df.x.values, df.y.values, Params(dilate_m=args.village_dilate_m, min_buildings=1),
                         polygons=False)
    hv = pd.Series(vmember).groupby(df.cluster.values).first().drop(-1, errors="ignore")
    cl["village_tier"] = cl.cluster.map(hv)
    vsize = cl.groupby("village_tier").n_buildings.transform("sum")
    cl["village_tier"] = pd.factorize(cl.village_tier, sort=True)[0]
    cl["village_tier_buildings"] = vsize
    cl["village_tier_hamlets"] = cl.groupby("village_tier").cluster.transform("size")
    print(f"village tier ({args.village_dilate_m:g} m): {cl.village_tier.nunique():,} villages")
    # admin attributes from the OCHA spine, by cluster centroid (building-weighted)
    o3 = gpd.read_file(ADMIN / "admin_boundaries.gpkg", layer="ocha_adm3").to_crs(CRS)
    pts = gpd.GeoDataFrame(cl[["cluster"]], geometry=gpd.points_from_xy(cl.x, cl.y), crs=CRS)
    j = gpd.sjoin(pts, o3[["adm3_pcode", "adm3_name", "adm2_pcode", "adm2_name", "geometry"]],
                  predicate="within", how="left").drop_duplicates("cluster")
    cl = cl.merge(j.drop(columns=["geometry", "index_right"]), on="cluster", how="left")
    cl["area_m2"] = cl.geometry.area.round(1)
    cl["lon"], cl["lat"] = Transformer.from_crs(CRS, 4326, always_xy=True).transform(cl.x.values, cl.y.values)
    cl["source"] = "open_buildings_v3"
    cl["params"] = f"dilate_m={prm.dilate_m};min_buildings={prm.min_buildings};scale_m={prm.scale_m};points=centroid"
    # topology QC
    bad = ~cl.is_valid
    qc = {"clusters": len(cl), "invalid_before_repair": int(bad.sum())}
    if bad.any():
        cl.loc[bad, "geometry"] = cl.loc[bad, "geometry"].make_valid()
    qc.update(invalid_after=int((~cl.is_valid).sum()), empty=int(cl.geometry.is_empty.sum()),
              outside_sindh=int(cl.adm3_pcode.isna().sum()),
              buildings_total=len(df), buildings_in_clusters=int(cl.n_buildings.sum()))
    # overlap check on a spatial index: clusters must be disjoint by construction
    sj = gpd.sjoin(cl[["cluster", "geometry"]], cl[["cluster", "geometry"]], predicate="overlaps")
    qc["overlapping_pairs"] = int((sj.cluster_left != sj.cluster_right).sum() // 2)
    out = SET / "settlements_v0.parquet"
    cl.drop(columns=["x", "y"]).to_crs(4326).to_parquet(out)
    pd.DataFrame([qc]).to_csv(SET / "qc_topology.csv", index=False)
    per_taluka(cl)
    print(pd.DataFrame([qc]).T.to_string())
    print(f"wrote {out} ({out.stat().st_size / 2**20:.0f} MB) in {time.time() - t0:.0f} s")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pilot")
    sub.add_parser("sensitivity")
    sub.add_parser("counts")
    p = sub.add_parser("province")
    p.add_argument("--dilate-m", type=float, default=40.0)
    p.add_argument("--min-buildings", type=int, default=5)
    p.add_argument("--village-dilate-m", type=float, default=150.0)
    args = ap.parse_args()
    {"pilot": cmd_pilot, "sensitivity": cmd_sensitivity, "province": cmd_province, "counts": cmd_counts}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
