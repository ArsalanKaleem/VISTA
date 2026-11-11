"""Day 23: core, resource and connectivity zones for every rural hamlet, province-wide (Section 5.6).

    python scripts/build_zones_v1.py            # all steps
    python scripts/build_zones_v1.py --skip-connectivity

Definitions (D010; r_max is a parameter that Day 44 tests):
  core C_i      settlement polygon buffered 100 m
  resource R_i  Voronoi cell of the hamlet centroid (cells built from ALL hamlets, urban ones included, so
                rural cells stop at city neighbours), clipped to the OCHA tehsil, intersected with
                buffer(S_i, r_max), minus every core (own and foreign) and minus the water/urban mask.
                r_max = 2 km; 4 km in the Thar desert (Tharparkar and Umerkot districts).
  mask          OSM water polygons (water, reservoir, riverbank, river, lake, dock) and the settlement polygons
                of urban clusters / urban centres buffered 100 m. No JRC raster is held locally, so OSM stands
                in for 'permanent water'.
  connectivity  k = 8 nearest rural hamlets (centroid distance, province-wide). For each edge, the corridor is
                the straight segment buffered 100 m; roads / canals / drains (OSM) inside the corridor and within
                5 km of the core are buffered 25 m and unioned into K_i. Edges carry the network length by
                class, so the graph (Day 81) can be built from the same table.
Hamlets outside every OCHA tehsil (304) take the nearest tehsil for the Voronoi clip.

Outputs (data/village_inventory/zones/v1/):
  zones_core.parquet, zones_resource.parquet, zones_connectivity.parquet   GeoParquet, EPSG:4326, keyed by vid
  village_graph_knn8.parquet       edges: vid_i, vid_j, dist_m, road_m, canal_m, drain_m, same_tehsil
  zones_upload_q12.parquet         long table (vid, zone, area_m2) for Q1-Q2 hamlets, for `gee.run upload-zones`
  zone_qc.csv                      area statistics, empty zones, overlap checks
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
OUT = VI / "zones/v1"
OSM = ROOT / "data/raw/osm/geofabrik_pakistan_260712_shp"
CRS = 32642
CORE_BUF = 100.0
R_MAX, R_MAX_DESERT = 2000.0, 4000.0
DESERT_DISTRICTS = {"Tharparkar", "Umer Kot"}
WATER_CLASSES = {"water", "reservoir", "riverbank", "river", "lake", "dock"}
K, CORRIDOR_HALF, NET_BUF, REACH = 8, 100.0, 25.0, 5000.0
ROAD_SKIP = {"footway", "path", "steps", "cycleway", "pedestrian", "bridleway", "unknown"}


def log(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:6.0f} s] {msg}", flush=True)


def voronoi_cells(pts: np.ndarray, clip) -> list:
    """Voronoi cell of each point (same order), clipped to `clip`."""
    if len(pts) == 1:
        return [clip]
    mp = shapely.MultiPoint(pts)
    cells = list(shapely.voronoi_polygons(mp, extend_to=clip.envelope.buffer(10_000)).geoms)
    tree = STRtree(cells)
    idx = tree.query(shapely.points(pts), predicate="within")  # (point_idx, cell_idx) pairs
    cell_of = dict(zip(idx[0].tolist(), idx[1].tolist()))
    missing = [i for i in range(len(pts)) if i not in cell_of]
    for i in missing:  # a point exactly on a cell edge: nearest cell
        cell_of[i] = int(tree.nearest(shapely.Point(pts[i])))
    return [shapely.intersection(cells[cell_of[i]], clip) for i in range(len(pts))]


def subtract_hits(geoms: list, tree: STRtree, others: np.ndarray, skip_self: np.ndarray | None = None) -> list:
    """geoms[i] minus the union of `others` that intersect it (optionally skipping others[skip_self[i]])."""
    q = tree.query(geoms, predicate="intersects")
    by = {}
    for gi, oi in zip(q[0].tolist(), q[1].tolist()):
        if skip_self is not None and skip_self[gi] == oi:
            continue
        by.setdefault(gi, []).append(oi)
    out = list(geoms)
    for gi, ois in by.items():
        out[gi] = shapely.difference(geoms[gi], shapely.union_all(others[ois]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-connectivity", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    reg = gpd.read_parquet(VI / "registry/village_registry.parquet").to_crs(CRS)
    o3 = gpd.read_file(VI / "admin/admin_boundaries.gpkg", layer="ocha_adm3").to_crs(CRS)
    o3["geometry"] = o3.geometry.make_valid()
    log(f"registry {len(reg):,} hamlets; {len(o3)} tehsils", t0)

    # tehsil for the Voronoi clip: own tehsil, else the nearest one
    reg["teh"] = reg.adm3_pcode
    miss = reg.teh.isna()
    if miss.any():
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(reg.loc[miss, "lon"], reg.loc[miss, "lat"], crs=4326)).to_crs(CRS)
        nn = gpd.sjoin_nearest(pts, o3[["adm3_pcode", "geometry"]], how="left")
        nn = nn[~nn.index.duplicated()]
        reg.loc[miss, "teh"] = nn.adm3_pcode.values
    reg["r_max"] = np.where(reg.adm2_name.isin(DESERT_DISTRICTS), R_MAX_DESERT, R_MAX)
    reg["core"] = reg.geometry.buffer(CORE_BUF)
    centroid_xy = np.c_[reg.geometry.centroid.x, reg.geometry.centroid.y]
    reg["cx"], reg["cy"] = centroid_xy[:, 0], centroid_xy[:, 1]

    # masks
    water = gpd.read_file(OSM / "gis_osm_water_a_free_1.shp", bbox=tuple(o3.to_crs(4326).total_bounds))
    water = water[water.fclass.isin(WATER_CLASSES)].to_crs(CRS)
    water["geometry"] = water.geometry.make_valid()
    urban = reg[~reg.in_rural_population].core
    mask_geoms = np.concatenate([water.geometry.values, urban.values])
    mask_tree = STRtree(mask_geoms)
    core_all = reg.core.values
    core_tree = STRtree(core_all)
    log(f"mask: {len(water):,} water polygons, {len(urban):,} urban cores", t0)

    # resource zones per tehsil
    rural = reg[reg.in_rural_population]
    res_geoms = {}
    teh_geom = o3.set_index("adm3_pcode").geometry
    for n, (pcode, grp) in enumerate(reg.groupby("teh")):
        clip = teh_geom.loc[pcode]
        pts = grp[["cx", "cy"]].values
        cells = voronoi_cells(pts, clip)
        is_rural = grp.in_rural_population.values
        idx_r = np.flatnonzero(is_rural)
        if len(idx_r) == 0:
            continue
        raw = [shapely.intersection(cells[i], grp.geometry.iloc[i].buffer(grp.r_max.iloc[i])) for i in idx_r]
        raw = subtract_hits(raw, core_tree, core_all)          # minus every core, own included
        raw = subtract_hits(raw, mask_tree, mask_geoms)        # minus water and urban fabric
        for i, g in zip(idx_r, raw):
            res_geoms[grp.index[i]] = g
        if n % 20 == 0:
            log(f"  resource zones: tehsil {n + 1}/{reg.teh.nunique()} ({pcode}, {len(idx_r):,} rural)", t0)
    rural = rural.assign(resource=pd.Series(res_geoms))
    rural["resource"] = gpd.GeoSeries(rural.resource.values, index=rural.index, crs=CRS).make_valid()
    log(f"resource zones built for {len(rural):,} hamlets", t0)

    core = gpd.GeoDataFrame({"vid": rural.vid.values, "quality_class": rural.quality_class.values,
                             "adm3_pcode": rural.adm3_pcode.values}, geometry=rural.core.values, crs=CRS)
    core["area_m2"] = core.geometry.area.round(1)
    core.to_crs(4326).to_parquet(OUT / "zones_core.parquet")
    res = gpd.GeoDataFrame({"vid": rural.vid.values, "quality_class": rural.quality_class.values,
                            "adm3_pcode": rural.adm3_pcode.values, "r_max": rural.r_max.values},
                           geometry=rural.resource.values, crs=CRS)
    res["area_m2"] = res.geometry.area.round(1)
    res.to_crs(4326).to_parquet(OUT / "zones_resource.parquet")

    # upload table for Q1-Q2
    q12 = rural.quality_class != "Q3"
    up = pd.concat([core[q12.values][["vid", "geometry", "area_m2"]].assign(zone="core"),
                    res[q12.values][["vid", "geometry", "area_m2"]].assign(zone="resource")], ignore_index=True)
    up = gpd.GeoDataFrame(up, geometry="geometry", crs=CRS)
    up = up[~up.geometry.is_empty & (up.area_m2 > 0)]
    up["geometry"] = up.geometry.simplify(5, preserve_topology=True).make_valid()
    up.to_crs(4326).to_parquet(OUT / "zones_upload_q12.parquet")

    # connectivity
    edges = None
    conn = None
    if not args.skip_connectivity:
        xy = rural[["cx", "cy"]].values
        tree = cKDTree(xy)
        d, j = tree.query(xy, k=K + 1)
        src = np.repeat(np.arange(len(xy)), K)
        dst = j[:, 1:].ravel()
        dist = d[:, 1:].ravel()
        lo, hi = np.minimum(src, dst), np.maximum(src, dst)
        e = pd.DataFrame({"i": lo, "j": hi, "dist_m": dist}).drop_duplicates(["i", "j"]).reset_index(drop=True)
        log(f"knn graph: {len(e):,} unique edges", t0)
        roads = gpd.read_file(OSM / "gis_osm_roads_free_1.shp", bbox=tuple(o3.to_crs(4326).total_bounds),
                              columns=["fclass"])
        roads = roads[~roads.fclass.isin(ROAD_SKIP)].to_crs(CRS)
        ww = gpd.read_file(OSM / "gis_osm_waterways_free_1.shp", bbox=tuple(o3.to_crs(4326).total_bounds),
                           columns=["fclass"]).to_crs(CRS)
        net = pd.concat([roads.assign(cls="road"), ww[ww.fclass.isin(["canal", "drain"])].assign(cls=ww.fclass)],
                        ignore_index=True)
        net_tree = STRtree(net.geometry.values)
        log(f"network: {len(roads):,} road lines, {int((net.cls != 'road').sum()):,} canal/drain lines", t0)
        segs = shapely.linestrings(np.stack([xy[e.i.values], xy[e.j.values]], axis=1))
        corr = shapely.buffer(segs, CORRIDOR_HALF, cap_style="flat")
        # network length per edge, in batches (the pair list is large)
        e["road_m"] = 0.0; e["canal_m"] = 0.0; e["drain_m"] = 0.0
        B = 50_000
        for s0 in range(0, len(e), B):
            q = net_tree.query(corr[s0:s0 + B], predicate="intersects")
            if len(q[0]) == 0:
                continue
            plen = shapely.length(shapely.intersection(corr[s0 + q[0]], net.geometry.values[q[1]]))
            agg = pd.DataFrame({"e": s0 + q[0], "cls": net.cls.values[q[1]], "len": plen})                 .pivot_table(index="e", columns="cls", values="len", aggfunc="sum", fill_value=0.0)
            for col in agg.columns:
                e.loc[agg.index, f"{col}_m"] = agg[col].values
            log(f"  edge network lengths {min(s0 + B, len(e)):,}/{len(e):,}", t0)
        e["same_tehsil"] = rural.teh.values[e.i.values] == rural.teh.values[e.j.values]
        vid = rural.vid.values
        edges = pd.DataFrame({"vid_i": vid[e.i.values], "vid_j": vid[e.j.values], "dist_m": e.dist_m.round(1),
                              "road_m": e.road_m.round(1), "canal_m": e.canal_m.round(1), "drain_m": e.drain_m.round(1),
                              "same_tehsil": e.same_tehsil})
        edges.to_parquet(OUT / "village_graph_knn8.parquet", index=False)
        log("edges written", t0)
        # K_i per hamlet: network inside the corridors of its edges, within REACH of its core (WKB kept, not geometries)
        inc: dict = {}
        for row, (a_, b_) in enumerate(zip(e.i.values, e.j.values)):
            inc.setdefault(a_, []).append(row)
            inc.setdefault(b_, []).append(row)
        reach = rural.core.buffer(REACH - CORE_BUF).values
        wkb = []
        empty_wkb = shapely.to_wkb(shapely.Polygon())
        for h in range(len(rural)):
            rows = inc.get(h, [])
            if not rows:
                wkb.append(empty_wkb)
                continue
            cs = corr[rows]
            q = net_tree.query(cs, predicate="intersects")
            if len(q[0]) == 0:
                wkb.append(empty_wkb)
                continue
            pieces = shapely.intersection(cs[q[0]], net.geometry.values[q[1]])
            g = shapely.intersection(shapely.union_all(shapely.buffer(pieces, NET_BUF)), reach[h])
            wkb.append(shapely.to_wkb(g))
            if h % 20000 == 0:
                log(f"  connectivity {h:,}/{len(rural):,}", t0)
        conn_geoms = shapely.from_wkb(wkb)
        conn = gpd.GeoDataFrame({"vid": rural.vid.values}, geometry=conn_geoms, crs=CRS)
        conn["n_edges"] = conn.vid.map(pd.concat([edges.vid_i, edges.vid_j]).value_counts()).fillna(0).astype(int)
        tot = (edges.road_m + edges.canal_m + edges.drain_m) / 1000
        per_v = pd.concat([pd.Series(tot.values, index=edges.vid_i.values), pd.Series(tot.values, index=edges.vid_j.values)])             .groupby(level=0).sum()
        conn["network_km"] = conn.vid.map(per_v).fillna(0).round(2)
        conn["area_m2"] = conn.geometry.area.round(1)
        conn.to_crs(4326).to_parquet(OUT / "zones_connectivity.parquet")
        log("connectivity zones written", t0)

    # QC
    rows = []
    for name, g in (("core", core), ("resource", res)) + ((("connectivity", conn),) if conn is not None else ()):
        a = g.area_m2 / 1e6
        rows.append({"zone": name, "n": len(g), "empty": int(g.geometry.is_empty.sum()), "invalid": int((~g.is_valid).sum()),
                     "area_km2_min": round(a.min(), 4), "area_km2_p10": round(a.quantile(.1), 3),
                     "area_km2_median": round(a.median(), 3), "area_km2_p90": round(a.quantile(.9), 3),
                     "area_km2_max": round(a.max(), 2), "area_km2_total": round(a.sum(), 1)})
    # resource vs foreign core overlap: sample 20,000 resource zones against all cores
    rng = np.random.default_rng(23)
    samp = rng.choice(len(res), size=min(20000, len(res)), replace=False)
    hits = core_tree.query(res.geometry.values[samp], predicate="intersects")
    ov = 0
    for gi, oi in zip(hits[0], hits[1]):
        inter = shapely.intersection(res.geometry.values[samp[gi]], core_all[oi])
        if shapely.area(inter) > 1.0:  # > 1 m2 (touching edges are fine)
            ov += 1
    rows.append({"zone": "resource_vs_any_core_overlap_pairs_in_20k_sample", "n": ov})
    q12_res_empty = int(res[q12.values].geometry.is_empty.sum() + (res[q12.values].area_m2 == 0).sum())
    rows.append({"zone": "q12_resource_empty", "n": q12_res_empty})
    pd.DataFrame(rows).to_csv(OUT / "zone_qc.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    log(f"done; upload table {len(up):,} features for {int(q12.sum()):,} Q1-Q2 hamlets", t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
