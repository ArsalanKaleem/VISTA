"""Settlement evidence in Earth Engine (Days 13-15 support).

1. Open Buildings v3 centroids per district (CSV) -> local clustering (Day 14-15).
2. Settlement-evidence table per taluka: building counts, GHSL built/pop, SMOD, WorldPop.
3. PROVISIONAL settlement polygons by raster clustering of Open Buildings
   (paint buildings at 10 m, dilate 40 m ~ 'buffer 40 m, dissolve', connected components,
   keep clusters with >= 5 buildings). These exist only to pilot the zonal pipeline before
   inventory v1.0 is frozen on Day 25; they are not the inventory.
   Fallback source: GHSL built-up connected components (Day 13 fallback).
"""
from __future__ import annotations

import ee

from .common import ds


def buildings(cfg: dict, region: ee.Geometry) -> ee.FeatureCollection:
    return ee.FeatureCollection(ds(cfg, "open_buildings")).filterBounds(region) \
        .filter(ee.Filter.gte("confidence", cfg["products"]["settlements"]["open_buildings_min_conf"]))


def building_centroids(cfg: dict, region: ee.Geometry) -> ee.FeatureCollection:
    def f(b):
        c = b.geometry().centroid(1)
        xy = c.coordinates()
        return ee.Feature(None, {
            "lon": xy.get(0), "lat": xy.get(1),
            "area_m2": b.get("area_in_meters"),
            "confidence": b.get("confidence"),
            "plus_code": b.get("full_plus_code"),
        })
    return buildings(cfg, region).map(f)


CENTROID_COLS = ["lon", "lat", "area_m2", "confidence", "plus_code"]


def taluka_evidence(cfg: dict, talukas: ee.FeatureCollection) -> ee.FeatureCollection:
    """Per-taluka evidence counts for comparison with PBS settlement totals (Day 13)."""
    pop = ee.ImageCollection(ds(cfg, "ghsl_pop")).filter(ee.Filter.calendarRange(2020, 2020, "year")) \
        .first().select("population_count").rename("ghsl_pop_2020")
    built = ee.ImageCollection(ds(cfg, "ghsl_built_s")).filter(ee.Filter.calendarRange(2020, 2020, "year")) \
        .first().select("built_surface").rename("ghsl_built_m2_2020")
    smod = ee.ImageCollection(ds(cfg, "ghsl_smod")).filter(ee.Filter.calendarRange(2020, 2020, "year")) \
        .first().select(0)
    # SMOD L2 codes: 30 urban centre, 21-23 urban cluster, 11-13 rural
    urban = smod.gte(21).rename("smod_urban_share")
    wp = ee.ImageCollection(ds(cfg, "worldpop")).filter(ee.Filter.eq("country", "PAK")) \
        .filter(ee.Filter.eq("year", 2020)).first().select("population").rename("worldpop_2020")
    sums = pop.addBands(built).addBands(wp)
    sums_fc = sums.reduceRegions(talukas, ee.Reducer.sum(), 100, tileScale=8)
    shares = urban.reduceRegions(sums_fc, ee.Reducer.mean().setOutputs(["smod_urban_share"]), 1000, tileScale=4)

    def count_buildings(f):
        n = buildings(cfg, f.geometry()).size()
        area_km2 = f.geometry().area(100).divide(1e6)
        return f.set({"n_buildings": n, "area_km2": area_km2,
                      "buildings_per_km2": n.divide(area_km2)}).setGeometry(None)
    return shares.map(count_buildings)


def provisional_settlements(cfg: dict, region: ee.Geometry, source: str = "open_buildings") -> ee.FeatureCollection:
    p = cfg["products"]["settlements"]
    proj = ee.Projection("EPSG:32642").atScale(p["raster_scale"])
    if source == "open_buildings":
        b = buildings(cfg, region).map(lambda f: f.set("one", 1))
        footprint = b.reduceToImage(["one"], ee.Reducer.first()).unmask(0).gt(0).reproject(proj)
        cents = b.map(lambda f: ee.Feature(f.geometry().centroid(1), {"one": 1}))
        count = cents.reduceToImage(["one"], ee.Reducer.sum()).unmask(0).reproject(proj).rename("n_buildings")
        min_n = p["min_buildings"]
    else:  # GHSL built-up fallback (100 m grid -> cells with >= 10% built surface)
        built = ee.ImageCollection(ds(cfg, "ghsl_built_s")).filter(ee.Filter.calendarRange(2020, 2020, "year")) \
            .first().select("built_surface")
        footprint = built.gte(1000).unmask(0)
        count = built.divide(100).rename("n_buildings")   # pseudo-count (built m2 / 100)
        proj = ee.Projection("EPSG:32642").atScale(100)
        min_n = p["min_buildings"]
    radius_px = max(1, round(p["dilate_m"] / proj.nominalScale().getInfo()))
    grown = footprint.focalMax(radius_px, "square", "pixels").reproject(proj)
    seg = ee.Image(1).updateMask(grown).toInt().addBands(count)
    vec = seg.reduceToVectors(
        geometry=region, crs=proj, geometryType="polygon", eightConnected=True,
        labelProperty="seg", reducer=ee.Reducer.sum().setOutputs(["n_buildings"]),
        maxPixels=1e12, tileScale=8, bestEffort=False)
    vec = vec.filter(ee.Filter.gte("n_buildings", min_n))

    def attrs(f):
        g = f.geometry()
        c = g.centroid(1).coordinates()
        return f.set({"area_m2": g.area(1), "lon": c.get(0), "lat": c.get(1), "source": source})
    return vec.map(attrs)
