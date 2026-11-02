"""Sentinel-1 GRD backscatter and inundation layers (Days 32, 48).

GEE S1_GRD is calibrated, thermal-noise corrected and terrain corrected, but not speckle
filtered. Per month we export:
  vv, vh, vhvv   median backscatter (dB) and VH-VV ratio
  vhmin          monthly minimum VH (water sensitivity)
  nobs           revisit count (covariate: S1B lost Dec 2021, sampling halves afterwards)
  inund          1 if any scene in the month is flooded (zonal mean -> inundated fraction)
  fdur           flooded scenes / scenes (revisit-normalised duration)
  inund_np       inund excluding permanent water (JRC occurrence >= threshold)
Flood rule: VH < monthly Otsu threshold (clamped) AND VH - dry-season baseline < change_db.
The dry-season baseline is the median VH of `dry_months` of the same year.
"""
from __future__ import annotations

import ee

from .common import band_names, ds, empty, month_window

S1_OUT = ["vv", "vh", "vhvv", "vhmin", "nobs", "inund", "fdur", "inund_np"]


def s1_collection(cfg: dict, region: ee.Geometry, start, end) -> ee.ImageCollection:
    p = cfg["products"]["s1"]
    col = (ee.ImageCollection(ds(cfg, "s1_grd")).filterBounds(region).filterDate(start, end)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .filter(ee.Filter.eq("orbitProperties_pass", p["orbit_pass"])))

    def prep(im):
        # GRD in GEE is already in dB; mask the low-backscatter border noise, then despeckle
        db = im.select(["VV", "VH"]).updateMask(im.select("VV").gt(-30))
        db = db.focalMedian(p["speckle_radius_m"], "circle", "meters").rename(["vv", "vh"])
        return db.addBands(db.select("vh").subtract(db.select("vv")).rename("vhvv")) \
            .copyProperties(im, ["system:time_start"])
    return col.map(prep)


def otsu(histogram: ee.Dictionary) -> ee.Number:
    """Otsu threshold from an ee.Reducer.histogram() output dictionary."""
    counts = ee.Array(ee.Dictionary(histogram).get("histogram"))
    means = ee.Array(ee.Dictionary(histogram).get("bucketMeans"))
    size = means.length().get([0])
    total = counts.reduce(ee.Reducer.sum(), [0]).get([0])
    mean = counts.multiply(means).reduce(ee.Reducer.sum(), [0]).get([0]).divide(total)
    indices = ee.List.sequence(1, size)

    def bss(i):
        a_counts = counts.slice(0, 0, i)
        a_count = a_counts.reduce(ee.Reducer.sum(), [0]).get([0])
        a_means = means.slice(0, 0, i)
        a_mean = a_means.multiply(a_counts).reduce(ee.Reducer.sum(), [0]).get([0]).divide(a_count)
        b_count = total.subtract(a_count)
        b_mean = total.multiply(mean).subtract(a_count.multiply(a_mean)).divide(b_count)
        return a_count.multiply(a_mean.subtract(mean).pow(2)).add(
            b_count.multiply(b_mean.subtract(mean).pow(2)))

    scores = indices.map(bss)
    return means.toList().get(ee.List(scores).indexOf(ee.List(scores).reduce(ee.Reducer.max())))


def s1_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    p = cfg["products"]["s1"]
    lo_db, hi_db = p["otsu_bounds_db"]
    year_start = ee.Date.fromYMD(year, 1, 1)
    col = s1_collection(cfg, region, year_start, year_start.advance(1, "year"))
    dry = col.filter(ee.Filter.calendarRange(min(p["dry_months"]), max(p["dry_months"]), "month"))
    baseline = ee.Image(ee.Algorithms.If(dry.size().gt(0), dry.select("vh").median(),
                                         empty(["vh"]))).rename("base")
    perm = ee.Image(ds(cfg, "jrc_global")).select("occurrence").gte(p["permanent_water_occurrence"]).unmask(0)

    out = []
    for m in range(1, 13):
        s, e = month_window(year, m)
        sub = col.filterDate(s, e)
        vhmin = sub.select("vh").min()
        hist = vhmin.reduceRegion(ee.Reducer.histogram(255, 0.1), region, 100, bestEffort=True,
                                  maxPixels=1e9).get("vh")
        # The histogram is only evaluated inside the non-empty branch (If is lazy server-side)
        thr = ee.Number(ee.Algorithms.If(sub.size().gt(0), otsu(hist), p["fallback_threshold_db"]))
        thr = thr.max(lo_db).min(hi_db)

        def flooded(im, thr=thr):
            vh = im.select("vh")
            return vh.lt(thr).And(vh.subtract(baseline).lt(p["change_db"])).rename("f")
        fl = sub.map(flooded)
        inund = fl.max().toFloat()
        n_fl = fl.count()
        comp = ee.Image.cat([
            sub.select(["vv", "vh", "vhvv"]).median(),
            vhmin.rename("vhmin"),
            sub.select("vh").count().rename("nobs"),
            inund.rename("inund"),
            fl.sum().divide(n_fl.max(1)).updateMask(n_fl.gt(0)).rename("fdur"),
            inund.updateMask(perm.Not()).rename("inund_np"),
        ]).toFloat()
        img = ee.Image(ee.Algorithms.If(sub.size().gt(0), comp, empty(S1_OUT)))
        out.append(img.rename([f"{n}_{year}{m:02d}" for n in S1_OUT]))
    return ee.Image.cat(out)


def s1_bands(year: int) -> list[str]:
    return band_names(S1_OUT, year)


def s1_orbit_counts(cfg: dict, region: ee.Geometry) -> dict:
    """Scene counts per orbit pass and year over `region` (Day 8 / Day 32 orbit policy)."""
    col = (ee.ImageCollection(ds(cfg, "s1_grd")).filterBounds(region)
           .filter(ee.Filter.eq("instrumentMode", "IW")))
    out = {}
    for orbit in ("ASCENDING", "DESCENDING"):
        c = col.filter(ee.Filter.eq("orbitProperties_pass", orbit))
        years = ee.List.sequence(2014, 2026)
        out[orbit] = years.map(lambda y: c.filter(ee.Filter.calendarRange(y, y, "year")).size()).getInfo()
    return out
