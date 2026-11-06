"""Settlement clusters from building centroids (Days 14-15).

Local re-implementation of gee/lib/settlements.provisional_settlements, so the whole province can be
clustered without per-taluka Earth Engine tasks and without seams at taluka borders:

    paint building centroids on a 10 m grid (EPSG:32642, origin-aligned like Earth Engine)
    -> dilate by a (2r+1)^2 square, r = dilate_m / 10 (GEE focalMax square)
    -> 8-connected components -> clusters with >= min_buildings buildings -> polygons

The grid is processed in square tiles. Each tile is read with a halo of r+1 pixels so the dilation is
exact, components are labelled on the tile core plus one pixel of overlap, and labels that share a pixel
across a seam are merged with union-find. The result equals clustering the whole grid at once
(tests/test_settlements.py checks this).

Difference from the GEE version: GEE paints footprint polygons, this paints centroids, so clusters are
about half a building width smaller on each side. Day 14 compares the two on the pilots.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import ndimage

try:  # polygons are optional: counts and membership need only numpy/scipy
    import geopandas as gpd
    import rasterio.features
    from affine import Affine
    from shapely.geometry import shape
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover
    gpd = None

CRS = 32642


@dataclass
class Params:
    dilate_m: float = 40.0
    min_buildings: int = 5
    scale_m: float = 10.0
    tile_px: int = 4000          # 40 km tiles at 10 m


class _UF:
    def __init__(self):
        self.p: dict = {}

    def find(self, a):
        p = self.p
        p.setdefault(a, a)
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def cluster(x: np.ndarray, y: np.ndarray, prm: Params = Params(), polygons: bool = True):
    """Cluster building centroids (UTM 42N metres).

    Returns (member, clusters):
      member   int64 array, cluster id per building (-1 if its cluster has < min_buildings)
      clusters DataFrame (cluster, n_buildings, x, y [, geometry]) or GeoDataFrame with polygons
    """
    s, r, T = prm.scale_m, int(round(prm.dilate_m / prm.scale_m)), prm.tile_px
    col = np.floor(x / s).astype(np.int64)
    row = np.floor(-y / s).astype(np.int64)        # north-up: row grows southwards
    c0, r0 = col.min() - r - 2, row.min() - r - 2   # grid origin (multiple of s, as in GEE)
    lc, lr = col - c0, row - r0
    tc, tr = lc // T, lr // T
    struct8 = np.ones((3, 3), bool)
    halo = r + 1
    order = np.lexsort((tc, tr))
    tc_s, tr_s = tc[order], tr[order]
    keys = tr_s * 1_000_000 + tc_s
    bounds = np.flatnonzero(np.diff(keys)) + 1
    starts, ends = np.r_[0, bounds], np.r_[bounds, len(keys)]
    tiles = {(int(tr_s[a]), int(tc_s[a])): order[a:b] for a, b in zip(starts, ends)}

    uf = _UF()
    local = np.full(len(x), -1, np.int64)          # building -> global provisional label
    edge_labels: dict = {}                          # (tile, side) -> label strip on the 1 px overlap
    tile_parts = []                                 # (tile key, label array, offset, window origin)
    next_id = 0
    # also process empty tiles next to occupied ones: dilation from neighbours can bridge through them
    keys_all = {(i + di, j + dj) for (i, j) in tiles for di in (-1, 0, 1) for dj in (-1, 0, 1)}
    empty = np.empty(0, np.int64)
    for (ti, tj) in sorted(keys_all):
        idx = tiles.get((ti, tj), empty)
        # buildings that can influence this tile: those within halo pixels of its core
        R0, C0 = ti * T - halo, tj * T - halo
        H = W = T + 2 * halo
        cand = [idx]
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (di or dj) and (ti + di, tj + dj) in tiles:
                    j = tiles[(ti + di, tj + dj)]
                    m = (lr[j] >= R0) & (lr[j] < R0 + H) & (lc[j] >= C0) & (lc[j] < C0 + W)
                    cand.append(j[m])
        allj = np.concatenate(cand)
        if not len(allj):
            continue
        img = np.zeros((H, W), bool)
        img[lr[allj] - R0, lc[allj] - C0] = True
        # square dilation == separable max filter (much faster than binary_dilation for large r)
        grown = ndimage.maximum_filter(img.view(np.uint8), size=2 * r + 1, mode="constant").view(bool)
        # core + 1 px overlap to the south and east, so seams can be matched
        core = grown[halo:halo + T + 1, halo:halo + T + 1]
        lab, n = ndimage.label(core, structure=struct8)
        lab = lab.astype(np.int64)
        lab[lab > 0] += next_id
        next_id += n
        own = lab[lr[idx] - ti * T, lc[idx] - tj * T]
        local[idx] = own
        edge_labels[(ti, tj, "S")] = lab[T, :T + 1].copy()
        edge_labels[(ti, tj, "E")] = lab[:T + 1, T].copy()
        edge_labels[(ti, tj, "N")] = lab[0, :T + 1].copy()
        edge_labels[(ti, tj, "W")] = lab[:T + 1, 0].copy()
        if polygons:
            tile_parts.append((ti, tj, lab[:T, :T], r0 + ti * T, c0 + tj * T))
    # seams: the overlap row/column of a tile is the first row/column of its neighbour
    for (ti, tj, side), strip in list(edge_labels.items()):
        if side == "S" and (ti + 1, tj, "N") in edge_labels:
            other = edge_labels[(ti + 1, tj, "N")]
        elif side == "E" and (ti, tj + 1, "W") in edge_labels:
            other = edge_labels[(ti, tj + 1, "W")]
        else:
            continue
        both = (strip > 0) & (other > 0)
        for a, b in set(zip(strip[both].tolist(), other[both].tolist())):
            uf.union(a, b)
    # corner seam (diagonal neighbour): pixel (T, T) of a tile is pixel (0, 0) of tile (ti+1, tj+1)
    for (ti, tj, side), strip in list(edge_labels.items()):
        if side == "S" and (ti + 1, tj + 1, "N") in edge_labels:
            a, b = strip[T], edge_labels[(ti + 1, tj + 1, "N")][0]
            if a > 0 and b > 0:
                uf.union(int(a), int(b))
    u, inv_u = np.unique(local, return_inverse=True)
    root = np.array([uf.find(int(v)) for v in u], np.int64)[inv_u]
    ids, inv, counts = np.unique(root, return_inverse=True, return_counts=True)
    keep = counts[inv] >= prm.min_buildings
    # dense cluster ids, ordered by the north-west-most pixel of each cluster: independent of input order
    pix = lr * 10**7 + lc
    first = pd.Series(pix[keep]).groupby(root[keep]).min()
    rank = pd.Series(np.argsort(np.argsort(first.values)), index=first.index)
    member = np.full(len(x), -1, np.int64)
    member[keep] = rank.reindex(root[keep]).values
    df = pd.DataFrame({"cluster": member[keep], "x": x[keep], "y": y[keep]})
    clusters = df.groupby("cluster").agg(n_buildings=("x", "size"), x=("x", "mean"), y=("y", "mean")).reset_index()
    if not polygons or gpd is None:
        return member, clusters
    root_to_cluster = dict(zip(rank.index.tolist(), rank.values.tolist()))
    pieces: dict = {}
    for ti, tj, lab, rr0, cc0 in tile_parts:
        tf = Affine(s, 0, cc0 * s, 0, -s, -rr0 * s)
        mask = lab > 0
        if not mask.any():
            continue
        # relabel to global cluster id (or 0) before polygonising
        u, inv_l = np.unique(lab, return_inverse=True)
        gid = np.array([root_to_cluster.get(uf.find(int(v)), -1) + 1 if v else 0 for v in u], np.int32)
        glab = gid[inv_l].reshape(lab.shape)
        for geom, val in rasterio.features.shapes(glab, mask=glab > 0, connectivity=8, transform=tf):
            pieces.setdefault(int(val) - 1, []).append(shape(geom))
    geoms = {k: (v[0] if len(v) == 1 else unary_union(v)) for k, v in pieces.items()}
    clusters["geometry"] = clusters.cluster.map(geoms)
    return member, gpd.GeoDataFrame(clusters, geometry="geometry", crs=CRS)
