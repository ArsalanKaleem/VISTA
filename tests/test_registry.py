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
