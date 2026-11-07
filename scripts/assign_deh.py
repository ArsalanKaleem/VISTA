"""Day 17: deh assignment without deh polygons (plan fallback), anchored on official deh names.

    python scripts/assign_deh.py

No deh boundary file is public (the Board of Revenue shows scanned sheets only; the PBS record request of
2026-11-07 may not be answered). The fallback has three steps:
  1. Geolocate dehs: a deh named in the BoR list (data/village_inventory/deh/bor_dehs.csv) is anchored on a
     named hamlet in the same OCHA tehsil whose name key equals the deh key, or is very close to it
     (difflib ratio >= 0.88, both keys >= 4 letters). Several candidates: the hamlet with most buildings
     (a deh is usually named after its main village).
  2. Proxy deh polygons: Voronoi cells of the anchors, clipped to the tehsil (EPSG:32642).
  3. Every hamlet gets the proxy deh whose cell contains its centroid. Tehsils with no anchor get no deh.
The proxy polygons are aggregation units with official names, NOT surveyed deh boundaries.

Outputs (data/village_inventory/deh/):
  deh_anchors.csv          deh -> anchor hamlet, match type, ratio
  deh_proxy.parquet        proxy deh polygons (GeoParquet, EPSG:4326)
  deh_assignment.parquet   cluster -> deh, method
  coverage_table.csv       per district: dehs listed / geolocated, hamlets and buildings assigned
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
DEH = VI / "deh"
CRS = 32642
MIN_RATIO = 0.88


def main() -> int:
    dehs = pd.read_csv(DEH / "bor_dehs.csv")
    dehs = dehs[dehs.ocha_pcode.notna() & ~dehs.under_sea].copy()
    dehs["deh_key"] = dehs.deh.str.lower().str.replace(r"[^a-z]", "", regex=True)
    st = gpd.read_parquet(VI / "settlements/settlements_v0_named.parquet").to_crs(CRS)
    names = pd.read_parquet(VI / "settlements/names_alt.parquet")
    names = names[names.name_key.notna() & (names.name_key.str.len() >= 3)]
    names = names.merge(st[["cluster", "adm3_pcode", "n_buildings"]], on="cluster")

    anchors = []
    for pcode, dg in dehs.groupby("ocha_pcode"):
        nk = names[names.adm3_pcode == pcode]
        if nk.empty:
            continue
        by_key = nk.groupby("name_key")
        keys = list(by_key.groups)
        taken: set = set()
        for _, d in dg.iterrows():
            k = d.deh_key
            hit, how, ratio = None, None, 1.0
            if k in by_key.groups:
                hit, how = by_key.get_group(k), "exact"
            elif len(k) >= 4:
                close = difflib.get_close_matches(k, [x for x in keys if len(x) >= 4], n=3, cutoff=MIN_RATIO)
                if close:
                    hit = nk[nk.name_key.isin(close)]
                    how = "fuzzy"
                    ratio = max(difflib.SequenceMatcher(None, k, c).ratio() for c in close)
            if hit is None:
                continue
            best = hit.sort_values("n_buildings", ascending=False)
            best = best[~best.cluster.isin(taken)]  # one anchor hamlet per deh
            if best.empty:
                continue
            b = best.iloc[0]
            taken.add(b.cluster)
            anchors.append({"ocha_pcode": pcode, "district": d.district, "taluka": d.taluka, "deh": d.deh,
                            "deh_key": k, "sno": d.sno, "cluster": int(b.cluster), "anchor_name": b.name_raw,
                            "anchor_source": b.source, "match": how, "ratio": round(ratio, 3)})
    an = pd.DataFrame(anchors)
    an.to_csv(DEH / "deh_anchors.csv", index=False)

    o3 = gpd.read_file(VI / "admin/admin_boundaries.gpkg", layer="ocha_adm3").to_crs(CRS).set_index("adm3_pcode")
    cent = st.set_index("cluster")
    pts = gpd.points_from_xy(st.lon, st.lat, crs=4326).to_crs(CRS)
    st["pt"] = pts
    polys, assign = [], []
    for pcode, ag in an.groupby("ocha_pcode"):
        teh = o3.loc[pcode].geometry
        a_pts = shapely.points([cent.loc[c].geometry.representative_point().coords[0] for c in ag.cluster])
        if len(ag) == 1:
            cells = [teh]
        else:
            vor = shapely.voronoi_polygons(shapely.MultiPoint(list(a_pts)), extend_to=teh.envelope.buffer(10_000))
            cells_raw = list(vor.geoms)
            # voronoi cells come in arbitrary order: map each back to its anchor point
            cells = [next(c for c in cells_raw if c.contains(p)).intersection(teh) for p in a_pts]
        g = gpd.GeoDataFrame(ag.reset_index(drop=True), geometry=cells, crs=CRS)
        polys.append(g)
        members = st[st.adm3_pcode == pcode]
        j = gpd.sjoin(gpd.GeoDataFrame(members[["cluster"]], geometry=members.pt.values, crs=CRS),
                      g[["deh", "sno", "geometry"]], predicate="within", how="left")
        assign.append(j.drop(columns=["geometry", "index_right"]).drop_duplicates("cluster"))
    proxy = pd.concat(polys, ignore_index=True)
    proxy = gpd.GeoDataFrame(proxy, geometry="geometry", crs=CRS)
    proxy["area_km2"] = (proxy.area / 1e6).round(2)
    proxy.to_crs(4326).to_parquet(DEH / "deh_proxy.parquet")
    asg = pd.concat(assign, ignore_index=True).rename(columns={"sno": "deh_sno"})
    asg["deh_method"] = "name_anchor_voronoi"
    asg = st[["cluster", "adm2_name", "adm3_pcode", "n_buildings", "in_rural_population"]].merge(asg, on="cluster",
                                                                                                  how="left")
    asg.loc[asg.deh.isna(), "deh_method"] = "none"
    asg.to_parquet(DEH / "deh_assignment.parquet", index=False)

    listed = dehs.groupby("district").size().rename("dehs_listed")
    located = an.groupby("district").size().rename("dehs_geolocated")
    cov = pd.concat([listed, located], axis=1).fillna(0).astype(int)
    cov["geolocated_share"] = (cov.dehs_geolocated / cov.dehs_listed).round(3)
    rural = asg[asg.in_rural_population]
    by_d = rural.groupby("adm2_name").agg(rural_hamlets=("cluster", "size"),
                                         hamlets_with_deh=("deh", lambda s: s.notna().sum()))
    by_d["hamlet_share"] = (by_d.hamlets_with_deh / by_d.rural_hamlets).round(3)
    cov.reset_index().rename(columns={"index": "district"}).to_csv(DEH / "coverage_table.csv", index=False)
    by_d.reset_index().to_csv(DEH / "coverage_hamlets_by_district.csv", index=False)

    print(f"dehs listed (rural tehsils, not under sea): {len(dehs):,}; geolocated {len(an):,} "
          f"({len(an) / len(dehs):.1%}; exact {int((an.match == 'exact').sum()):,}, fuzzy {int((an.match == 'fuzzy').sum()):,})")
    print(f"tehsils with >= 1 anchor: {an.ocha_pcode.nunique()} of {dehs.ocha_pcode.nunique()}")
    print(f"rural hamlets with a proxy deh: {rural.deh.notna().mean():.1%}")
    print(cov.sort_values("geolocated_share").head(8).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
