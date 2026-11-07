"""Day 16: attach place names from OSM and GeoNames to settlement clusters.

    python scripts/attach_names.py

Inputs
    data/village_inventory/settlements/settlements_v0.parquet   hamlet polygons (Day 15)
    data/village_inventory/raw/{osm,geonames}.parquet           named points (Day 13)
Outputs
    data/village_inventory/settlements/names_alt.parquet        every name candidate: cluster, source, raw name,
                                                               normalised key, distance, match type
    data/village_inventory/settlements/settlements_v0_named.parquet   hamlets + primary name columns
    data/village_inventory/naming_coverage.csv                  named share by district

Matching: a point inside a hamlet polygon names that hamlet ("inside"); otherwise the nearest hamlet
within 250 m (OSM) or 500 m (GeoNames, coarser coordinates) ("near"). Points farther away stay unmatched.
Primary name = OSM inside > GeoNames inside > OSM near > GeoNames near, then nearest. Raw names are kept
unchanged. Arabic-script names get no Latin key (no transliteration is attempted), so they are kept but
not used for matching.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
SET = VI / "settlements"
CRS = 32642
MAX_D = {"osm": 250, "geonames": 500}
RANK = {("osm", "inside"): 0, ("geonames", "inside"): 1, ("osm", "near"): 2, ("geonames", "near"): 3}
GENERIC = {"goth", "gothi", "got", "village", "gaon", "gaun", "deh", "jo", "ji", "je", "ja", "mohalla",
           "muhalla", "colony", "basti", "para", "paro", "dhani", "dhand", "wandh", "wand", "old", "new"}
ARABIC = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")


def latin_part(s: str) -> str | None:
    """Latin text of a name; 'Sekhat (سیکاٹ)' -> 'Sekhat'. None if no Latin letters."""
    if not isinstance(s, str) or not LATIN.search(s):
        return None
    s = re.sub(r"\([^)]*[؀-ۿ][^)]*\)", " ", s)
    s = ARABIC.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip() or None


def name_key(s: str | None) -> str | None:
    """Lower-case ASCII, punctuation and generic settlement words removed, spaces dropped."""
    if not isinstance(s, str) or not s:
        return None
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    toks = [t for t in re.split(r"[^a-z]+", s) if t and t not in GENERIC]
    return "".join(toks) or None


def candidates(points: gpd.GeoDataFrame, hamlets: gpd.GeoDataFrame, source: str) -> pd.DataFrame:
    pts = points.to_crs(CRS)
    inside = gpd.sjoin(pts, hamlets[["cluster", "geometry"]], predicate="within", how="inner")
    inside["distance_m"] = 0.0
    inside["match"] = "inside"
    rest = pts[~pts.index.isin(inside.index)]
    near = gpd.sjoin_nearest(rest, hamlets[["cluster", "geometry"]], max_distance=MAX_D[source],
                             distance_col="distance_m", how="inner")
    near["match"] = "near"
    out = pd.concat([inside, near])
    out = out[~out.index.duplicated(keep="first")]  # a point on a shared edge: keep one
    out["source"] = source
    return pd.DataFrame(out.drop(columns=["geometry", "index_right"], errors="ignore"))


def main() -> int:
    hamlets = gpd.read_parquet(SET / "settlements_v0.parquet").to_crs(CRS)
    osm = gpd.read_parquet(VI / "raw/osm.parquet")
    osm = osm[osm.name.notna() & osm.fclass.isin(["village", "hamlet", "town", "city", "suburb", "locality",
                                                    "farm", "isolated_dwelling"])]
    gn = gpd.read_parquet(VI / "raw/geonames.parquet")

    c_osm = candidates(osm, hamlets, "osm")
    c_osm = c_osm.assign(source_id=c_osm.osm_id.astype(str), name_raw=c_osm.name, place_class=c_osm.fclass)
    c_gn = candidates(gn, hamlets, "geonames")
    c_gn = c_gn.assign(source_id=c_gn.geonameid.astype(str), name_raw=c_gn.name, place_class=c_gn.fcode)
    cols = ["cluster", "source", "source_id", "name_raw", "place_class", "match", "distance_m"]
    alt = pd.concat([c_osm[cols], c_gn[cols]], ignore_index=True)
    alt["name_latin"] = alt.name_raw.map(latin_part)
    alt["name_key"] = alt.name_latin.map(name_key)
    alt["script"] = alt.name_raw.map(lambda s: "arabic" if ARABIC.search(str(s)) and not LATIN.search(str(s))
                                     else "mixed" if ARABIC.search(str(s)) else "latin")
    # GeoNames alternate names as extra rows (Latin only), so later matching sees every spelling
    gn_alt = c_gn[c_gn.alternatenames.notna()][["cluster", "source_id", "alternatenames", "fcode", "match",
                                                 "distance_m"]]
    gn_alt = gn_alt.assign(name_raw=gn_alt.alternatenames.str.split(",")).explode("name_raw")
    gn_alt = gn_alt[gn_alt.name_raw.str.len() > 0]
    gn_alt = gn_alt.assign(source="geonames_alt", place_class=gn_alt.fcode, name_latin=gn_alt.name_raw.map(latin_part))
    gn_alt["name_key"] = gn_alt.name_latin.map(name_key)
    gn_alt["script"] = "latin"
    alt = pd.concat([alt, gn_alt[alt.columns]], ignore_index=True)
    alt = alt.drop_duplicates(["cluster", "source", "source_id", "name_key", "name_raw"])
    alt["distance_m"] = alt.distance_m.round(1)
    alt.to_parquet(SET / "names_alt.parquet", index=False)

    prim = alt[alt.source != "geonames_alt"].copy()
    prim["rank"] = [RANK[(s, m)] for s, m in zip(prim.source, prim.match)]
    prim = prim.sort_values(["cluster", "rank", "distance_m"]).drop_duplicates("cluster")
    named = hamlets.merge(prim[["cluster", "name_raw", "name_latin", "name_key", "source", "match", "distance_m"]]
                          .rename(columns={"name_raw": "name", "source": "name_source", "match": "name_match",
                                           "distance_m": "name_distance_m"}), on="cluster", how="left")
    n_names = alt[alt.source != "geonames_alt"].groupby("cluster").size()
    named["n_name_candidates"] = named.cluster.map(n_names).fillna(0).astype(int)
    named.to_crs(4326).to_parquet(SET / "settlements_v0_named.parquet")

    named["is_named"] = named.name.notna()
    vt = named.groupby("village_tier").agg(adm2_name=("adm2_name", "first"), named=("is_named", "any"))
    cov = named.groupby("adm2_name", dropna=False).agg(hamlets=("cluster", "size"), named_hamlets=("is_named", "sum"),
                                                      buildings=("n_buildings", "sum"))
    cov["named_share"] = (cov.named_hamlets / cov.hamlets).round(3)
    w = named[named.is_named].groupby("adm2_name").n_buildings.sum()
    cov["named_building_share"] = (w.reindex(cov.index).fillna(0) / cov.buildings).round(3)
    cov["villages"] = vt.groupby("adm2_name").size().reindex(cov.index)
    cov["named_villages"] = vt.groupby("adm2_name").named.sum().reindex(cov.index)
    cov["named_village_share"] = (cov.named_villages / cov.villages).round(3)
    cov.reset_index().to_csv(VI / "naming_coverage.csv", index=False)

    print(f"name candidates: {len(alt):,} rows ({alt.source.value_counts().to_dict()})")
    print(f"named hamlets: {int(named.is_named.sum()):,} / {len(named):,} ({named.is_named.mean():.1%}); "
          f"buildings in named hamlets {named[named.is_named].n_buildings.sum() / named.n_buildings.sum():.1%}; "
          f"village tier named {vt.named.mean():.1%}")
    print(named[named.is_named].groupby(["name_source", "name_match"]).size().to_string())
    print("unmatched points: osm", len(osm) - c_osm.shape[0], "geonames", len(gn) - c_gn.shape[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
