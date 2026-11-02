"""Dynamic World probabilities (Day 33) and JRC Global Surface Water (Day 37).

Dynamic World: monthly MEAN class probabilities (never hard labels) + valid count.
JRC MonthlyHistory (1984-03 .. 2021-12): 'water' 0 = no data, 1 = not water, 2 = water.
  jrcw   water indicator on valid pixels only (zonal mean = water fraction of observed area)
  jrcv   valid indicator, unmasked (zonal mean = observed share of the zone)
After 2021 the S1/S2 water variables (wfrac, inund) replace JRC; targets use S1/S2 only.
"""
from __future__ import annotations

import ee

from .common import band_names, ds, month_window, monthly_stack


def dw_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    classes = cfg["products"]["dw"]["classes"]
    s = ee.Date.fromYMD(year, 1, 1)
    col = ee.ImageCollection(ds(cfg, "dynamic_world")).filterBounds(region) \
        .filterDate(s, s.advance(1, "year")).select(classes, [f"dw_{c}" for c in classes])
    return monthly_stack(col, year, [f"dw_{c}" for c in classes], "mean", nobs="nobs_dw")


def dw_bands(cfg: dict, year):
    return band_names([f"dw_{c}" for c in cfg["products"]["dw"]["classes"]] + ["nobs_dw"], year)


JRC_OUT = ["jrcw", "jrcv"]


def jrc_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    col = ee.ImageCollection(ds(cfg, "jrc_monthly"))
    out = []
    for m in range(1, 13):
        s, e = month_window(year, m)
        img = ee.Image(col.filterDate(s, e).first())
        # Missing months (none expected 2000-2021) would fail loudly here, which is intended.
        w = img.select("water")
        valid = w.gt(0)
        out.append(ee.Image.cat([
            w.eq(2).updateMask(valid).toFloat().rename(f"jrcw_{year}{m:02d}"),
            valid.unmask(0).toFloat().rename(f"jrcv_{year}{m:02d}"),
        ]))
    return ee.Image.cat(out)


def jrc_bands(year):
    return band_names(JRC_OUT, year)


JRC_STATIC = ["occurrence", "recurrence", "seasonality", "max_extent", "change_abs"]


def jrc_static(cfg: dict, year=None, region=None) -> ee.Image:
    g = ee.Image(ds(cfg, "jrc_global"))
    img = g.select(JRC_STATIC).unmask(0).toFloat()
    perm = g.select("occurrence").gte(cfg["products"]["s1"]["permanent_water_occurrence"]).unmask(0).rename("perm_water")
    return img.rename([f"jrc_{b}" for b in JRC_STATIC]).addBands(perm.toFloat())


def jrc_static_bands(year=None):
    return [f"jrc_{b}" for b in JRC_STATIC] + ["perm_water"]
