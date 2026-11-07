"""Day 18: village registry with persistent, name-independent identifiers, and crosswalks.

    python scripts/build_registry.py

VID (hamlet)   'SD' + OCHA district code (2, from PK7dd) + OCHA tehsil code (3, from PK7ddtt) + H3 res-10 cell of
               the building-weighted centroid + 2-char disambiguator (src/village_mapping/ids.py)
VVID (village tier) 'SV' + same codes + H3 cell of the village tier's building-weighted centroid
Clusters outside every tehsil get codes 99 / 999.

Outputs (data/village_inventory/registry/):
  village_registry.parquet         one row per hamlet: vid, vvid, admin codes and names, deh, name, class flags,
                                   size, geometry (EPSG:4326)
  crosswalks/vid_cluster.csv       vid <-> run-specific cluster id of settlements_v0
  crosswalks/vid_deh.csv           vid -> proxy deh (D008)
  crosswalks/vid_pilot_v0.csv      pilot zone vid (wave 2, geoBoundaries codes) -> registry vid with the largest
                                   overlap; share_of_registry = part of that hamlet inside the pilot core
  registry_summary.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.village_mapping.ids import make_vids  # noqa: E402

VI = ROOT / "data/village_inventory"
REG = VI / "registry"
CRS = 32642


def codes(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    d = df.adm2_pcode.fillna("PK799").str[3:5]
    t = df.adm3_pcode.fillna("PK799999").str[5:7].str.zfill(3)
    return d, t


def main() -> int:
    (REG / "crosswalks").mkdir(parents=True, exist_ok=True)
    st = gpd.read_parquet(VI / "settlements/settlements_v0_named.parquet")
    st = st.sort_values("cluster").reset_index(drop=True)
    st["district_code"], st["taluka_code"] = codes(st)
    st["vid"] = make_vids(list(zip(st.district_code, st.taluka_code, st.lat, st.lon)))

    # village tier: building-weighted centroid of its hamlets; codes from its largest hamlet
    w = st.assign(wx=st.lon * st.n_buildings, wy=st.lat * st.n_buildings)
    vt = w.groupby("village_tier").agg(wx=("wx", "sum"), wy=("wy", "sum"), n=("n_buildings", "sum"))
    big = st.sort_values("n_buildings", ascending=False).drop_duplicates("village_tier").set_index("village_tier")
    vt = vt.join(big[["district_code", "taluka_code"]]).sort_index()
    vt["vvid"] = make_vids(list(zip(vt.district_code, vt.taluka_code, vt.wy / vt.n, vt.wx / vt.n)), prefix="SV")
    st["vvid"] = st.village_tier.map(vt.vvid)

    deh = pd.read_parquet(VI / "deh/deh_assignment.parquet")[["cluster", "deh", "deh_sno", "deh_method"]]
    st = st.merge(deh, on="cluster", how="left")

    keep = ["vid", "vvid", "district_code", "taluka_code", "adm2_pcode", "adm2_name", "adm3_pcode", "adm3_name",
            "deh", "deh_sno", "deh_method", "name", "name_key", "name_source", "name_match", "n_name_candidates",
            "settlement_class", "in_rural_population", "smod_2000", "smod_2010", "smod_2020", "smod_max_2020",
            "n_buildings", "building_area_m2", "mean_conf", "area_m2", "village_tier_buildings",
            "village_tier_hamlets", "lon", "lat", "source", "params", "geometry"]
    reg = gpd.GeoDataFrame(st[keep], geometry="geometry", crs=st.crs)
    reg["registry_version"] = "v0.5"
    reg["id_scheme"] = "SD+OCHA codes+H3r10+2; SV for village tier"
    reg.to_parquet(REG / "village_registry.parquet")
    st[["vid", "cluster"]].to_csv(REG / "crosswalks/vid_cluster.csv", index=False)
    st[["vid", "deh", "deh_sno", "deh_method"]].to_csv(REG / "crosswalks/vid_deh.csv", index=False)

    # pilot zone VIDs (wave 2 data) -> registry VIDs by core-zone overlap
    pz = gpd.read_file(VI / "zones/pilot_zones_v0.geojson")
    core = pz[pz.zone == "core"][["vid", "geometry"]].rename(columns={"vid": "pilot_vid"}).to_crs(CRS)
    core["pilot_area"] = core.area
    # pilot cores are the GEE settlement polygon + 100 m, so the test is how much of the registry hamlet
    # lies inside the core (share_of_registry), not the other way round
    r = reg[["vid", "geometry"]].to_crs(CRS)
    r["reg_area"] = r.area
    ov = gpd.overlay(core, r, how="intersection", keep_geom_type=True)
    ov["share_of_pilot"] = ov.area / ov.pilot_area
    ov["share_of_registry"] = ov.area / ov.reg_area
    best = ov.sort_values("share_of_pilot", ascending=False).drop_duplicates("pilot_vid")
    cw = core[["pilot_vid"]].merge(best[["pilot_vid", "vid", "share_of_pilot", "share_of_registry"]],
                                   on="pilot_vid", how="left")
    cw["share_of_registry"] = cw.share_of_registry.round(3)
    cw["n_registry_overlaps"] = cw.pilot_vid.map(ov.groupby("pilot_vid").size()).fillna(0).astype(int)
    cw["share_of_pilot"] = cw.share_of_pilot.round(3)
    cw.to_csv(REG / "crosswalks/vid_pilot_v0.csv", index=False)

    summ = {"hamlets": len(reg), "unique_vids": reg.vid.nunique(), "villages": reg.vvid.nunique(),
            "rural_hamlets": int(reg.in_rural_population.sum()), "named": int(reg.name.notna().sum()),
            "with_deh": int(reg.deh.notna().sum()), "outside_tehsils": int(reg.adm3_pcode.isna().sum()),
            "pilot_core_zones": len(cw), "pilot_matched": int(cw.vid.notna().sum()),
            "pilot_matched_registry_inside_ge_0_8": int((cw.share_of_registry >= 0.8).sum())}
    pd.DataFrame([summ]).to_csv(REG / "registry_summary.csv", index=False)
    print(pd.Series(summ).to_string())
    return 0 if summ["hamlets"] == summ["unique_vids"] else 1


if __name__ == "__main__":
    sys.exit(main())
