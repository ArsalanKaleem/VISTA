"""Interactive (non-batch) Earth Engine steps: Day 6 check, Day 8 asset verification,
Day 10 five-point smoke test, and asset uploads (admin boundaries, village zones)."""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path

import ee

from .lib import optical, radar
from .lib.common import (RESOLVED, ROOT, asset, asset_exists, ds, ensure_folder,
                         export_table, export_table_to_asset, fc_from_geojson, sindh_bbox)
from .lib.manifest import Submitter


def _date(ms) -> str:
    # epoch + timedelta: fromtimestamp() fails on Windows for pre-1970 dates (ERA5-Land starts 1950)
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return (epoch + dt.timedelta(milliseconds=ms)).strftime("%Y-%m-%d") if ms is not None else ""


# --------------------------------------------------------------------------- Day 6

def check(cfg: dict, dry_run: bool = False) -> None:
    """reduceRegion on a 10 km box in Sindh + a tiny Drive export (Day 6 acceptance)."""
    box = ee.Geometry.Rectangle([68.30, 25.35, 68.39, 25.44], None, False)  # near Hyderabad
    print("project:", cfg["gee"]["project"])
    img = optical.s2_year_stack(cfg, 2023, box).select("ndvi_2023.*")
    vals = img.reduceRegion(ee.Reducer.mean(), box, 100, bestEffort=True).getInfo()
    print("S2 monthly NDVI 2023 over test box:", {k: round(v, 3) for k, v in vals.items() if v is not None})
    try:
        ensure_folder(cfg["gee"]["asset_root"])
        print("asset root ok:", cfg["gee"]["asset_root"])
    except ee.EEException as exc:
        # Drive exports still work; only asset uploads/exports need the folder.
        print(f"WARNING asset root not writable ({exc}). Check the account's Earth Engine "
              "role on the project (Owner or Earth Engine Resource Admin/Writer).")
    fc = ee.FeatureCollection([ee.Feature(box, {"name": "smoke_box"})])
    table = img.reduceRegions(fc, ee.Reducer.mean(), 100)
    sub = Submitter(cfg, dry_run=dry_run)
    sub.submit(export_table(cfg, table, "smoke_test_export", "smoke"), job="check", product="smoke")
    print("quota note: record EECU/concurrent-task limits from the Cloud console in docs/compute.md")


# --------------------------------------------------------------------------- Day 8

def _describe(asset_id: str, region: ee.Geometry) -> dict:
    meta = ee.data.getAsset(asset_id)
    kind = meta["type"]
    row = {"id": asset_id, "type": kind}
    if kind == "IMAGE_COLLECTION":
        col = ee.ImageCollection(asset_id).filterBounds(region)
        first = col.sort("system:time_start").first()
        last = col.sort("system:time_start", False).first()
        info = ee.Dictionary({
            "n_images_sindh": col.size(),
            "first": first.get("system:time_start"),
            "last": last.get("system:time_start"),
            "bands": first.bandNames(),
            "scale_m": first.select(0).projection().nominalScale(),
        }).getInfo()
        row.update(info, first=_date(info["first"]), last=_date(info["last"]))
    elif kind == "IMAGE":
        img = ee.Image(asset_id)
        info = ee.Dictionary({"bands": img.bandNames(),
                              "scale_m": img.select(0).projection().nominalScale()}).getInfo()
        row.update(info)
    elif kind == "TABLE":
        fc = ee.FeatureCollection(asset_id).filterBounds(
            ee.Geometry.Rectangle([68.30, 25.35, 68.40, 25.45], None, False))
        info = ee.Dictionary({"n_features_10km_box": fc.size(),
                              "properties": ee.Feature(fc.first()).propertyNames()}).getInfo()
        row.update(info)
    row["bands"] = ",".join(row.get("bands", []) or [])
    if "properties" in row:
        row["properties"] = ",".join(row["properties"])
    return row


def verify_assets(cfg: dict) -> None:
    region = sindh_bbox(cfg)
    rows, resolved = [], {}
    for key, candidates in cfg["datasets"].items():
        for cid in candidates:
            try:
                row = _describe(cid, region)
                row.update(key=key, status="ok")
                resolved.setdefault(key, cid)
                rows.append(row)
                print(f"  ok   {key:20s} {cid}  {row.get('first', '')} .. {row.get('last', '')}")
                break
            except Exception as exc:
                rows.append({"key": key, "id": cid, "status": f"missing: {str(exc)[:120]}"})
                print(f"  MISS {key:20s} {cid}: {str(exc)[:80]}")
    # Specific Day-8 checks
    extra = {}
    try:
        s1 = ee.ImageCollection(ds(cfg, "s1_grd")).filterBounds(region)
        s1b = s1.filter(ee.Filter.eq("platform_number", "B")).sort("system:time_start", False).first()
        extra["s1b_last"] = _date(s1b.get("system:time_start").getInfo())
        extra["s1_orbit_counts_by_year_2014_2026"] = radar.s1_orbit_counts(cfg, region)
    except Exception as exc:
        extra["s1_check_error"] = str(exc)
    try:
        july = ee.ImageCollection(ds(cfg, "era5_land_monthly")).filterDate("2020-07-01", "2020-08-01").first()
        pev = july.select("potential_evaporation_sum").reduceRegion(ee.Reducer.mean(), region, 11132).getInfo()
        extra["era5_pev_jul2020_mean_m"] = pev
        extra["era5_pev_sign_note"] = "negative = ECMWF upward convention (code multiplies by -1000)"
    except Exception as exc:
        extra["era5_check_error"] = str(exc)

    RESOLVED.write_text(json.dumps(resolved, indent=2))
    out_csv = ROOT / "outputs" / "tables" / "assets_verification.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = ["key", "id", "status", "type", "first", "last", "n_images_sindh", "bands", "scale_m",
              "n_features_10km_box", "properties"]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    report = ROOT / "documentation" / "assets_report.md"
    lines = [f"# Earth Engine asset verification ({dt.date.today()})", "",
             "Generated by `python -m gee.run verify-assets`. Dates come from the API, not memory.", "",
             "| key | id | status | first | last | n (Sindh) | scale m |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['key']} | `{r['id']}` | {r['status']} | {r.get('first', '')} | {r.get('last', '')} "
                     f"| {r.get('n_images_sindh', r.get('n_features_10km_box', ''))} | "
                     f"{round(r['scale_m'], 1) if r.get('scale_m') else ''} |")
    lines += ["", "## Specific checks", "", "```json", json.dumps(extra, indent=2), "```"]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {RESOLVED.name}, {out_csv.relative_to(ROOT)}, {report.relative_to(ROOT)}")


# --------------------------------------------------------------------------- Day 10

def smoke5(cfg: dict, years=(2019, 2024), test_year: int = 2023) -> None:
    """S2 NDVI monthly series at 5 points -> table -> train-only climatology -> MAE.

    Leakage guard (reused on Day 66): the climatology uses only years < test_year.
    """
    pts = cfg["aoi"]["smoke_points"]
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point(xy).buffer(1000), {"vid": k}) for k, xy in pts.items()])
    region = fc.geometry().bounds()
    rows = []
    for y in range(years[0], years[1] + 1):
        img = optical.s2_year_stack(cfg, y, region).select("ndvi_.*|nobs_.*")
        res = img.reduceRegions(fc, ee.Reducer.mean(), 20, tileScale=4).getInfo()
        for f in res["features"]:
            p = f["properties"]
            for m in range(1, 13):
                rows.append({"vid": p["vid"], "year": y, "month": m,
                             "ndvi": p.get(f"ndvi_{y}{m:02d}"), "nobs": p.get(f"nobs_{y}{m:02d}")})
        print(f"  {y}: {len(res['features'])} points")
    out = ROOT / "data" / "processed" / "smoke_s2_ndvi.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["vid", "year", "month", "ndvi", "nobs"])
        w.writeheader()
        w.writerows(rows)
    try:  # Parquet if pandas/pyarrow are installed
        import pandas as pd
        pd.DataFrame(rows).to_parquet(out.with_suffix(".parquet"), index=False)
    except Exception:
        pass

    train = [r for r in rows if r["year"] < test_year and r["ndvi"] is not None]
    assert all(r["year"] < test_year for r in train), "leakage: climatology saw test years"
    clim: dict[tuple, list] = {}
    for r in train:
        clim.setdefault((r["vid"], r["month"]), []).append(r["ndvi"])
    errs = []
    for r in rows:
        if r["year"] >= test_year and r["ndvi"] is not None and (r["vid"], r["month"]) in clim:
            ref = sum(clim[(r["vid"], r["month"])]) / len(clim[(r["vid"], r["month"])])
            errs.append(abs(r["ndvi"] - ref))
    mae = sum(errs) / len(errs) if errs else math.nan
    rep = ROOT / "documentation" / "smoke_test_report.md"
    rep.write_text(
        f"# Smoke test ({dt.date.today()})\n\n"
        f"- Points: {', '.join(pts)} (1 km buffers)\n- S2 NDVI monthly {years[0]}-{years[1]} -> `{out.relative_to(ROOT)}`\n"
        f"- Climatology fitted on years < {test_year} only (assertion passed)\n"
        f"- Climatology MAE on {test_year}-{years[1]}: {mae:.4f} (n = {len(errs)} point-months)\n"
        f"- Missing point-months (no valid S2): {sum(r['ndvi'] is None for r in rows)} of {len(rows)}\n",
        encoding="utf-8")
    print(f"climatology MAE {mae:.4f} over {len(errs)} point-months; report -> {rep.relative_to(ROOT)}")


# --------------------------------------------------------------------------- uploads

def _features_from_file(path: Path, simplify_m: float | None) -> list[dict]:
    """GeoJSON natively; GPKG/Parquet/SHP via geopandas (simplified in UTM 42N)."""
    if path.suffix.lower() in (".geojson", ".json") and not simplify_m:
        return json.loads(path.read_text(encoding="utf-8"))["features"]
    import geopandas as gpd  # only needed for non-GeoJSON or simplification
    gdf = gpd.read_parquet(path) if path.suffix == ".parquet" else gpd.read_file(path)
    if simplify_m:
        gdf = gdf.to_crs(32642)
        gdf["geometry"] = gdf.geometry.simplify(simplify_m, preserve_topology=True)
    gdf = gdf.to_crs(4326)
    # reprojection/simplification can leave self-intersections; repair in the upload CRS
    gdf["geometry"] = gdf.geometry.make_valid().buffer(0)
    gdf = gdf[~gdf.geometry.is_empty]
    return json.loads(gdf.to_json(drop_id=True))["features"]


def upload_features(cfg: dict, features: list[dict], name: str, part_size: int = 500,
                    keep: list[str] | None = None, dry_run: bool = False) -> None:
    """Client-side upload in parts: <asset_root>/<name>/part_000, part_001, ...

    Zonal jobs read a folder of parts as one collection (merge on read), so no GCS bucket
    or second merge step is needed. Large uploads: consider `earthengine upload table` via GCS.
    """
    folder = asset(cfg, name)
    if not dry_run:
        ensure_folder(folder)
    sub = Submitter(cfg, dry_run=dry_run)
    for i in range(0, len(features), part_size):
        part = features[i:i + part_size]
        for f in part:
            if keep:
                f["properties"] = {k: f["properties"].get(k) for k in keep}
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry(f["geometry"], None, False), f["properties"])
                                   for f in part])
        pid = f"{folder}/part_{i // part_size:03d}"
        if not dry_run and asset_exists(pid):
            print(f"  exists {pid}")
            continue
        sub.submit(export_table_to_asset(fc, pid, f"upload_{name.replace('/', '_')}_{i // part_size:03d}"),
                   job="upload", product=name, chunk=i // part_size, destination=pid)


def upload_admin(cfg: dict, dry_run: bool = False) -> None:
    for level, key in ((1, "sindh"), (2, "districts"), (3, "talukas")):
        path = ROOT / cfg["aoi"]["local_admin_dir"] / f"sindh_adm{level}_simplified.geojson"
        aid = asset(cfg, cfg["aoi"]["assets"][key])
        if not dry_run:
            ensure_folder(aid.rsplit("/", 1)[0])
            if asset_exists(aid):
                print(f"  exists {aid}")
                continue
        fc = fc_from_geojson(path)
        Submitter(cfg, dry_run=dry_run).submit(
            export_table_to_asset(fc, aid, f"upload_admin_adm{level}"), job="upload_admin",
            product="admin", chunk=level, destination=aid)


def upload_zones(cfg: dict, path: Path, name: str, dry_run: bool = False, part_size: int = 500) -> None:
    """Upload village zones with vid, zone and a deterministic chunk index (sorted by vid)."""
    z = cfg["zones"]
    feats = _features_from_file(path, z["simplify_m"])
    for f in feats:
        p = f["properties"]
        if z["id_field"] not in p or z["zone_field"] not in p:
            raise SystemExit(f"each feature needs '{z['id_field']}' and '{z['zone_field']}' properties")
    feats.sort(key=lambda f: (str(f["properties"][z["id_field"]]), str(f["properties"][z["zone_field"]])))
    vids = sorted({str(f["properties"][z["id_field"]]) for f in feats})
    idx = {v: i // z["base_chunk_size"] for i, v in enumerate(vids)}
    for f in feats:
        f["properties"][z["chunk_field"]] = idx[str(f["properties"][z["id_field"]])]
    print(f"  {len(feats)} zone features, {len(vids)} villages, {max(idx.values()) + 1} chunks")
    keep = [z["id_field"], z["zone_field"], z["chunk_field"]]
    upload_features(cfg, feats, name, part_size=part_size, keep=keep, dry_run=dry_run)
