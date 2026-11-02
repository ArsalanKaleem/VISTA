"""Zonal-statistics framework (Day 26): yearly multi-band stacks reduced once per zone chunk.

Zones asset schema (written by `gee.run upload-zones`): one feature per village zone with
properties vid, zone (core|resource|connectivity) and chunk (int, sorted by vid).
Each export task reduces one product-year stack over a group of chunks and writes a wide CSV:
    vid, zone, chunk, <var>_<YYYYMM>_mean, <var>_<YYYYMM>_count, ...
scripts/gee_to_long.py converts these into the long Parquet schema of the plan
(vid, zone, date_start, date_end, available_at, product, band, stat, value, n_valid).
"""
from __future__ import annotations

from typing import Callable

import ee

from .common import asset, export_table

STATS = {
    "mean": ee.Reducer.mean,
    "count": ee.Reducer.count,
    "median": ee.Reducer.median,
    "sum": ee.Reducer.sum,
    "min": ee.Reducer.min,
    "max": ee.Reducer.max,
    "stdDev": ee.Reducer.stdDev,
}


def reducer(stats: list[str]) -> ee.Reducer:
    red = STATS[stats[0]]()
    for s in stats[1:]:
        red = red.combine(STATS[s](), sharedInputs=True)
    return red


def zones_fc(cfg: dict, zones_name: str, zone_types: list[str] | None = None) -> ee.FeatureCollection:
    """Zones table, or a folder of uploaded parts merged on read."""
    aid = asset(cfg, zones_name)
    if ee.data.getAsset(aid)["type"] == "FOLDER":
        parts = [a["name"] for a in ee.data.listAssets({"parent": aid})["assets"] if a["type"] == "TABLE"]
        fc = ee.FeatureCollection([ee.FeatureCollection(x) for x in sorted(parts)]).flatten()
    else:
        fc = ee.FeatureCollection(aid)
    if zone_types:
        fc = fc.filter(ee.Filter.inList(cfg["zones"]["zone_field"], zone_types))
    return fc


def chunk_ranges(cfg: dict, fc: ee.FeatureCollection, group: int) -> list[tuple[int, int]]:
    n = int(ee.Number(fc.aggregate_max(cfg["zones"]["chunk_field"])).getInfo()) + 1
    return [(a, min(a + group, n) - 1) for a in range(0, n, group)]


def chunk(cfg: dict, fc: ee.FeatureCollection, lo: int, hi: int) -> ee.FeatureCollection:
    f = cfg["zones"]["chunk_field"]
    return fc.filter(ee.Filter.And(ee.Filter.gte(f, lo), ee.Filter.lte(f, hi)))


def selectors(cfg: dict, band_names: list[str], stats: list[str]) -> list[str]:
    z = cfg["zones"]
    if len(band_names) == 1:  # single-band images get bare stat names from Earth Engine
        return [z["id_field"], z["zone_field"], z["chunk_field"], *stats]
    return [z["id_field"], z["zone_field"], z["chunk_field"],
            *[f"{b}_{s}" for b in band_names for s in stats]]


def submit_zonal(cfg: dict, submitter, *, job: str, product: str, zones_name: str,
                 image_fn: Callable[[int | None, ee.Geometry], ee.Image],
                 band_fn: Callable[[int | None], list[str]], years: list[int | None],
                 scale: float, group: int, stats=("mean", "count"),
                 zone_types: list[str] | None = None) -> None:
    """Submit one table export per (year, chunk group).

    image_fn(year, region) builds the stack (region = chunk bounds, for filterBounds);
    band_fn(year) returns its band names client-side (used for CSV selectors).
    Use years=[None] for static products.
    """
    fc = zones_fc(cfg, zones_name, zone_types)
    ranges = chunk_ranges(cfg, fc, group)
    stats = list(stats)
    if len(stats) == 1:  # a lone reducer names columns by band only; keep <band>_<stat> naming
        stats.append("count")
    red = reducer(stats)
    print(f"  {product}: {len(years)} period(s) x {len(ranges)} chunk group(s) on {zones_name}")
    for year in years:
        bands = band_fn(year)
        sel = selectors(cfg, bands, stats)
        for lo, hi in ranges:
            sub = chunk(cfg, fc, lo, hi)
            region = sub.geometry(100).bounds(100)
            img = image_fn(year, region)
            table = img.reduceRegions(collection=sub, reducer=red, scale=scale,
                                      tileScale=cfg["zones"]["tile_scale"])
            ytag = "static" if year is None else str(year)
            desc = f"{product}_{zones_name.split('/')[-1]}_{ytag}_c{lo:04d}-{hi:04d}"
            task = export_table(cfg, table, desc, subfolder=product, selectors=sel)
            submitter.submit(task, job=job, product=product, year=ytag, chunk=f"{lo}-{hi}",
                             destination=f"{product}/{desc}.csv",
                             params={"scale": scale, "stats": stats, "zones": zones_name})
