"""Day 19: duplicate detection and resolution for the village registry.

    python scripts/dedupe_inventory.py

Three kinds of duplicate are checked:

D1 duplicated detections: the same building twice. Hamlets are disjoint by construction (one clustering of
   de-duplicated plus_codes), so the remaining risk is the same building listed twice under different
   plus_codes. Checked by building pairs closer than 1 m, per tehsil.
D2 duplicated name records: several OSM / GeoNames records of one place on one hamlet (same name key).
   They are merged into one name entity (rule R1).
D3 duplicated names across hamlets in one tehsil (same name key):
   R2 all hamlets in one village tier             -> hamlets of one village; the name becomes the village name
   R3 different village tiers, nearest pair <= D  -> one place named twice (a GeoNames point snapped to the
                                                     wrong hamlet): the name stays on the best-supported hamlet
                                                     (OSM inside > GeoNames inside > near; then most buildings)
                                                     and is dropped from the others
   R4 different village tiers, all pairs > D      -> homonyms (common names such as Mirpur): all kept
D is not guessed: it is the 95th percentile of GeoNames position error, measured on verified pairs
(a hamlet named by an OSM point inside it, and a GeoNames point with the same key in the same tehsil).

Outputs
  data/village_inventory/registry/merge_log.csv           every merge / drop / keep decision with its rule
  data/village_inventory/registry/review_sample.csv       300 stratified decisions for manual review (blank
                                                          'reviewer_verdict' column)
  outputs/tables/day19_geonames_position_error.csv        verified pairs and distances (also used on Day 20)
  outputs/tables/day19_duplicate_summary.csv
  registry: name_status, village_name columns added in place; registry_version v0.6
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from attach_names import latin_part, name_key  # noqa: E402

VI = ROOT / "data/village_inventory"
REG = VI / "registry"
TAB = ROOT / "outputs/tables"
CRS = 32642
SRC_RANK = {("osm", "inside"): 0, ("geonames", "inside"): 1, ("osm", "near"): 2, ("geonames", "near"): 3}


def position_error(reg: gpd.GeoDataFrame, names: pd.DataFrame) -> pd.DataFrame:
    """Distance from GeoNames points to the hamlet that an OSM point inside it names with the same key."""
    osm_in = names[(names.source == "osm") & (names.match == "inside") & names.name_key.notna()]
    osm_in = osm_in.drop_duplicates(["vid", "name_key"]).merge(reg[["vid", "adm3_pcode"]], on="vid")
    gn = gpd.read_parquet(VI / "raw/geonames.parquet").to_crs(CRS)
    gn["name_key"] = gn.name.map(latin_part).map(name_key)
    gn = gn[gn.name_key.notna()]
    poly = reg.set_index("vid").geometry
    rows = []
    for (pcode, k), o in osm_in.groupby(["adm3_pcode", "name_key"]):
        if len(o) != 1:
            continue  # ambiguous: the same key on two OSM-named hamlets
        cand = gn[(gn.adm3_pcode == pcode) & (gn.name_key == k)]
        if cand.empty:
            continue
        h = poly.loc[o.vid.iloc[0]]
        d = cand.distance(h)
        rows.append({"vid": o.vid.iloc[0], "adm3_pcode": pcode, "name_key": k, "geonameid": cand.geonameid.loc[d.idxmin()],
                     "distance_m": round(float(d.min()), 1), "n_geonames_same_key": len(cand)})
    return pd.DataFrame(rows)


def building_duplicates() -> dict:
    fp = pd.read_parquet(VI / "raw/footprints.parquet", columns=["lon", "lat", "adm3_pcode"])
    from pyproj import Transformer
    x, y = Transformer.from_crs(4326, CRS, always_xy=True).transform(fp.lon.values, fp.lat.values)
    fp["x"], fp["y"] = x, y
    pairs = 0
    for _, g in fp.groupby(fp.adm3_pcode.fillna("none")):
        pairs += len(cKDTree(g[["x", "y"]].values).query_pairs(1.0))
    return {"buildings": len(fp), "pairs_within_1m": pairs}


def main() -> int:
    reg = gpd.read_parquet(REG / "village_registry.parquet").to_crs(CRS)
    cw = pd.read_csv(REG / "crosswalks/vid_cluster.csv")
    names = pd.read_parquet(VI / "settlements/names_alt.parquet").merge(cw, on="cluster")
    names = names[names.source != "geonames_alt"]

    # ---- D = 95th percentile GeoNames position error on verified pairs
    pe = position_error(reg, names)
    pe = pe[pe.distance_m <= 10_000]  # beyond 10 km it is another place with the same name
    TAB.mkdir(parents=True, exist_ok=True)
    pe.to_csv(TAB / "day19_geonames_position_error.csv", index=False)
    D = float(np.ceil(np.percentile(pe.distance_m, 95) / 100) * 100)
    print(f"verified pairs {len(pe):,}: GeoNames error median {pe.distance_m.median():.0f} m, "
          f"p90 {np.percentile(pe.distance_m, 90):.0f} m, p95 {np.percentile(pe.distance_m, 95):.0f} m -> D = {D:.0f} m")

    log = []
    # ---- D1 building duplicates
    bd = building_duplicates()
    print(f"D1: {bd['pairs_within_1m']:,} building pairs within 1 m among {bd['buildings']:,}")

    # ---- D2 name records on one hamlet with the same key
    nk = names[names.name_key.notna()]
    rec = nk.groupby(["vid", "name_key"]).agg(n=("source_id", "nunique"), ids=("source_id", lambda s: ";".join(sorted(set(s)))),
                                              sources=("source", lambda s: ";".join(sorted(set(s))))).reset_index()
    for r in rec[rec.n > 1].itertuples():
        log.append({"rule": "R1_record_merge", "name_key": r.name_key, "vids": r.vid, "records": r.ids,
                    "sources": r.sources, "decision": "merged into one name entity", "distance_m": 0.0})
    print(f"D2: {int((rec.n > 1).sum()):,} hamlets with duplicated name records merged")

    # ---- D3 same key on several hamlets of one tehsil
    best = nk.copy()
    best["rank"] = [SRC_RANK.get((s, m), 9) for s, m in zip(best.source, best.match)]
    best = best.sort_values(["vid", "name_key", "rank"]).drop_duplicates(["vid", "name_key"])
    prim = reg[reg.name_key.notna()][["vid", "vvid", "adm3_pcode", "name", "name_key", "n_buildings", "geometry"]]
    prim = prim.merge(best[["vid", "name_key", "rank"]], on=["vid", "name_key"], how="left")
    prim["rank"] = prim["rank"].fillna(9)
    reg["name_status"] = np.where(reg.name.notna(), "unique", "unnamed")  # Arabic-only names have no key
    reg["village_name"] = None
    groups = prim.groupby(["adm3_pcode", "name_key"])
    for (pcode, k), g in groups:
        if len(g) < 2:
            continue
        vids = ";".join(g.vid)
        if g.vvid.nunique() == 1:
            log.append({"rule": "R2_same_village", "name_key": k, "vids": vids, "decision": "village name",
                        "distance_m": 0.0})
            reg.loc[reg.vid.isin(g.vid), "name_status"] = "village_shared"
            continue
        geoms = gpd.GeoSeries(g.geometry.values, crs=CRS)
        dmat = np.array([[a.distance(b) for b in geoms] for a in geoms])
        np.fill_diagonal(dmat, np.inf)
        # connected components of hamlets closer than D (distinct village tiers)
        comp = list(range(len(g)))
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                if dmat[i, j] <= D:
                    a, b = comp[i], comp[j]
                    comp = [a if c == b else c for c in comp]
        g = g.assign(comp=comp, near=dmat.min(axis=1))
        for c, cg in g.groupby("comp"):
            if len(cg) == 1:
                reg.loc[reg.vid == cg.vid.iloc[0], "name_status"] = "homonym"
                continue
            keep = cg.sort_values(["rank", "n_buildings"], ascending=[True, False]).iloc[0]
            drop = cg[cg.vid != keep.vid]
            log.append({"rule": "R3_name_conflict", "name_key": k, "vids": ";".join(cg.vid), "kept": keep.vid,
                        "dropped": ";".join(drop.vid), "decision": "name kept on best-supported hamlet",
                        "distance_m": round(float(cg.near.min()), 1)})
            reg.loc[reg.vid == keep.vid, "name_status"] = "conflict_kept"
            reg.loc[reg.vid.isin(drop.vid), "name_status"] = "conflict_dropped"
        if g.comp.nunique() > 1:
            log.append({"rule": "R4_homonym", "name_key": k, "vids": vids, "decision": "distinct places kept",
                        "distance_m": round(float(np.min([d for d in dmat.ravel() if np.isfinite(d)] or [0])), 1)})

    # names dropped by R3 move to alternates; village tier name = name of its largest named hamlet
    drop = reg.name_status == "conflict_dropped"
    reg.loc[drop, ["name", "name_key", "name_latin"]] = None
    nm = reg[reg.name.notna()].sort_values("n_buildings", ascending=False).drop_duplicates("vvid").set_index("vvid")
    reg["village_name"] = reg.vvid.map(nm.name)
    reg["registry_version"] = "v0.6"
    reg.to_crs(4326).to_parquet(REG / "village_registry.parquet")

    ml = pd.DataFrame(log)
    ml.insert(0, "merge_id", [f"M{i:05d}" for i in range(1, len(ml) + 1)])
    ml.to_csv(REG / "merge_log.csv", index=False)
    # stratified review sample of 300 decisions: every R3 conflict, then R2 / R4, filled up with R1 merges
    rng = np.random.default_rng(19)
    quota = {"R3_name_conflict": 120, "R2_same_village": 80, "R4_homonym": 80}
    parts, used = [], set()
    for rule, n in quota.items():
        s_ = ml[ml.rule == rule]
        take = s_.iloc[rng.choice(len(s_), size=min(n, len(s_)), replace=False)] if len(s_) else s_
        parts.append(take)
        used |= set(take.merge_id)
    rest = ml[(ml.rule == "R1_record_merge") & ~ml.merge_id.isin(used)]
    need = 300 - sum(len(x) for x in parts)
    parts.append(rest.iloc[rng.choice(len(rest), size=min(need, len(rest)), replace=False)])
    rs = pd.concat(parts).assign(reviewer_verdict="", reviewer_note="")
    rs.to_csv(REG / "review_sample.csv", index=False)

    summ = ml.rule.value_counts().rename_axis("rule").reset_index(name="decisions")
    summ.loc[len(summ)] = ["D1_building_pairs_within_1m", bd["pairs_within_1m"]]
    summ.loc[len(summ)] = ["D_threshold_m", D]
    summ.to_csv(TAB / "day19_duplicate_summary.csv", index=False)
    print(summ.to_string(index=False))
    print(reg.name_status.value_counts().to_string())
    print(f"villages with a name: {reg.drop_duplicates('vvid').village_name.notna().mean():.1%}; "
          f"review sample {len(rs)} rows; VIDs unique: {reg.vid.is_unique}")
    return 0 if reg.vid.is_unique else 1


if __name__ == "__main__":
    sys.exit(main())
