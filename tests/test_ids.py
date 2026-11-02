"""Day 18: VIDs are unique and identical across reruns."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.village_mapping.ids import geohash, make_vids  # noqa: E402


def test_geohash_reference():
    assert geohash(57.64911, 10.40744, 11) == "u4pruydqqvj"


def test_vids_stable_and_unique():
    rows = [("01", "002", 24.80001, 69.92), ("01", "002", 24.80001, 69.92), ("03", "010", 26.8, 67.7)]
    a, b = make_vids(rows), make_vids(list(rows))
    assert a == b and len(set(a)) == len(a)
    assert all(v.startswith("SD") for v in a)
