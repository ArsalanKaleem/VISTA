"""Shared Earth Engine helpers: config, initialisation, AOI, monthly stacking and exports."""
from __future__ import annotations

import json
import re
from pathlib import Path

import ee
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "gee.yaml"
RESOLVED = ROOT / "configs" / "resolved_assets.json"


# --------------------------------------------------------------------------- config / init

def load_config(path: str | Path | None = None) -> dict:
    cfg = yaml.safe_load(Path(path or CONFIG).read_text())
    cfg["_resolved"] = json.loads(RESOLVED.read_text()) if RESOLVED.exists() else {}
    return cfg


def init(cfg: dict) -> None:
    project = cfg["gee"]["project"]
    if not project or project.startswith("YOUR_"):
        raise SystemExit("Set gee.project and gee.asset_root in configs/gee.yaml first.")
    try:
        ee.Initialize(project=project)
    except Exception as exc:  # most common cause: never authenticated on this machine
        raise SystemExit(f"ee.Initialize failed ({exc}).\nRun `earthengine authenticate` "
                         f"(or python -c \"import ee; ee.Authenticate()\") and retry.")


def ds(cfg: dict, key: str) -> str:
    """Dataset ID: resolved by verify-assets if available, else the first candidate."""
    return cfg["_resolved"].get(key) or (cfg["datasets"].get(key) or [None])[0]


def asset(cfg: dict, name: str) -> str:
    return f"{cfg['gee']['asset_root']}/{name}"


def asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def ensure_folder(path: str) -> None:
    """Create an asset folder and its parents (no-op if they exist)."""
    parts = path.split("/")
    # projects/<p>/assets/<a>/<b>...: folders start after 'assets'
    start = parts.index("assets") + 2
    for i in range(start, len(parts) + 1):
        sub = "/".join(parts[:i])
        if not asset_exists(sub):
            ee.data.createAsset({"type": "FOLDER"}, sub)


# --------------------------------------------------------------------------- AOI

def _local_admin(cfg: dict, level: int) -> Path:
    return ROOT / cfg["aoi"]["local_admin_dir"] / f"sindh_adm{level}_simplified.geojson"


def fc_from_geojson(path: Path) -> ee.FeatureCollection:
    """Client-side FeatureCollection (planar geometries) from a small GeoJSON file."""
    gj = json.loads(path.read_text(encoding="utf-8"))
    feats = [ee.Feature(ee.Geometry(f["geometry"], None, False), f.get("properties") or {})
             for f in gj["features"]]
    return ee.FeatureCollection(feats)


def admin(cfg: dict, level: int) -> ee.FeatureCollection:
    """Sindh admin layer (1 province, 2 districts, 3 talukas): asset > local GeoJSON > GAUL/bbox."""
    key = {1: "sindh", 2: "districts", 3: "talukas"}[level]
    aid = asset(cfg, cfg["aoi"]["assets"][key])
    if asset_exists(aid):
        return ee.FeatureCollection(aid)
    local = _local_admin(cfg, level)
    if local.exists():
        return fc_from_geojson(local)
    if level == 1:
        gaul = ee.FeatureCollection(ds(cfg, "fao_gaul_l1")).filter(ee.Filter.eq("ADM1_NAME", "Sindh"))
        return gaul
    raise SystemExit(f"No admin level {level}: run scripts/prepare_admin.py and `gee.run upload-admin`.")


def sindh_geom(cfg: dict) -> ee.Geometry:
    try:
        return admin(cfg, 1).geometry(100)
    except SystemExit:
        return ee.Geometry.Rectangle(cfg["aoi"]["sindh_bbox"], None, False)


def sindh_bbox(cfg: dict) -> ee.Geometry:
    return ee.Geometry.Rectangle(cfg["aoi"]["sindh_bbox"], None, False)


def select_by_name(fc: ee.FeatureCollection, field: str, names: list[str]) -> ee.FeatureCollection:
    """Case-insensitive exact-name filter; prints available names if nothing matches."""
    wanted = [n.lower() for n in names]
    have = fc.aggregate_array(field).getInfo()
    keep = [h for h in have if h and h.lower() in wanted]
    missing = set(wanted) - {k.lower() for k in keep}
    if missing:
        print(f"  not found: {sorted(missing)}\n  available ({len(have)}): {sorted(set(have))}")
    return fc.filter(ee.Filter.inList(field, keep))


# --------------------------------------------------------------------------- time stacks

def month_window(year: int, month: int) -> tuple[ee.Date, ee.Date]:
    start = ee.Date.fromYMD(year, month, 1)
    return start, start.advance(1, "month")


def band_names(variables: list[str], year: int, months=range(1, 13)) -> list[str]:
    return [f"{v}_{year}{m:02d}" for m in months for v in variables]


def empty(variables: list[str]) -> ee.Image:
    """Fully masked float image used when a month has no observations."""
    return ee.Image.constant([0] * len(variables)).rename(variables).toFloat().updateMask(ee.Image(0))


def monthly_stack(col: ee.ImageCollection, year: int, variables: list[str], composite="median",
                  nobs: str | None = "nobs", months=range(1, 13)) -> ee.Image:
    """Stack monthly composites of `variables` into one image named <var>_<YYYYMM>.

    `col` must already contain the variables as bands and a system:time_start that equals
    the date the information became available (window end for MODIS composites).
    nobs (number of valid observations per pixel) is added when `nobs` is a band name.
    """
    out = []
    names = variables + ([nobs] if nobs else [])
    for m in months:
        start, end = month_window(year, m)
        sub = col.filterDate(start, end).select(variables)
        reducer = {"median": sub.median, "mean": sub.mean, "max": sub.max,
                   "min": sub.min, "sum": sub.sum}[composite]
        comp = reducer().toFloat()
        if nobs:
            comp = comp.addBands(sub.select(variables[0]).count().rename(nobs).toFloat())
        img = ee.Image(ee.Algorithms.If(sub.size().gt(0), comp.rename(names), empty(names)))
        out.append(img.rename([f"{n}_{year}{m:02d}" for n in names]))
    return ee.Image.cat(out)


def shift_to_window_end(col: ee.ImageCollection, days: int) -> ee.ImageCollection:
    """Re-stamp composites with their END date (availability) instead of the start date."""
    def f(im):
        start = ee.Date(im.get("system:time_start"))
        return im.set({"window_start": start.millis(),
                       "system:time_start": start.advance(days, "day").millis()})
    return col.map(f)


# --------------------------------------------------------------------------- exports

def clean_desc(text: str) -> str:
    """Earth Engine task descriptions: <= 100 chars of [A-Za-z0-9_-.,:;]."""
    return re.sub(r"[^A-Za-z0-9_\-.,:;]", "_", text)[:100]


def export_table(cfg: dict, fc: ee.FeatureCollection, desc: str, subfolder: str,
                 selectors: list[str] | None = None, fmt: str = "CSV") -> ee.batch.Task:
    desc = clean_desc(desc)
    bucket = cfg["gee"].get("gcs_bucket")
    if bucket:
        return ee.batch.Export.table.toCloudStorage(
            collection=fc, description=desc, bucket=bucket,
            fileNamePrefix=f"{cfg['gee']['drive_folder']}/{subfolder}/{desc}",
            fileFormat=fmt, selectors=selectors)
    return ee.batch.Export.table.toDrive(
        collection=fc, description=desc, folder=f"{cfg['gee']['drive_folder']}_{subfolder}",
        fileNamePrefix=desc, fileFormat=fmt, selectors=selectors)


def export_image(cfg: dict, img: ee.Image, desc: str, subfolder: str, region: ee.Geometry,
                 scale: float | None = None, crs: str = "EPSG:4326",
                 crs_transform: list | None = None) -> ee.batch.Task:
    desc = clean_desc(desc)
    kw = dict(image=img, description=desc, region=region, crs=crs, maxPixels=1e13,
              fileFormat="GeoTIFF", formatOptions={"cloudOptimized": True})
    if crs_transform:
        kw["crsTransform"] = crs_transform
    else:
        kw["scale"] = scale
    bucket = cfg["gee"].get("gcs_bucket")
    if bucket:
        return ee.batch.Export.image.toCloudStorage(
            bucket=bucket, fileNamePrefix=f"{cfg['gee']['drive_folder']}/{subfolder}/{desc}", **kw)
    return ee.batch.Export.image.toDrive(
        folder=f"{cfg['gee']['drive_folder']}_{subfolder}", fileNamePrefix=desc, **kw)


def export_table_to_asset(fc: ee.FeatureCollection, asset_id: str, desc: str) -> ee.batch.Task:
    return ee.batch.Export.table.toAsset(collection=fc, description=clean_desc(desc), assetId=asset_id)
