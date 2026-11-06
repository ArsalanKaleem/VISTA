"""Registry of every Earth Engine export job in the 100-day plan.

Each job is a function job(cfg, ctx, submitter). ctx carries CLI options:
    zones   zones asset name under gee.asset_root (zonal jobs)
    years   (start, end) override
    regions list of district/taluka names (region-based jobs)
Run `python -m gee.run list-jobs` for the table, `python -m gee.run submit <job> --dry-run`
to preview, and `python -m gee.run wave <n>` to submit a whole wave from configs/gee_jobs.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import ee

from .lib import coarse, landcover, optical, radar, settlements, static
from .lib.common import (admin, asset, ds, ensure_folder, export_image, export_table,
                         export_table_to_asset, select_by_name, sindh_bbox, sindh_geom)
from .lib.zonal import submit_zonal


@dataclass
class Ctx:
    zones: str | None = None
    years: tuple[int, int] | None = None
    regions: list[str] = field(default_factory=list)
    zone_types: list[str] | None = None


@dataclass
class Job:
    fn: Callable
    day: str
    needs_zones: bool
    summary: str


JOBS: dict[str, Job] = {}


def job(name: str, day: str, needs_zones: bool, summary: str):
    def deco(fn):
        JOBS[name] = Job(fn, day, needs_zones, summary)
        return fn
    return deco


def _years(cfg, ctx, product) -> list[int]:
    a, b = ctx.years or cfg["products"][product]["years"]
    return list(range(a, b + 1))


def _need_zones(ctx):
    if not ctx.zones:
        raise SystemExit("this job needs --zones <asset name>, e.g. zones/pilot_v0 or zones/v1_0")


# =========================================================================== zone-independent

@job("chirps_grid", "35", False, "CHIRPS monthly precip/wet days/RX1/RX5/dry spell rasters 1981-2025 (one GeoTIFF per year)")
def chirps_grid(cfg, ctx, sub):
    region = sindh_bbox(cfg)
    proj = ee.Image(ee.ImageCollection(ds(cfg, "chirps_daily")).first()).projection().getInfo()
    for y in _years(cfg, ctx, "chirps"):
        img = coarse.chirps_year_stack(cfg, y, region)
        t = export_image(cfg, img, f"chirps_grid_{y}", "chirps_grid", region,
                         crs=proj["crs"], crs_transform=proj["transform"])
        sub.submit(t, job="chirps_grid", product="chirps", year=y, destination=f"chirps_grid/chirps_grid_{y}.tif")


@job("era5_grid", "36", False, "ERA5-Land monthly t2m/skt/tp/PET/ET/soil water/runoff + tmax/tmin rasters 1981-2025")
def era5_grid(cfg, ctx, sub):
    region = sindh_bbox(cfg)
    proj = ee.Image(ee.ImageCollection(ds(cfg, "era5_land_monthly")).first()).projection().getInfo()
    for y in _years(cfg, ctx, "era5"):
        img = coarse.era5_year_stack(cfg, y, region)
        t = export_image(cfg, img, f"era5_grid_{y}", "era5_grid", region,
                         crs=proj["crs"], crs_transform=proj["transform"])
        sub.submit(t, job="era5_grid", product="era5", year=y, destination=f"era5_grid/era5_grid_{y}.tif")


@job("grace_grid", "36", False, "GRACE/GRACE-FO monthly LWE anomaly raster 2002-2025 (regional context only)")
def grace_grid(cfg, ctx, sub):
    region = sindh_bbox(cfg).buffer(200_000)
    img = coarse.grace_stack(cfg, ctx.years or (2002, 2025))
    t = export_image(cfg, img, "grace_lwe_2002_2025", "grace", region, scale=111_320)
    sub.submit(t, job="grace_grid", product="grace", destination="grace/grace_lwe_2002_2025.tif")


@job("open_buildings_centroids", "13", False, "Open Buildings v3 centroids (lon, lat, area, confidence) per Sindh taluka -> CSV")
def open_buildings_centroids(cfg, ctx, sub):
    # Talukas, not districts: geoBoundaries ADM2 lacks Larkana and uses the pre-2017 districts.
    talukas = admin(cfg, 3)
    name = cfg["aoi"]["name_field"]
    if ctx.regions:
        talukas = select_by_name(talukas, name, ctx.regions)
    names = talukas.aggregate_array(name).getInfo()
    print(f"  {len(names)} talukas")
    for n in names:
        geom = talukas.filter(ee.Filter.eq(name, n)).geometry()
        fc = settlements.building_centroids(cfg, geom)
        tag = n.replace(" ", "_").replace(".", "")
        t = export_table(cfg, fc, f"open_buildings_{tag}", "open_buildings", selectors=settlements.CENTROID_COLS)
        sub.submit(t, job="open_buildings_centroids", product="open_buildings", chunk=n,
                   destination=f"open_buildings/open_buildings_{tag}.csv")


@job("open_buildings_gaps", "15", False, "Open Buildings centroids for OCHA tehsils missing from the geoBoundaries ADM3 spine (Jacobabad) -> CSV")
def open_buildings_gaps(cfg, ctx, sub):
    # geoBoundaries ADM3 has no polygon for Jacobabad taluka (3% covered), so open_buildings_centroids
    # never exported it. Gap tehsils come from scripts/admin_crosswalk.py (gb_coverage < 0.9).
    import json

    import geopandas as gpd
    import pandas as pd

    from .lib.common import ROOT
    adm = ROOT / cfg["aoi"]["local_admin_dir"]
    cw = pd.read_csv(adm / "taluka_crosswalk.csv")
    gaps = cw[cw.gb_coverage < 0.9].drop_duplicates("ocha_adm3_pcode")
    o3 = gpd.read_file(adm / "admin_boundaries.gpkg", layer="ocha_adm3")
    o3 = o3[o3.adm3_pcode.isin(gaps.ocha_adm3_pcode)]
    if ctx.regions:
        o3 = o3[o3.adm3_name.str.upper().isin([r.upper() for r in ctx.regions])]
    print(f"  {len(o3)} gap tehsils: {', '.join(o3.adm3_name)}")
    for _, r in o3.iterrows():
        g = r.geometry.simplify(0.0005)  # ~50 m: enough for a filterBounds region
        geom = ee.Geometry(json.loads(gpd.GeoSeries([g]).to_json())["features"][0]["geometry"])
        fc = settlements.building_centroids(cfg, geom)
        tag = f"OCHA_{r.adm3_pcode}_{r.adm3_name.upper().replace(' ', '_')}"
        t = export_table(cfg, fc, f"open_buildings_{tag}", "open_buildings", selectors=settlements.CENTROID_COLS)
        sub.submit(t, job="open_buildings_gaps", product="open_buildings", chunk=r.adm3_pcode,
                   destination=f"open_buildings/open_buildings_{tag}.csv")


@job("settlement_evidence", "13", False, "Per-taluka evidence: building counts, GHSL pop/built, SMOD urban share, WorldPop -> CSV")
def settlement_evidence(cfg, ctx, sub):
    fc = settlements.taluka_evidence(cfg, admin(cfg, 3))
    t = export_table(cfg, fc, "settlement_evidence_by_taluka", "settlements")
    sub.submit(t, job="settlement_evidence", product="settlements",
               destination="settlements/settlement_evidence_by_taluka.csv")


@job("provisional_settlements", "14", False, "PROVISIONAL settlement polygons (Open Buildings raster clustering) for pilot talukas -> asset + GeoJSON")
def provisional_settlements(cfg, ctx, sub):
    talukas = admin(cfg, 3)
    name = cfg["aoi"]["name_field"]
    names = ctx.regions or cfg["aoi"]["pilot_talukas"]
    sel = select_by_name(talukas, name, names)
    try:
        ensure_folder(asset(cfg, "settlements"))
        to_asset = True
    except ee.EEException as exc:
        # The Drive GeoJSON is what scripts/make_zones.py reads; the asset copy is a convenience.
        print(f"  asset folder not writable ({exc}); exporting GeoJSON to Drive only")
        to_asset = False
    for n in sel.aggregate_array(name).getInfo():
        geom = sel.filter(ee.Filter.eq(name, n)).geometry()
        fc = settlements.provisional_settlements(cfg, geom).map(lambda f, n=n: f.set("taluka", n))
        tag = n.replace(" ", "_")
        aid = asset(cfg, f"settlements/provisional_{tag}")
        if to_asset:
            sub.submit(export_table_to_asset(fc, aid, f"prov_settlements_asset_{tag}"),
                       job="provisional_settlements", product="settlements", chunk=n, destination=aid)
        sub.submit(export_table(cfg, fc, f"prov_settlements_{tag}", "settlements", fmt="GeoJSON"),
                   job="provisional_settlements", product="settlements", chunk=n,
                   destination=f"settlements/prov_settlements_{tag}.geojson")


@job("province_maps", "92", False, "Province-wide rasters for figures: JRC occurrence, S1 flood frequency 2015-25, MODIS NDVI Sen slope 2001-25")
def province_maps(cfg, ctx, sub):
    region = sindh_geom(cfg)
    occ = ee.Image(ds(cfg, "jrc_global")).select("occurrence").unmask(0).toByte()
    sub.submit(export_image(cfg, occ, "map_jrc_occurrence_30m", "maps", region, scale=30, crs="EPSG:32642"),
               job="province_maps", product="maps", chunk="jrc_occurrence")
    # Monsoon (Jul-Oct) flood frequency from S1: share of years with any flooded month
    years = range(2015, 2026)
    floods = [radar.s1_year_stack(cfg, y, region).select(f"inund_{y}0[7-9]|inund_{y}10").reduce(ee.Reducer.max())
              .rename(f"f{y}") for y in years]
    freq = ee.Image.cat(floods).reduce(ee.Reducer.mean()).rename("flood_freq_2015_2025").toFloat()
    sub.submit(export_image(cfg, freq, "map_s1_flood_frequency_100m", "maps", region, scale=100, crs="EPSG:32642"),
               job="province_maps", product="maps", chunk="s1_flood_freq")
    # Annual mean MODIS NDVI and its Sen slope (per year)
    ann = []
    for y in range(2001, 2026):
        v = coarse.modis_vi_stack(cfg, y, region).select("ndvi_m_.*").reduce(ee.Reducer.mean())
        ann.append(v.rename("ndvi").addBands(ee.Image.constant(y).toFloat().rename("t")).select(["t", "ndvi"]))
    slope = ee.ImageCollection(ann).reduce(ee.Reducer.sensSlope()).select("slope").rename("ndvi_sen_slope").toFloat()
    sub.submit(export_image(cfg, slope, "map_modis_ndvi_sen_slope_250m", "maps", region, scale=250, crs="EPSG:32642"),
               job="province_maps", product="maps", chunk="ndvi_trend")


# =========================================================================== zonal (need --zones)

def zonal_job(name: str, day: str, summary: str, product_key: str, image_fn, band_fn,
              scale, stats=("mean", "count"), static_: bool = False) -> None:
    """Register a zonal job. image_fn(cfg, year, region); band_fn(cfg, year); scale = metres
    or the key of a scale entry in cfg['products'][product_key]."""
    def run(cfg, ctx, sub):
        _need_zones(ctx)
        p = cfg["products"][product_key]
        years = [None] if static_ else _years(cfg, ctx, product_key)
        submit_zonal(cfg, sub, job=name, product=name, zones_name=ctx.zones,
                     image_fn=lambda y, r: image_fn(cfg, y, r), band_fn=lambda y: band_fn(cfg, y),
                     years=years, scale=p[scale] if isinstance(scale, str) else scale,
                     group=p["chunk_group"], stats=stats, zone_types=ctx.zone_types)
    run.__name__ = name
    JOBS[name] = Job(run, day, True, summary)


def _b(fn):
    """Adapt a band_fn(year) to band_fn(cfg, year)."""
    return lambda cfg, y: fn(y)


zonal_job("s2_zonal", "28-29", "Sentinel-2 monthly NDVI/EVI/NDWI/MNDWI/NDMI/SAVI/water fraction + n_obs (Cloud Score+)",
          "s2", optical.s2_year_stack, _b(optical.s2_bands), "scale")
zonal_job("landsat_zonal", "31", "Landsat C2 L2 monthly NDVI/EVI/MNDWI/NDMI/LST + n_obs, L7 count (Roy-harmonised)",
          "landsat", optical.landsat_year_stack, _b(optical.landsat_bands), "scale")
zonal_job("landsat_season_zonal", "30-31", "Landsat Rabi/Kharif seasonal composites",
          "landsat", optical.landsat_season_stack, _b(optical.landsat_season_bands), "scale")
zonal_job("s1_zonal", "32, 48", "Sentinel-1 monthly VV/VH/VH-VV, min VH, revisits, inundation fraction/duration",
          "s1", radar.s1_year_stack, _b(radar.s1_bands), "scale")
zonal_job("dw_zonal", "33", "Dynamic World monthly mean class probabilities + n_obs",
          "dw", landcover.dw_year_stack, landcover.dw_bands, "scale")
zonal_job("modis_vi_zonal", "34", "MODIS MOD13Q1 NDVI/EVI monthly (end-date stamped)",
          "modis", coarse.modis_vi_stack, _b(coarse.modis_vi_bands), "vi_scale")
zonal_job("modis_lst_zonal", "34, 46", "MODIS MOD11A2/MYD11A2 day/night LST monthly",
          "modis", coarse.modis_lst_stack, _b(coarse.modis_lst_bands), "lst_scale")
zonal_job("modis_et_zonal", "34", "MODIS ET/PET/GPP gap-filled (NON-CAUSAL, descriptive only)",
          "modis", coarse.modis_et_stack, _b(coarse.modis_et_bands), "et_scale")
zonal_job("chirps_zonal", "35", "CHIRPS monthly precip/wet days/RX1/RX5/dry spell per zone",
          "chirps", coarse.chirps_year_stack, _b(coarse.chirps_bands), "zonal_scale", stats=("mean", "count"))
zonal_job("era5_zonal", "36", "ERA5-Land monthly variables + tmax/tmin per zone",
          "era5", coarse.era5_year_stack, coarse.era5_bands, "zonal_scale", stats=("mean", "count"))
zonal_job("jrc_zonal", "37", "JRC GSW monthly water fraction + valid share 2000-2021",
          "jrc", landcover.jrc_year_stack, _b(landcover.jrc_bands), "scale", stats=("mean", "count"))
zonal_job("jrc_static_zonal", "37, 47", "JRC GSW occurrence/recurrence/seasonality/max extent/change + permanent water share",
          "jrc", landcover.jrc_static, _b(landcover.jrc_static_bands), "scale", stats=("mean", "count"), static_=True)
zonal_job("terrain_zonal", "38", "GLO-30/SRTM elevation, slope, MERIT HAND, upstream area, TWI",
          "terrain", static.terrain_image, _b(static.terrain_bands), "scale",
          stats=("mean", "min", "max"), static_=True)
zonal_job("context_zonal", "39", "GHSL pop/built epochs, SMOD, WorldPop 2000-20, accessibility, VIIRS",
          "context", static.context_image, static.context_bands, "scale", stats=("mean", "sum"), static_=True)
zonal_job("embedding_zonal", "73 (optional)", "AlphaEarth annual 64-d embeddings (lag one year when used)",
          "embeddings", static.embedding_image, _b(static.embedding_bands), 10, stats=("mean", "count"))


# =========================================================================== chips (Day 73)

@job("chips", "73", True, "32x32 seasonal Sentinel-2 + S1 chips at settlement centroids -> TFRecord (needs --zones of POINTS)")
def chips(cfg, ctx, sub):
    """Chips via neighborhoodToArray + sampleRegions (Drive TFRecord; no Cloud Storage needed).

    --zones must point to a centroid FeatureCollection of the chip subset (Day 9 policy),
    with properties vid and chunk. One task per (season, chunk group).
    """
    _need_zones(ctx)
    p = cfg["products"]["chips"]
    from .lib.zonal import chunk, chunk_ranges, zones_fc
    pts = zones_fc(cfg, ctx.zones)
    kernel = ee.Kernel.rectangle(p["size_px"] // 2, p["size_px"] // 2, "pixels")
    ranges = chunk_ranges(cfg, pts, 10)
    a, b = ctx.years or (2018, 2025)
    for y in range(a, b + 1):
        for label, start in (("rabi", ee.Date.fromYMD(y - 1, 11, 1)), ("kharif", ee.Date.fromYMD(y, 5, 1))):
            end = start.advance(6, "month")
            for lo, hi in ranges:
                sub_pts = chunk(cfg, pts, lo, hi)
                region = sub_pts.geometry(100).bounds(100).buffer(500)
                s2 = ee.ImageCollection(ds(cfg, "s2_sr")).filterBounds(region).filterDate(start, end) \
                    .linkCollection(ee.ImageCollection(ds(cfg, "cloud_score_plus")), ["cs_cdf"]) \
                    .map(lambda im: im.updateMask(im.select("cs_cdf").gte(cfg["products"]["s2"]["cs_threshold"])))
                comp = s2.select(["B2", "B3", "B4", "B8", "B11", "B12"]).median().divide(10000)
                ndvi = comp.normalizedDifference(["B8", "B4"]).rename("NDVI")
                vh = radar.s1_collection(cfg, region, start, end).select("vh").median().rename("VH")
                img = comp.addBands(ndvi).addBands(vh).unmask(0).toFloat() \
                    .reproject(ee.Projection("EPSG:32642").atScale(p["scale"]))
                arr = img.neighborhoodToArray(kernel)
                samples = arr.sampleRegions(collection=sub_pts, properties=[cfg["zones"]["id_field"]],
                                            scale=p["scale"], tileScale=8)
                desc = f"chips_{label}_{y}_c{lo:04d}-{hi:04d}"
                sub.submit(export_table(cfg, samples, desc, "chips", fmt="TFRecord"),
                           job="chips", product="chips", year=y, chunk=f"{lo}-{hi}")
