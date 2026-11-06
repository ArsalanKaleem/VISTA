"""Days 14-15: tiled settlement clustering equals single-tile clustering; distance rule behaves."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.village_mapping.settlements import Params, cluster  # noqa: E402


def _partition(member):
    """Set of frozensets of building indices: comparable across different id numbering."""
    out = {}
    for i, m in enumerate(member):
        if m >= 0:
            out.setdefault(m, []).append(i)
    return {frozenset(v) for v in out.values()}


def test_distance_rule():
    # 5 buildings in a row 50 m apart join; a sixth 200 m further does not
    x = np.array([500000.0 + 50 * k for k in range(5)] + [500000.0 + 50 * 4 + 200])
    y = np.full(6, 2_700_000.0)
    member, cl = cluster(x, y, Params(dilate_m=40, min_buildings=5), polygons=False)
    assert len(cl) == 1 and cl.n_buildings.iloc[0] == 5
    assert member[-1] == -1


def test_tiles_equal_single_tile():
    rng = np.random.default_rng(0)
    # clumps of buildings scattered over ~6 km, many straddling 1 km tile seams
    centres = rng.uniform(0, 6000, size=(60, 2))
    pts = np.concatenate([c + rng.normal(0, 60, size=(rng.integers(3, 40), 2)) for c in centres])
    x, y = 400000 + pts[:, 0], 2_800_000 + pts[:, 1]
    big, cb = cluster(x, y, Params(tile_px=5000), polygons=False)
    small, cs = cluster(x, y, Params(tile_px=100), polygons=False)  # 1 km tiles
    assert _partition(big) == _partition(small)
    assert len(cb) == len(cs) and cb.n_buildings.sum() == cs.n_buildings.sum()


def test_ids_independent_of_order():
    rng = np.random.default_rng(1)
    pts = rng.uniform(0, 3000, size=(800, 2))
    x, y = 400000 + pts[:, 0], 2_800_000 + pts[:, 1]
    a, _ = cluster(x, y, Params(min_buildings=3), polygons=False)
    perm = rng.permutation(len(x))
    b, _ = cluster(x[perm], y[perm], Params(min_buildings=3), polygons=False)
    assert np.array_equal(a[perm], b)


def test_polygons_cover_members():
    rng = np.random.default_rng(2)
    centres = rng.uniform(0, 4000, size=(20, 2))
    pts = np.concatenate([c + rng.normal(0, 40, size=(15, 2)) for c in centres])
    x, y = 400000 + pts[:, 0], 2_800_000 + pts[:, 1]
    member, gdf = cluster(x, y, Params(tile_px=150), polygons=True)
    assert gdf.geometry.notna().all() and gdf.is_valid.all()
    import shapely
    pts_g = shapely.points(x, y)
    for _, r in gdf.iterrows():
        inside = shapely.contains(r.geometry.buffer(1e-6), pts_g[member == r.cluster])
        assert inside.all()
