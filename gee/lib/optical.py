"""Sentinel-2 (Day 27) and Landsat Collection 2 (Day 30) monthly/seasonal index stacks.

Indices are computed per image BEFORE compositing (Section 7 / Day 42):
  NDVI  = (NIR-Red)/(NIR+Red)
  EVI   = 2.5 (NIR-Red)/(NIR + 6 Red - 7.5 Blue + 1)
  NDWI  = (Green-NIR)/(Green+NIR)          (McFeeters)
  MNDWI = (Green-SWIR1)/(Green+SWIR1)      (Xu)
  NDMI  = (NIR-SWIR1)/(NIR+SWIR1)
  SAVI  = 1.5 (NIR-Red)/(NIR+Red+0.5)
wfrac = 1 where the monthly median MNDWI > 0 (zonal mean -> open-water fraction).
"""
from __future__ import annotations

import ee

from .common import band_names, ds, empty, month_window, monthly_stack

S2_VARS = ["ndvi", "evi", "ndwi", "mndwi", "ndmi", "savi"]
S2_OUT = S2_VARS + ["wfrac", "nobs"]
LS_VARS = ["ndvi", "evi", "mndwi", "ndmi", "lst"]
LS_OUT = LS_VARS + ["nobs", "n_l7"]


def indices(img: ee.Image) -> ee.Image:
    """img has bands blue, green, red, nir, swir1 in reflectance units (0-1)."""
    b, g, r, n, s1 = (img.select(x) for x in ("blue", "green", "red", "nir", "swir1"))
    ndvi = n.subtract(r).divide(n.add(r)).rename("ndvi")
    evi = n.subtract(r).multiply(2.5).divide(n.add(r.multiply(6)).subtract(b.multiply(7.5)).add(1)).rename("evi")
    ndwi = g.subtract(n).divide(g.add(n)).rename("ndwi")
    mndwi = g.subtract(s1).divide(g.add(s1)).rename("mndwi")
    ndmi = n.subtract(s1).divide(n.add(s1)).rename("ndmi")
    savi = n.subtract(r).multiply(1.5).divide(n.add(r).add(0.5)).rename("savi")
    # EVI explodes where the denominator approaches 0 (bright, dark or masked edge pixels)
    evi = evi.updateMask(evi.abs().lte(2))
    return ee.Image.cat([ndvi, evi, ndwi, mndwi, ndmi, savi])


# --------------------------------------------------------------------------- Sentinel-2

def s2_collection(cfg: dict, region: ee.Geometry, start, end) -> ee.ImageCollection:
    p = cfg["products"]["s2"]
    s2 = ee.ImageCollection(ds(cfg, "s2_sr")).filterBounds(region).filterDate(start, end)
    csp_id = ds(cfg, "cloud_score_plus")
    if csp_id:
        s2 = s2.linkCollection(ee.ImageCollection(csp_id), ["cs_cdf"])
        mask = lambda im: im.select("cs_cdf").gte(p["cs_threshold"])
    else:  # fallback: s2cloudless probability + SCL (Day 27 fallback)
        prob = ee.ImageCollection(ds(cfg, "s2_cloud_prob"))
        s2 = s2.linkCollection(prob, ["probability"])
        def mask(im):
            scl = im.select("SCL")
            return im.select("probability").lt(p["cloud_prob_max"]).And(
                scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10))

    def prep(im):
        sr = im.select(["B2", "B3", "B4", "B8", "B11", "B12"],
                       ["blue", "green", "red", "nir", "swir1", "swir2"]).divide(10000)
        # Reject negative / saturated reflectance artefacts (Day 27 checklist)
        ok = sr.reduce(ee.Reducer.min()).gt(0).And(sr.reduce(ee.Reducer.max()).lt(1))
        return indices(sr).updateMask(mask(im)).updateMask(ok) \
            .copyProperties(im, ["system:time_start"])
    return s2.map(prep)


def s2_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    start, _ = month_window(year, 1)
    col = s2_collection(cfg, region, start, start.advance(1, "year"))
    stack = monthly_stack(col, year, S2_VARS, "median", nobs="nobs")
    wf = []
    for m in range(1, 13):
        mndwi = stack.select(f"mndwi_{year}{m:02d}")
        wf.append(mndwi.gt(0).toFloat().rename(f"wfrac_{year}{m:02d}"))
    return stack.addBands(ee.Image.cat(wf))


def s2_bands(year: int) -> list[str]:
    return band_names(S2_VARS + ["nobs"], year) + band_names(["wfrac"], year)


# --------------------------------------------------------------------------- Landsat

# Roy et al. (2016) OLS ETM+ -> OLI coefficients (blue, green, red, nir, swir1, swir2).
ROY_SLOPE = [0.8474, 0.8483, 0.9047, 0.8462, 0.8937, 0.9071]
ROY_ITCP = [0.0003, 0.0088, 0.0061, 0.0412, 0.0254, 0.0172]
OPT = ["blue", "green", "red", "nir", "swir1", "swir2"]
L57 = (["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"], "ST_B6")
L89 = (["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], "ST_B10")


def _ls_prep(sr_bands, st_band, sensor: int, harmonise: bool):
    def f(im):
        qa = im.select("QA_PIXEL")
        # bits 1 dilated cloud, 2 cirrus, 3 cloud, 4 shadow -> mask value 0b11110
        clear = qa.bitwiseAnd(30).eq(0).And(im.select("QA_RADSAT").eq(0))
        sr = im.select(sr_bands, OPT).multiply(0.0000275).add(-0.2)
        if harmonise and sensor in (5, 7):
            sr = sr.multiply(ee.Image.constant(ROY_SLOPE)).add(ee.Image.constant(ROY_ITCP)).rename(OPT)
        ok = sr.reduce(ee.Reducer.min()).gt(0).And(sr.reduce(ee.Reducer.max()).lt(1))
        lst = im.select(st_band).multiply(0.00341802).add(149.0).subtract(273.15).rename("lst")
        is_l7 = ee.Image.constant(1 if sensor == 7 else 0).rename("is_l7").toFloat()
        # SLC-off stripes are no-data in L2 products and stay masked (never interpolated)
        return indices(sr).addBands(lst).addBands(is_l7).updateMask(clear).updateMask(ok) \
            .copyProperties(im, ["system:time_start"])
    return f


def landsat_collection(cfg: dict, region: ee.Geometry, start, end) -> ee.ImageCollection:
    h = cfg["products"]["landsat"]["harmonise_to_oli"]
    parts = []
    for key, sensor, (srb, stb) in (("landsat_l5", 5, L57), ("landsat_l7", 7, L57),
                                     ("landsat_l8", 8, L89), ("landsat_l9", 9, L89)):
        col = ee.ImageCollection(ds(cfg, key)).filterBounds(region).filterDate(start, end)
        parts.append(col.map(_ls_prep(srb, stb, sensor, h)))
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p)
    return out


def landsat_year_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    start, _ = month_window(year, 1)
    col = landsat_collection(cfg, region, start, start.advance(1, "year"))
    stack = monthly_stack(col, year, LS_VARS, "median", nobs="nobs")
    n7 = []
    for m in range(1, 13):
        s, e = month_window(year, m)
        sub = col.filterDate(s, e).select("is_l7")
        img = ee.Image(ee.Algorithms.If(sub.size().gt(0), sub.sum().toFloat().rename("n_l7"),
                                        empty(["n_l7"])))
        n7.append(img.rename(f"n_l7_{year}{m:02d}"))
    return stack.addBands(ee.Image.cat(n7))


def landsat_bands(year: int) -> list[str]:
    return band_names(LS_VARS + ["nobs"], year) + band_names(["n_l7"], year)


def landsat_season_stack(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    """Rabi (Nov y-1 .. Apr y) and Kharif (May .. Oct y) medians, named <var>_<YYYY><MM start>."""
    out = []
    for label, start in (("rabi", ee.Date.fromYMD(year - 1, 11, 1)), ("kharif", ee.Date.fromYMD(year, 5, 1))):
        col = landsat_collection(cfg, region, start, start.advance(6, "month"))
        names = LS_VARS + ["nobs"]
        comp = col.select(LS_VARS).median().addBands(col.select("ndvi").count().rename("nobs")).toFloat()
        img = ee.Image(ee.Algorithms.If(col.size().gt(0), comp.rename(names), empty(names)))
        tag = f"{year - 1}11" if label == "rabi" else f"{year}05"
        out.append(img.rename([f"{n}_{tag}" for n in names]))
    return ee.Image.cat(out)


def landsat_season_bands(year: int) -> list[str]:
    names = LS_VARS + ["nobs"]
    return [f"{n}_{year - 1}11" for n in names] + [f"{n}_{year}05" for n in names]
