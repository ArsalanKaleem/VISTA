"""Static terrain/hydrology (Day 38) and slow context layers (Day 39).

Terrain: one DEM is used for all villages (Copernicus GLO-30 by default; SRTM kept for the
Day-38 comparison). HAND/TWI are coarse covariates in the flat delta, not flood-depth models.
TWI = ln(a / tan(beta)), a = MERIT upstream area (m2) / pixel width (90 m), beta = slope.
Distances to river/canal/coast/road are computed locally from vectors in UTM 42N.

Context: modelled estimates (GHSL, WorldPop) are exposure context, never outcomes; GHSL 2025
and 2030 epochs are projections. Embeddings of year Y may only be used for origins in Y+1+.
"""
from __future__ import annotations

import ee

from .common import ds

TERRAIN = ["elev_glo30", "elev_srtm", "slope", "hand", "log_upa", "twi"]


def glo30(cfg: dict) -> ee.Image:
    col = ee.ImageCollection(ds(cfg, "glo30")).select("DEM")
    return col.mosaic().setDefaultProjection(col.first().projection()).rename("elev_glo30")


def terrain_image(cfg: dict, year=None, region=None) -> ee.Image:
    dem = glo30(cfg)
    srtm = ee.Image(ds(cfg, "srtm")).select("elevation").rename("elev_srtm")
    slope = ee.Terrain.slope(dem).rename("slope")
    merit = ee.Image(ds(cfg, "merit_hydro"))
    upa_m2 = merit.select("upa").multiply(1e6)
    tan_b = slope.multiply(3.141592653589793 / 180).tan().max(0.001)
    twi = upa_m2.divide(90).divide(tan_b).log().rename("twi")
    return ee.Image.cat([
        dem, srtm, slope,
        merit.select("hnd").rename("hand"),
        merit.select("upa").max(0.0001).log10().rename("log_upa"),
        twi,
    ]).toFloat()


def terrain_bands(year=None):
    return TERRAIN


# --------------------------------------------------------------------------- context

def _epoch(col_id: str, year: int, band: str) -> ee.Image:
    col = ee.ImageCollection(col_id)
    return col.filter(ee.Filter.calendarRange(year, year, "year")).first().select(band)


def context_image(cfg: dict, year=None, region=None) -> ee.Image:
    p = cfg["products"]["context"]
    bands = []
    for y in p["ghsl_epochs"]:
        bands.append(_epoch(ds(cfg, "ghsl_pop"), y, "population_count").rename(f"ghsl_pop_{y}"))
        bands.append(_epoch(ds(cfg, "ghsl_built_s"), y, "built_surface").rename(f"ghsl_built_{y}"))
    smod = ee.ImageCollection(ds(cfg, "ghsl_smod"))
    bands.append(smod.filter(ee.Filter.calendarRange(2020, 2020, "year")).first()
                 .select(0).rename("ghsl_smod_2020"))
    wp = ee.ImageCollection(ds(cfg, "worldpop")).filter(ee.Filter.eq("country", "PAK"))
    for y in range(p["worldpop_years"][0], p["worldpop_years"][1] + 1):
        bands.append(wp.filter(ee.Filter.eq("year", y)).first().select("population").rename(f"worldpop_{y}"))
    bands.append(ee.Image(ds(cfg, "accessibility")).select("accessibility").rename("access_min_2015"))
    # V22 covers 2022+ only and V21 2013-2021: merge every candidate (same "average" band)
    viirs = ee.ImageCollection(ds(cfg, "viirs_annual"))
    for alt in cfg["datasets"]["viirs_annual"]:
        if alt != ds(cfg, "viirs_annual"):
            viirs = viirs.merge(ee.ImageCollection(alt).select("average"))
    for y in range(p["viirs_years"][0], p["viirs_years"][1] + 1):
        img = viirs.filter(ee.Filter.calendarRange(y, y, "year")).first()
        bands.append(ee.Image(ee.Algorithms.If(img, ee.Image(img).select("average"),
                                               ee.Image.constant(0).updateMask(0)))
                     .rename(f"viirs_{y}"))
    return ee.Image.cat(bands).toFloat()


def context_bands(cfg: dict, year=None):
    p = cfg["products"]["context"]
    out = []
    for y in p["ghsl_epochs"]:
        out += [f"ghsl_pop_{y}", f"ghsl_built_{y}"]
    out.append("ghsl_smod_2020")
    out += [f"worldpop_{y}" for y in range(p["worldpop_years"][0], p["worldpop_years"][1] + 1)]
    out.append("access_min_2015")
    out += [f"viirs_{y}" for y in range(p["viirs_years"][0], p["viirs_years"][1] + 1)]
    return out


EMB = [f"A{i:02d}" for i in range(64)]


def embedding_image(cfg: dict, year: int, region: ee.Geometry) -> ee.Image:
    """AlphaEarth annual embedding of `year` (use only for origins in year+1 or later)."""
    col = ee.ImageCollection(ds(cfg, "embeddings")).filterBounds(region) \
        .filter(ee.Filter.calendarRange(year, year, "year"))
    return col.mosaic().select(EMB).rename([f"emb{year}_{b}" for b in EMB]).toFloat()


def embedding_bands(year: int):
    return [f"emb{year}_{b}" for b in EMB]
