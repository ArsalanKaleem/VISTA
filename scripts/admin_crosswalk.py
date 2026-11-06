"""Day 12: harmonised admin boundaries and taluka crosswalk PBS 2020 <-> OCHA COD-AB 2022 <-> geoBoundaries.

    python scripts/admin_crosswalk.py

Inputs
    data/raw/hdx/pak_admin_boundaries.shp.zip     OCHA COD-AB (valid_on 2022-09-09), pcodes PK7xxyy
    data/village_inventory/admin/sindh_adm3.geojson   geoBoundaries ADM3: the spine used by every GEE job so far
    data/village_inventory/pbs_sindh_tables/t1_1_mouzas_by_status.csv   PBS Mouza Census 2020 (Day 11)

Outputs
    data/village_inventory/admin/admin_boundaries.gpkg   layers ocha_adm1/2/3, gb_adm3 (EPSG:4326), repaired
    data/village_inventory/admin/taluka_crosswalk.csv     one row per PBS taluka (plus unmatched OCHA tehsils)
    data/village_inventory/admin/gb_ocha_overlap.csv      geoBoundaries ADM3 x OCHA ADM3 area shares (>= 1%)
    data/village_inventory/admin/district_sources.csv     district set in PBS 2020 vs OCHA 2022 (year-by-year history: admin_history.py)
    data/village_inventory/admin/geometry_qc.csv          invalid / empty geometry counts before and after repair
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "data/village_inventory/admin"
OCHA = "zip://" + str(ROOT / "data/raw/hdx/pak_admin_boundaries.shp.zip") + "!"
UTM = 32642

# spelling variants that normalisation alone cannot reconcile (PBS spelling -> OCHA spelling)
ALIASES = {
    "GOLARCHI SFRAHU": "SHAHEED FAZIL RAHU",
    "SEHWAN": "SEHWAN SHARIF",
    "KAMBAR ALI KHAN": "QAMBAR ALI KHAN",
    "MIRO KHAN": "MEERO KHAN",
    "NASIRABAD": "NASIR ABAD",
    "SUJAWAL JUNEJO": "SIJAWAL JUNEJO",
    "KANDHKOT": "KANDH KOT",
    "KASHMOR": "KASHMORE",
    "BAKRANI": "BAQRANI",
    "RATODERO": "RATO DERO",
    "HUSSAIN BUX MARI": "HUSSAIN BUX MUREE",
    "SHUJAABAD": "SHUJA ABAD",
    "ISLAMKOT": "ISLAM KOT",
    "MEHRABPUR": "MEHRAB PUR",
    "KAZI AHMED": "DAULAT PUR",  # Qazi Ahmed taluka; OCHA labels it by Daulatpur (checked spatially below)
    "KOTDIJI": "KOT DIJI",
    "MIRWAH": "THARI MEER WAH",
    "SOBHODERO": "SOBHO DERO",
    "PANO AKIL": "PANO AQIL",
    "QASIM ABAD": "QASIMABAD",
    "BIN QASIM": "BIN QASIM",
    "GADAP": "GADAP",
    "SUKKUR CITY": "SUKKUR",
}
# PBS Karachi sub-divisions created after the OCHA 2022 tehsil set (no one-to-one tehsil): kept 'unmapped'
UNMAPPED_NOTE = "Karachi sub-division with no OCHA 2022 tehsil; compare at district level only"
# PBS district -> OCHA adm2 name where they differ
DISTRICTS = {
    "KARACHI WEST": "WEST KARACHI",
    "MALIR": "MALIR KARACHI",
    "SHAHEED BENAZIRABAD": "SHAHEED BENAZIR ABAD",
}


def norm(s: str) -> str:
    s = str(s).upper()
    s = re.sub(r"\b(TALUKA|TALUKS|TALUKAS|TOWN|SUB-DIVISION|SUBDIVISION|DISTRICT)\b", " ", s)
    s = re.sub(r"[^A-Z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def repair(g: gpd.GeoDataFrame, layer: str, qc: list) -> gpd.GeoDataFrame:
    before = int((~g.is_valid).sum())
    g = g.copy()
    g["geometry"] = g.geometry.make_valid().buffer(0)
    g = g[~g.geometry.is_empty]
    qc.append({"layer": layer, "features": len(g), "invalid_before": before,
               "invalid_after": int((~g.is_valid).sum()), "empty_after": int(g.geometry.is_empty.sum())})
    return g


def main() -> int:
    qc: list = []
    o1 = gpd.read_file(OCHA + "pak_admin1.shp")
    o1 = repair(o1[o1.adm1_name == "Sindh"], "ocha_adm1", qc)
    o2 = gpd.read_file(OCHA + "pak_admin2.shp")
    o2 = repair(o2[o2.adm1_name == "Sindh"], "ocha_adm2", qc)
    o3 = gpd.read_file(OCHA + "pak_admin3.shp")
    o3 = repair(o3[o3.adm1_name == "Sindh"], "ocha_adm3", qc)
    gb = repair(gpd.read_file(ADMIN / "sindh_adm3.geojson"), "gb_adm3", qc)
    keep = lambda g, cols: g[[c for c in cols if c in g.columns] + ["geometry"]].to_crs(4326)
    out = ADMIN / "admin_boundaries.gpkg"
    out.unlink(missing_ok=True)
    keep(o1, ["adm1_name", "adm1_pcode", "valid_on"]).to_file(out, layer="ocha_adm1")
    keep(o2, ["adm2_name", "adm2_pcode", "adm1_pcode", "valid_on"]).to_file(out, layer="ocha_adm2")
    keep(o3, ["adm3_name", "adm3_pcode", "adm2_name", "adm2_pcode", "valid_on"]).to_file(out, layer="ocha_adm3")
    keep(gb, ["shapeName", "shapeID"]).to_file(out, layer="gb_adm3")
    pd.DataFrame(qc).to_csv(ADMIN / "geometry_qc.csv", index=False)

    # geoBoundaries x OCHA area overlap (UTM 42N)
    a = gb[["shapeID", "shapeName", "geometry"]].to_crs(UTM)
    b = o3[["adm3_pcode", "adm3_name", "adm2_name", "geometry"]].to_crs(UTM)
    a["gb_area"] = a.area
    b["ocha_area"] = b.area
    ov = gpd.overlay(a, b, how="intersection", keep_geom_type=True)
    ov["share_of_gb"] = ov.area / ov.gb_area
    ov["share_of_ocha"] = ov.area / ov.ocha_area
    ov = ov[(ov.share_of_gb >= 0.01) | (ov.share_of_ocha >= 0.01)]
    ov = ov.drop(columns="geometry").sort_values(["shapeName", "share_of_gb"], ascending=[True, False])
    ov[["shapeID", "shapeName", "adm3_pcode", "adm3_name", "adm2_name", "share_of_gb", "share_of_ocha"]] \
        .round(4).to_csv(ADMIN / "gb_ocha_overlap.csv", index=False)
    # main OCHA tehsil for each gb polygon, and main gb polygon for each OCHA tehsil
    gb_main = ov.sort_values("share_of_gb", ascending=False).drop_duplicates("shapeID")
    ocha_main = ov.sort_values("share_of_ocha", ascending=False).drop_duplicates("adm3_pcode") \
        .set_index("adm3_pcode")

    # PBS talukas -> OCHA tehsils, by normalised name within the district
    pbs = pd.read_csv(ADMIN.parent / "pbs_sindh_tables/t1_1_mouzas_by_status.csv")
    tal = pbs[pbs.level == "taluka"].copy()
    tal["d_norm"] = tal.district.map(norm).map(lambda d: DISTRICTS.get(d, d))
    o3n = o3.assign(n=o3.adm3_name.map(norm), d=o3.adm2_name.map(norm))
    rows = []
    for _, r in tal.iterrows():
        n = norm(r["name"])
        n_alias = ALIASES.get(n, n)
        cand = o3n[o3n.d == r.d_norm]
        hit = cand[cand.n == n_alias]
        method = "exact" if n_alias == n else "alias"
        if hit.empty:
            close = difflib.get_close_matches(n_alias, cand.n.tolist(), n=1, cutoff=0.8)
            hit = cand[cand.n.isin(close)]
            method = "fuzzy" if not hit.empty else "unmatched"
        row = {"pbs_division": r.division, "pbs_district": r.district, "pbs_taluka": r["name"],
               "pbs_mouzas_total": r.mouzas_total, "pbs_rural_populated": r.rural_populated,
               "match": method, "ocha_adm2_name": None, "ocha_adm2_pcode": None, "ocha_adm3_name": None,
               "ocha_adm3_pcode": None, "gb_shapeID": None, "gb_shapeName": None, "gb_share_of_ocha": None}
        if not hit.empty:
            h = hit.iloc[0]
            row.update(ocha_adm2_name=h.adm2_name, ocha_adm2_pcode=h.adm2_pcode, ocha_adm3_name=h.adm3_name,
                       ocha_adm3_pcode=h.adm3_pcode)
            if h.adm3_pcode in ocha_main.index:
                m = ocha_main.loc[h.adm3_pcode]
                row.update(gb_shapeID=m.shapeID, gb_shapeName=m.shapeName, gb_share_of_ocha=round(m.share_of_ocha, 4))
        rows.append(row)
    cw = pd.DataFrame(rows)
    cw.loc[(cw.match == "unmatched") & cw.pbs_district.str.contains("KARACHI|MALIR"), "note"] = UNMAPPED_NOTE
    used = set(cw.ocha_adm3_pcode.dropna())
    extra = o3[~o3.adm3_pcode.isin(used)]
    for _, h in extra.iterrows():  # OCHA tehsils with no PBS taluka (Karachi towns not enumerated, etc.)
        m = ocha_main.loc[h.adm3_pcode] if h.adm3_pcode in ocha_main.index else None
        cw.loc[len(cw)] = {"match": "ocha_only", "ocha_adm2_name": h.adm2_name, "ocha_adm2_pcode": h.adm2_pcode,
                           "ocha_adm3_name": h.adm3_name, "ocha_adm3_pcode": h.adm3_pcode,
                           "gb_shapeID": None if m is None else m.shapeID,
                           "gb_shapeName": None if m is None else m.shapeName,
                           "gb_share_of_ocha": None if m is None else round(m.share_of_ocha, 4)}
    cw.to_csv(ADMIN / "taluka_crosswalk.csv", index=False)

    # district sets per source
    pbs_d = set(pbs[pbs.level == "district"].district.map(norm).map(lambda d: DISTRICTS.get(d, d)))
    ocha_d = set(o2.adm2_name.map(norm))
    hist = pd.DataFrame({"district": sorted(pbs_d | ocha_d)})
    hist["in_pbs_2020"] = hist.district.isin(pbs_d)
    hist["in_ocha_2022"] = hist.district.isin(ocha_d)
    hist["note"] = ""
    hist.loc[~hist.in_pbs_2020 & hist.district.str.contains("KARACHI"), "note"] = \
        "urban Karachi district: not enumerated in the Mouza Census"
    hist.to_csv(ADMIN / "district_sources.csv", index=False)

    # coverage of each OCHA tehsil by the geoBoundaries spine (holes = missing GEE inputs)
    gu = a.union_all()
    b["gb_coverage"] = b.geometry.intersection(gu).area / b.ocha_area
    cw = cw.merge(b[["adm3_pcode", "gb_coverage"]].round(4), left_on="ocha_adm3_pcode", right_on="adm3_pcode",
                  how="left").drop(columns="adm3_pcode")
    cw.to_csv(ADMIN / "taluka_crosswalk.csv", index=False)
    holes = b[b.gb_coverage < 0.9]
    print("OCHA tehsils < 90% covered by geoBoundaries ADM3:")
    print(holes[["adm3_pcode", "adm3_name", "adm2_name", "gb_coverage"]].to_string(index=False))

    tal_n = len(tal)
    matched = cw[cw.match.isin(["exact", "alias", "fuzzy"])]
    print(f"geometry: {pd.DataFrame(qc).to_string(index=False)}")
    print(f"PBS talukas {tal_n}: matched {len(matched)} ({matched.match.value_counts().to_dict()}), "
          f"unmatched {int((cw.match == 'unmatched').sum())}")
    print(cw[cw.match == "unmatched"][["pbs_district", "pbs_taluka"]].to_string())
    print("OCHA tehsils with no PBS taluka:", ", ".join(extra.adm3_name))
    low = cw[cw.gb_share_of_ocha.notna() & (cw.gb_share_of_ocha < 0.9)]
    print("OCHA tehsils split across geoBoundaries polygons (<90% in one):")
    print(low[["pbs_taluka", "ocha_adm3_name", "gb_shapeName", "gb_share_of_ocha"]].to_string())
    print("districts only in one source:")
    print(hist[hist.in_pbs_2020 != hist.in_ocha_2022].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
