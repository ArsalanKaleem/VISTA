"""Download the small, open reference datasets the plan needs locally (Days 8, 11-13).

Every file lands in data/raw/<source>/ and is recorded in data/raw/manifest.csv
(path, sha256, bytes, source URL, UTC date) as required by Section 9.4.

Large sources (Geofabrik PBF, Microsoft/Overture footprints) are opt-in via
--large because they need several hundred MB to tens of GB of disk.

Usage:
    python scripts/download_data.py            # small set
    python scripts/download_data.py --large    # also the Geofabrik Pakistan PBF
    python scripts/download_data.py --only geonames pbs
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "manifest.csv"
UA = {"User-Agent": "VISTA-Sindh research data fetch (python-requests)"}

GEOBOUNDARIES_API = "https://www.geoboundaries.org/api/current/gbOpen/PAK/{level}/"
HDX_API = "https://data.humdata.org/api/3/action/package_show?id={pkg}"

SMALL = {
    "pbs": [
        ("pbs/mouza_census_2020_sindh_report.pdf",
         "https://www.pbs.gov.pk/wp-content/uploads/2020/07/mouza_census_2020_sindh_report.pdf"),
        ("pbs/mouza_census_2020_country_report.pdf",
         "https://www.pbs.gov.pk/wp-content/uploads/2020/07/mouza_census_2020_country_report.pdf"),
    ],
    "geonames": [
        ("geonames/PK.zip", "https://download.geonames.org/export/dump/PK.zip"),
        ("geonames/admin1CodesASCII.txt", "https://download.geonames.org/export/dump/admin1CodesASCII.txt"),
        ("geonames/featureCodes_en.txt", "https://download.geonames.org/export/dump/featureCodes_en.txt"),
    ],
}
LARGE = {
    "osm": [
        ("osm/pakistan-latest.osm.pbf", "https://download.geofabrik.de/asia/pakistan-latest.osm.pbf"),
    ],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def record(path: Path, url: str) -> None:
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["path", "sha256", "bytes", "source", "downloaded_utc"])
        w.writerow([path.relative_to(ROOT).as_posix(), sha256(path), path.stat().st_size, url,
                    dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")])


def fetch(rel: str, url: str, min_free_mb: int = 300) -> Path | None:
    dest = RAW / rel
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  skip (exists) {rel}")
        return dest
    free_mb = shutil.disk_usage(RAW).free / 2**20
    if free_mb < min_free_mb:
        print(f"  SKIP {rel}: only {free_mb:.0f} MB free (< {min_free_mb} MB)")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, headers=UA, stream=True, timeout=120) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        tmp.replace(dest)
    except Exception as exc:  # keep going; failures are reported in the summary
        tmp.unlink(missing_ok=True)
        print(f"  FAIL {rel}: {exc}")
        return None
    record(dest, url)
    print(f"  ok   {rel} ({dest.stat().st_size / 2**20:.1f} MB)")
    return dest


def geoboundaries() -> list[tuple[str, str]]:
    """Resolve geoBoundaries gbOpen PAK ADM1-3 (full + simplified GeoJSON) via the API."""
    out = []
    for level in ("ADM1", "ADM2", "ADM3"):
        try:
            meta = requests.get(GEOBOUNDARIES_API.format(level=level), headers=UA, timeout=60).json()
        except Exception as exc:
            print(f"  FAIL geoBoundaries {level} metadata: {exc}")
            continue
        (RAW / "geoboundaries").mkdir(parents=True, exist_ok=True)
        (RAW / "geoboundaries" / f"PAK_{level}_meta.json").write_text(json.dumps(meta, indent=2))
        out.append((f"geoboundaries/PAK_{level}.geojson", meta["gjDownloadURL"]))
        if meta.get("simplifiedGeometryGeoJSON"):
            out.append((f"geoboundaries/PAK_{level}_simplified.geojson", meta["simplifiedGeometryGeoJSON"]))
    return out


def hdx_cod_ab() -> list[tuple[str, str]]:
    """Resolve the OCHA COD-AB Pakistan shapefile/geopackage resource URLs from HDX."""
    try:
        pkg = requests.get(HDX_API.format(pkg="cod-ab-pak"), headers=UA, timeout=60).json()["result"]
    except Exception as exc:
        print(f"  FAIL HDX cod-ab-pak metadata: {exc}")
        return []
    (RAW / "hdx").mkdir(parents=True, exist_ok=True)
    (RAW / "hdx" / "cod-ab-pak_meta.json").write_text(json.dumps(pkg, indent=2))
    out = []
    for res in pkg.get("resources", []):
        name = res.get("name", "")
        fmt = (res.get("format") or "").lower()
        size = res.get("size") or 0
        # Prefer compact vector formats; skip anything above 150 MB (disk is tight).
        if fmt in {"shp", "zipped shapefile", "geopackage", "gpkg", "geojson", "xlsx"} and size < 150 * 2**20:
            out.append((f"hdx/{name}", res["url"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--large", action="store_true", help="also fetch large sources (OSM PBF)")
    ap.add_argument("--only", nargs="*", help="subset: pbs geonames geoboundaries hdx osm")
    args = ap.parse_args()

    groups = dict(SMALL)
    groups["geoboundaries"] = None  # resolved lazily
    groups["hdx"] = None
    if args.large:
        groups.update(LARGE)
    if args.only:
        groups = {k: v for k, v in groups.items() if k in args.only}

    RAW.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, items in groups.items():
        print(f"[{name}]")
        if name == "geoboundaries":
            items = geoboundaries()
        elif name == "hdx":
            items = hdx_cod_ab()
        for rel, url in items:
            if fetch(rel, url, min_free_mb=2000 if name == "osm" else 300) is None:
                failed.append(rel)
    print("\nfailed:" if failed else "\nall downloads ok", *failed, sep="\n  ")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
