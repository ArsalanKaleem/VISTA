"""Village zones (Day 23): core C_i, resource R_i (Section 5.6). Code from Section 12.3.

core      = settlement polygon buffered by core_buf (default 100 m; sensitivity 50-200 m)
resource  = (Voronoi cell of the settlement centroid within the boundary) n buffer(S_i, r_max)
            minus all foreign cores; r_max = 2 km default, 3-5 km in the Thar
Connectivity corridors (K_i) are built on Day 23 from OSM roads/canals (graph_construction).
"""
from __future__ import annotations

import geopandas as gpd
from shapely import MultiPoint, voronoi_polygons
from shapely.ops import unary_union
from shapely.strtree import STRtree

UTM = 32642  # UTM 42N for metric work


def make_zones(settl: gpd.GeoDataFrame, boundary_gdf: gpd.GeoDataFrame,
               r_max: float = 2000.0, core_buf: float = 100.0) -> gpd.GeoDataFrame:
    s = settl.to_crs(UTM).copy()
    boundary = boundary_gdf.to_crs(UTM).geometry.union_all()
    cent = gpd.GeoDataFrame(geometry=s.geometry.centroid, crs=UTM).reset_index(names="sid")
    cells = gpd.GeoDataFrame(
        geometry=list(voronoi_polygons(MultiPoint(list(cent.geometry)), extend_to=boundary).geoms), crs=UTM)
    vor = cells.sjoin(cent, predicate="contains").set_index("sid").geometry  # one cell per settlement
    s["core"] = s.geometry.buffer(core_buf)
    tree = STRtree(s["core"].values)
    res = []
    for pos, (i, row) in enumerate(s.iterrows()):
        area = vor.loc[i].intersection(row.geometry.buffer(r_max)).intersection(boundary)
        hit = [h for h in tree.query(area, predicate="intersects") if h != pos]
        res.append(area.difference(unary_union(s["core"].values[hit])) if hit else area)
    s["resource"] = res
    return s


def zones_long(s: gpd.GeoDataFrame, id_col: str = "vid") -> gpd.GeoDataFrame:
    """One row per (vid, zone) for upload to Earth Engine."""
    core = gpd.GeoDataFrame({id_col: s[id_col], "zone": "core"}, geometry=s["core"], crs=UTM)
    res = gpd.GeoDataFrame({id_col: s[id_col], "zone": "resource"}, geometry=s["resource"], crs=UTM)
    out = gpd.GeoDataFrame(gpd.pd.concat([core, res], ignore_index=True), crs=UTM)
    out = out[~out.geometry.is_empty & out.geometry.notna()]
    out["area_m2"] = out.geometry.area
    return out
