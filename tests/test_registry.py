"""Day 18 checklist on the built registry: 0 duplicate VIDs, IDs identical after rerun, no crosswalk orphans.

Skipped when the registry has not been built on this machine (data are not in Git).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.village_mapping.ids import geohash, make_vids, spatial_key  # noqa: E402

REG = ROOT / "data/village_inventory/registry"
needs_registry = pytest.mark.skipif(not (REG / "village_registry.parquet").exists(), reason="registry not built")


def _reg():
    return pd.read_parquet(REG / "village_registry.parquet",
                           columns=["vid", "vvid", "district_code", "taluka_code", "lat", "lon"])


def test_scheme_is_explicit():
    assert spatial_key(24.8, 69.92, "geohash") == "g" + geohash(24.8, 69.92, 9)
    assert make_vids([("05", "001", 24.8, 69.92)], prefix="SV")[0].startswith("SV05001")


@needs_registry
def test_no_duplicate_vids():
    r = _reg()
    assert r.vid.is_unique and r.vid.notna().all()


@needs_registry
def test_vids_identical_after_rerun():
    r = _reg()
    again = make_vids(list(zip(r.district_code, r.taluka_code, r.lat, r.lon)))
    assert again == r.vid.tolist()


@needs_registry
def test_crosswalks_have_no_orphans():
    vids = set(_reg().vid)
    for f in ("vid_cluster.csv", "vid_deh.csv"):
        cw = pd.read_csv(REG / "crosswalks" / f)
        assert set(cw.vid) <= vids, f
    pilot = pd.read_csv(REG / "crosswalks/vid_pilot_v0.csv")
    assert set(pilot.vid.dropna()) <= vids


@needs_registry
def test_name_resolution_consistent():
    r = pd.read_parquet(REG / "village_registry.parquet", columns=["vid", "name", "name_status", "registry_version"])
    if "name_status" not in r or r.registry_version.iloc[0] < "v0.6":
        pytest.skip("dedupe_inventory.py not run")
    assert set(r.name_status) <= {"unnamed", "unique", "homonym", "village_shared", "conflict_kept", "conflict_dropped"}
    assert r[r.name_status == "conflict_dropped"].name.isna().all()
    assert r[r.name_status == "unnamed"].name.isna().all()


@needs_registry
def test_every_vid_has_quality_class():
    r = pd.read_parquet(REG / "village_registry.parquet")
    if "quality_class" not in r:
        pytest.skip("quality_classes.py not run")
    assert r.quality_class.isin(["Q1", "Q2", "Q3"]).all()
    q12 = r[r.quality_class != "Q3"]
    assert (q12.n_buildings >= 10).all() and (q12.mean_conf >= 0.70).all()
