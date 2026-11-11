"""Day 23 (part 2): k-nearest-neighbour village graph and connectivity zones K_i, resumable.

    python scripts/build_connectivity.py

Edges: k = 8 nearest rural hamlets by centroid distance (province-wide), de-duplicated; each edge carries the
length of OSM roads, canals and drains inside the 100 m corridor around the straight segment.
K_i: the network pieces inside the corridors of the hamlet's edges, buffered 25 m, within 5 km of its core.

The corridor loop crashed twice between hamlet 140,000 and 155,731 (silent exit, no Python traceback: a
native crash in one geometry operation). So this script works in blocks of 5,000 hamlets with a checkpoint
file per block; a rerun skips finished blocks, and a block whose marker says it crashed is redone in safe
mode (the longest 2,000 pieces only, unioned in parts). Outputs join data/village_inventory/zones/v1/:
village_graph_knn8.parquet, zones_connectivity.parquet, and a connectivity row in zone_qc.csv.
"""
from __future__ import annotations

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
CK = OUT / "connectivity_checkpoints"
OSM = ROOT / "data/raw/osm/geofabrik_pakistan_260712_shp"
CRS = 32642
CORE_BUF, K, CORRIDOR_HALF, NET_BUF, REACH = 100.0, 8, 100.0, 25.0, 5000.0
ROAD_SKIP = {"footway", "path", "steps", "cycleway", "pedestrian", "bridleway", "unknown"}
BLOCK, SAFE_MAX = 5000, 2000


def log(msg, t0):
    print(f"[{time.time() - t0:6.0f} s] {msg}", flush=True)


def union_safe(geoms: np.ndarray) -> shapely.Geometry:
    """Union in parts of 200 to keep each GEOS call small."""
    parts = [shapely.union_all(geoms[i:i + 200]) for i in range(0, len(geoms), 200)]
    return shapely.union_all(parts) if len(parts) > 1 else parts[0]


def main() -> int:
    t0 = time.time()
    CK.mkdir(parents=True, exist_ok=True)
    reg = gpd.read_parquet(VI / "registry/village_registry.parquet",
                           columns=["vid", "adm3_pcode", "lon", "lat", "in_rural_population", "geometry"]).to_crs(CRS)
    rural = reg[reg.in_rural_population].reset_index(drop=True)
    xy = np.c_[rural.geometry.centroid.x, rural.geometry.centroid.y]
    core = rural.geometry.buffer(CORE_BUF).values
    log(f"{len(rural):,} rural hamlets", t0)

    bbox = tuple(reg.to_crs(4326).total_bounds)
    roads = gpd.read_file(OSM / "gis_osm_roads_free_1.shp", bbox=bbox, columns=["fclass"])
    roads = roads[~roads.fclass.isin(ROAD_SKIP)].to_crs(CRS)
    ww = gpd.read_file(OSM / "gis_osm_waterways_free_1.shp", bbox=bbox, columns=["fclass"]).to_crs(CRS)
    net = pd.concat([roads.assign(cls="road"), ww[ww.fclass.isin(["canal", "drain"])].assign(cls=ww.fclass)],
                    ignore_index=True)
    net_geoms = net.geometry.values
    net_tree = STRtree(net_geoms)
    log(f"network: {len(roads):,} road lines, {int((net.cls != 'road').sum()):,} canal/drain lines", t0)

    # edges
    edge_file = OUT / "village_graph_knn8.parquet"
    d, j = cKDTree(xy).query(xy, k=K + 1)
    src = np.repeat(np.arange(len(xy)), K)
    dst = j[:, 1:].ravel()
    e = pd.DataFrame({"i": np.minimum(src, dst), "j": np.maximum(src, dst), "dist_m": d[:, 1:].ravel()}) \
        .drop_duplicates(["i", "j"]).reset_index(drop=True)
    segs = shapely.linestrings(np.stack([xy[e.i.values], xy[e.j.values]], axis=1))
    corr = shapely.buffer(segs, CORRIDOR_HALF, cap_style="flat")
    if edge_file.exists():
        edges = pd.read_parquet(edge_file)
        log(f"edges: {len(edges):,} loaded", t0)
    else:
        for c in ("road", "canal", "drain"):
            e[f"{c}_m"] = 0.0
        B = 50_000
        for s0 in range(0, len(e), B):
            q = net_tree.query(corr[s0:s0 + B], predicate="intersects")
            if len(q[0]):
                plen = shapely.length(shapely.intersection(corr[s0 + q[0]], net_geoms[q[1]]))
                agg = pd.DataFrame({"e": s0 + q[0], "cls": net.cls.values[q[1]], "len": plen}) \
                    .pivot_table(index="e", columns="cls", values="len", aggfunc="sum", fill_value=0.0)
                for col in agg.columns:
                    e.loc[agg.index, f"{col}_m"] = agg[col].values
            log(f"  edge lengths {min(s0 + B, len(e)):,}/{len(e):,}", t0)
        vid = rural.vid.values
        pc = rural.adm3_pcode.values
        edges = pd.DataFrame({"vid_i": vid[e.i.values], "vid_j": vid[e.j.values], "dist_m": e.dist_m.round(1),
                              "road_m": e.road_m.round(1), "canal_m": e.canal_m.round(1), "drain_m": e.drain_m.round(1),
                              "same_tehsil": pc[e.i.values] == pc[e.j.values]})
        edges.to_parquet(edge_file, index=False)
        log(f"edges: {len(edges):,} written", t0)

    inc: dict = {}
    for row, (a_, b_) in enumerate(zip(e.i.values, e.j.values)):
        inc.setdefault(int(a_), []).append(row)
        inc.setdefault(int(b_), []).append(row)
    reach = shapely.buffer(core, REACH - CORE_BUF)
    empty_wkb = shapely.to_wkb(shapely.Polygon())

    def k_zone(h: int, safe: bool) -> bytes:
        rows = inc.get(h, [])
        if not rows:
            return empty_wkb
        cs = corr[rows]
        q = net_tree.query(cs, predicate="intersects")
        if len(q[0]) == 0:
            return empty_wkb
        pieces = shapely.intersection(cs[q[0]], net_geoms[q[1]])
        pieces = pieces[~shapely.is_empty(pieces)]
        if safe and len(pieces) > SAFE_MAX:
            pieces = pieces[np.argsort(-shapely.length(pieces))[:SAFE_MAX]]
        buf = shapely.buffer(pieces, NET_BUF)
        g = union_safe(buf) if safe else shapely.union_all(buf)
        return shapely.to_wkb(shapely.intersection(g, reach[h]))

    n = len(rural)
    for b0 in range(0, n, BLOCK):
        f = CK / f"block_{b0:06d}.parquet"
        if f.exists():
            continue
        marker = CK / f"block_{b0:06d}.inprogress"
        safe = marker.exists()  # a previous attempt died inside this block
        marker.write_text("1")
        wkb = []
        for h in range(b0, min(b0 + BLOCK, n)):
            try:
                wkb.append(k_zone(h, safe))
            except Exception as exc:  # a Python-level failure: retry that hamlet in safe mode
                print(f"  hamlet {h}: {exc}; safe mode")
                wkb.append(k_zone(h, True))
        pd.DataFrame({"h": np.arange(b0, b0 + len(wkb)), "wkb": wkb, "safe": safe}).to_parquet(f, index=False)
        marker.unlink()
        log(f"  block {b0:,} done{' (safe mode)' if safe else ''}", t0)

    parts = pd.concat([pd.read_parquet(f) for f in sorted(CK.glob("block_*.parquet"))], ignore_index=True)
    assert len(parts) == n and (parts.h.values == np.arange(n)).all()
    conn = gpd.GeoDataFrame({"vid": rural.vid.values}, geometry=shapely.from_wkb(parts.wkb.values), crs=CRS)
    conn["n_edges"] = conn.vid.map(pd.concat([edges.vid_i, edges.vid_j]).value_counts()).fillna(0).astype(int)
    tot = (edges.road_m + edges.canal_m + edges.drain_m) / 1000
    per_v = pd.concat([pd.Series(tot.values, index=edges.vid_i.values), pd.Series(tot.values, index=edges.vid_j.values)]) \
        .groupby(level=0).sum()
    conn["network_km"] = conn.vid.map(per_v).fillna(0).round(2)
    conn["safe_mode"] = parts.safe.values
    conn["area_m2"] = conn.geometry.area.round(1)
    conn.to_crs(4326).to_parquet(OUT / "zones_connectivity.parquet")
    a = conn.area_m2 / 1e6
    row = {"zone": "connectivity", "n": len(conn), "empty": int(conn.geometry.is_empty.sum()), "invalid": int((~conn.is_valid).sum()),
           "area_km2_min": round(a.min(), 4), "area_km2_p10": round(a.quantile(.1), 3), "area_km2_median": round(a.median(), 3),
           "area_km2_p90": round(a.quantile(.9), 3), "area_km2_max": round(a.max(), 2), "area_km2_total": round(a.sum(), 1)}
    qc = pd.read_csv(OUT / "zone_qc.csv") if (OUT / "zone_qc.csv").exists() else pd.DataFrame()
    qc = pd.concat([qc[qc.zone != "connectivity"] if len(qc) else qc, pd.DataFrame([row])], ignore_index=True)
    qc.to_csv(OUT / "zone_qc.csv", index=False)
    print(pd.DataFrame([row]).to_string(index=False))
    print(f"edges {len(edges):,}; hamlets with no network in any corridor: {int(conn.geometry.is_empty.sum()):,}; "
          f"safe-mode hamlets {int(conn.safe_mode.sum()):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
