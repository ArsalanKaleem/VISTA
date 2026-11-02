"""Extract Sindh province, district and taluka layers from geoBoundaries (Day 12 starter).

Pure Python (no geopandas) so it runs before the full environment exists. A feature is kept
when the area-weighted centroid of its largest polygon lies inside the Sindh polygon.
Writes data/village_inventory/admin/sindh_adm{1,2,3}[_simplified].geojson and a name list.

    python scripts/prepare_admin.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "raw" / "geoboundaries"
OUT = ROOT / "data" / "village_inventory" / "admin"


def polygons(geom: dict) -> list[list[list[list[float]]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-15:
        xs, ys = zip(*ring)
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a), cx / (6 * a), cy / (6 * a)


def rep_point(geom: dict) -> tuple[float, float]:
    best = max((ring_area_centroid(p[0]) for p in polygons(geom)), key=lambda t: t[0])
    return best[1], best[2]


def point_in_ring(x: float, y: float, ring) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def point_in_geom(x: float, y: float, geom: dict) -> bool:
    for poly in polygons(geom):
        if point_in_ring(x, y, poly[0]) and not any(point_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def load(name: str) -> dict:
    return json.loads((SRC / name).read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    adm1 = load("PAK_ADM1.geojson")
    sindh = [f for f in adm1["features"] if "sindh" in f["properties"]["shapeName"].lower()]
    if len(sindh) != 1:
        raise SystemExit(f"expected one Sindh feature, got {[f['properties']['shapeName'] for f in sindh]}")
    sgeom = sindh[0]["geometry"]
    names = []
    for level in (1, 2, 3):
        for suffix in ("", "_simplified"):
            src = SRC / f"PAK_ADM{level}{suffix}.geojson"
            if not src.exists():
                continue
            gj = load(src.name)
            keep = []
            for f in gj["features"]:
                if level == 1:
                    ok = "sindh" in f["properties"]["shapeName"].lower()
                else:
                    ok = point_in_geom(*rep_point(f["geometry"]), sgeom)
                if ok:
                    f["properties"]["adm_level"] = level
                    keep.append(f)
            out = OUT / f"sindh_adm{level}{suffix}.geojson"
            out.write_text(json.dumps({"type": "FeatureCollection", "features": keep}), encoding="utf-8")
            print(f"{out.relative_to(ROOT)}: {len(keep)} features")
            if suffix == "":
                names += [(level, f["properties"]["shapeName"], f["properties"].get("shapeID", "")) for f in keep]
    with (OUT / "sindh_admin_names.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["adm_level", "name", "shapeID"])
        w.writerows(names)


if __name__ == "__main__":
    main()
