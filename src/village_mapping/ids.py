"""Village identifiers (Day 18, Section 5.5).

VID = 'SD' + district code (2) + taluka code (3) + H3 res-10 cell of the centroid + 2-char
disambiguator. IDs never encode names and must be identical across reruns (tests/test_ids.py).
Fallback when h3 is unavailable: geohash level 9 (Day 18 fallback).
"""
from __future__ import annotations

import string

_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DIS = string.digits + string.ascii_uppercase


def geohash(lat: float, lon: float, precision: int = 9) -> str:
    lat_r, lon_r, bits, out, even, bit, ch = [-90.0, 90.0], [-180.0, 180.0], [16, 8, 4, 2, 1], [], True, 0, 0
    while len(out) < precision:
        rng, val = (lon_r, lon) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val > mid:
            ch |= bits[bit]
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(_B32[ch])
            bit, ch = 0, 0
    return "".join(out)


def spatial_key(lat: float, lon: float) -> str:
    try:
        import h3
        return h3.latlng_to_cell(lat, lon, 10)
    except ImportError:
        return "g" + geohash(lat, lon, 9)


def make_vids(rows: list[tuple[str, str, float, float]]) -> list[str]:
    """rows: (district_code, taluka_code, lat, lon) in a deterministic order -> VIDs.

    Ties within the same spatial key are broken by rounded centroid (1e-5 deg), then order.
    """
    keyed = []
    for i, (d, t, lat, lon) in enumerate(rows):
        base = f"SD{str(d).zfill(2)[:2]}{str(t).zfill(3)[:3]}{spatial_key(lat, lon)}"
        keyed.append((base, round(lat, 5), round(lon, 5), i))
    vids = [""] * len(rows)
    seen: dict[str, int] = {}
    for base, _, _, i in sorted(keyed):
        n = seen.get(base, 0)
        seen[base] = n + 1
        vids[i] = base + _DIS[n // 36] + _DIS[n % 36]
    return vids
