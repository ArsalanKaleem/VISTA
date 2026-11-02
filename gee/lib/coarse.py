"""MODIS (Day 34), CHIRPS (Day 35), ERA5-Land (Day 36) and GRACE (optional context).

Timing rule (Section 4.4): composites are re-stamped with their END date before monthly
grouping, so a month only contains information available by the end of that month.
Gap-filled products (MOD16A2GF, MOD17A2HGF) are exported for descriptive use and flagged
non-causal; they must not become model inputs.
"""
from __future__ import annotations

import ee

from .common import band_names, ds, empty, month_window, monthly_stack, shift_to_window_end

# --------------------------------------------------------------------------- MODIS

MODIS_VI = ["ndvi_m", "evi_m"]
MODIS_LST = ["lstd_t", "lstn_t", "lstd_a", "lstn_a"]
MODIS_ET = ["et_gf", "pet_gf", "gpp_gf"]          # *_gf = gap-filled, non-causal


def modis_vi_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    def prep(im):
        good = im.select("SummaryQA").lte(1)      # 0 good, 1 marginal
        return im.select(["NDVI", "EVI"], MODIS_VI).multiply(0.0001).updateMask(good) \
            .copyProperties(im, ["system:time_start"])
    s = ee.Date.fromYMD(year, 1, 1)
    col = ee.ImageCollection(ds(cfg, "mod13q1")).filterBounds(region) \
        .filterDate(s.advance(-20, "day"), s.advance(1, "year")).map(prep)
    col = shift_to_window_end(col, 15)
    return monthly_stack(col, year, MODIS_VI, "mean", nobs="nobs_vi")


def _lst_prep(prefix: str):
    def f(im):
        def qc_ok(qc):
            # bits 0-1: 00 good, 01 other quality; bits 6-7: LST error <= 2 K
            return qc.bitwiseAnd(3).lte(1).And(qc.rightShift(6).bitwiseAnd(3).lte(1))
        day = im.select("LST_Day_1km").multiply(0.02).subtract(273.15).updateMask(qc_ok(im.select("QC_Day")))
        night = im.select("LST_Night_1km").multiply(0.02).subtract(273.15).updateMask(qc_ok(im.select("QC_Night")))
        return day.rename(f"lstd_{prefix}").addBands(night.rename(f"lstn_{prefix}")) \
            .copyProperties(im, ["system:time_start"])
    return f


def modis_lst_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    s = ee.Date.fromYMD(year, 1, 1)
    out = []
    for key, prefix in (("mod11a2", "t"), ("myd11a2", "a")):
        col = ee.ImageCollection(ds(cfg, key)).filterBounds(region) \
            .filterDate(s.advance(-10, "day"), s.advance(1, "year")).map(_lst_prep(prefix))
        col = shift_to_window_end(col, 7)
        out.append(monthly_stack(col, year, [f"lstd_{prefix}", f"lstn_{prefix}"], "mean",
                                 nobs=f"nobs_lst_{prefix}"))
    return ee.Image.cat(out)


def modis_et_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    s = ee.Date.fromYMD(year, 1, 1)
    et = ee.ImageCollection(ds(cfg, "mod16a2gf")).filterBounds(region) \
        .filterDate(s.advance(-10, "day"), s.advance(1, "year")) \
        .map(lambda im: im.select(["ET", "PET"], ["et_gf", "pet_gf"]).multiply(0.1)
             .copyProperties(im, ["system:time_start"]))
    gpp = ee.ImageCollection(ds(cfg, "mod17a2hgf")).filterBounds(region) \
        .filterDate(s.advance(-10, "day"), s.advance(1, "year")) \
        .map(lambda im: im.select(["Gpp"], ["gpp_gf"]).multiply(0.0001)
             .copyProperties(im, ["system:time_start"]))
    # 8-day sums per month (kg/m2 and kgC/m2); composites assigned by end date
    a = monthly_stack(shift_to_window_end(et, 7), year, ["et_gf", "pet_gf"], "sum", nobs=None)
    b = monthly_stack(shift_to_window_end(gpp, 7), year, ["gpp_gf"], "sum", nobs=None)
    return a.addBands(b)


def modis_vi_bands(year):
    return band_names(MODIS_VI + ["nobs_vi"], year)


def modis_lst_bands(year):
    return band_names(["lstd_t", "lstn_t", "nobs_lst_t"], year) + band_names(["lstd_a", "lstn_a", "nobs_lst_a"], year)


def modis_et_bands(year):
    return band_names(["et_gf", "pet_gf"], year) + band_names(["gpp_gf"], year)


# --------------------------------------------------------------------------- CHIRPS

CHIRPS_OUT = ["precip", "rdays", "rx1", "rx5", "cdd"]


def chirps_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    """Monthly total, wet days (> wet_day_mm), max 1-day, max 5-day and longest dry spell.

    Dry spells are counted within the calendar month (spells crossing month ends are split);
    annual/seasonal maxima are derived locally from the daily-independent monthly values.
    """
    wet = cfg["products"]["chirps"]["wet_day_mm"]
    daily_all = ee.ImageCollection(ds(cfg, "chirps_daily")).filterBounds(region).select("precipitation")
    out = []
    for m in range(1, 13):
        s, e = month_window(year, m)
        daily = daily_all.filterDate(s, e)

        def five_day(im):
            d = ee.Date(im.get("system:time_start"))
            return daily_all.filterDate(d.advance(-4, "day"), d.advance(1, "day")).sum() \
                .rename("p5").copyProperties(im, ["system:time_start"])

        def dry_step(im, acc):
            acc = ee.Image(acc)
            dry = im.lt(wet)
            run = acc.select("run").add(1).multiply(dry)
            return run.addBands(acc.select("max").max(run)).rename(["run", "max"])

        init = ee.Image.constant([0, 0]).rename(["run", "max"]).toFloat()
        cdd = ee.Image(daily.sort("system:time_start").iterate(dry_step, init)).select("max")
        comp = ee.Image.cat([
            daily.sum().rename("precip"),
            daily.map(lambda im: im.gt(wet)).sum().rename("rdays"),
            daily.max().rename("rx1"),
            daily.map(five_day).max().rename("rx5"),
            cdd.rename("cdd"),
        ]).toFloat()
        img = ee.Image(ee.Algorithms.If(daily.size().gt(0), comp, empty(CHIRPS_OUT)))
        out.append(img.rename([f"{n}_{year}{m:02d}" for n in CHIRPS_OUT]))
    return ee.Image.cat(out)


def chirps_bands(year):
    return band_names(CHIRPS_OUT, year)


# --------------------------------------------------------------------------- ERA5-Land

ERA5_EXTRA = ["tmax", "tmin"]  # monthly means of daily extremes (Hargreaves PET fallback)


def era5_prep(cfg: dict):
    bands = cfg["products"]["era5"]["bands"]

    def f(im):
        out = []
        for short, name in bands.items():
            b = im.select(name)
            if short in ("t2m", "skt"):
                b = b.subtract(273.15)                  # K -> degC
            elif short in ("tp", "sro"):
                b = b.multiply(1000)                    # m -> mm
            elif short in ("pev", "evap"):
                b = b.multiply(-1000)                   # m, ECMWF sign (upward negative) -> mm, positive
            out.append(b.rename(short))
        return ee.Image.cat(out).copyProperties(im, ["system:time_start"])
    return f


def era5_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    s = ee.Date.fromYMD(year, 1, 1)
    col = ee.ImageCollection(ds(cfg, "era5_land_monthly")).filterBounds(region) \
        .filterDate(s, s.advance(1, "year")).map(era5_prep(cfg))
    names = list(cfg["products"]["era5"]["bands"])
    stack = monthly_stack(col, year, names, "mean", nobs=None)
    daily = ee.ImageCollection(ds(cfg, "era5_land_daily")).filterBounds(region) \
        .filterDate(s, s.advance(1, "year")) \
        .map(lambda im: im.select(["temperature_2m_max", "temperature_2m_min"], ERA5_EXTRA)
             .subtract(273.15).copyProperties(im, ["system:time_start"]))
    return stack.addBands(monthly_stack(daily, year, ERA5_EXTRA, "mean", nobs=None))


def era5_bands(cfg: dict, year):
    return band_names(list(cfg["products"]["era5"]["bands"]), year) + band_names(ERA5_EXTRA, year)


# --------------------------------------------------------------------------- GRACE (regional only)

def grace_stack(cfg: dict, years: tuple[int, int]) -> ee.Image:
    """Monthly LWE thickness anomaly, all months in one image. Regional context ONLY (Section 6)."""
    col = ee.ImageCollection(ds(cfg, "grace")).filterDate(f"{years[0]}-01-01", f"{years[1] + 1}-01-01")

    col = col.map(lambda im: im.set("ym", ee.Date(im.get("system:time_start")).format("YYYYMM")))
    months = col.aggregate_array("ym").distinct().sort()

    def month_mean(ym):  # some months hold two GRACE solutions (e.g. 2004-02): average them
        # first band = LWE thickness (band names differ between GRACE versions)
        sub = col.filter(ee.Filter.eq("ym", ym)).select([0])
        return sub.mean().rename(ee.String("lwe_").cat(ym))
    # toBands prefixes each band with the image index; keep only lwe_YYYYMM
    return (ee.ImageCollection(months.map(month_mean)).toBands()
            .regexpRename("^.*_(lwe_[0-9]{6})$", "$1"))
