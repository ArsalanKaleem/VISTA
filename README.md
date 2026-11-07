# VISTA-Sindh

Village Intelligence for Spatiotemporal Tracking and Anticipation of Socioecological Decline in
Sindh, Pakistan. This repository implements the *100-Day Research and Development Execution
Plan* (v1.0, 1 November 2026; `VISTA-Sindh_100-Day_Execution_Plan.pdf`).

**Next step: [RUNBOOK_GEE.md](RUNBOOK_GEE.md).** It covers Cloud project setup, the
check/verify/smoke steps, and submitting the Earth Engine waves.

## What exists now (Day 0, 2026-11-01)

| area | contents | plan days |
|---|---|---|
| `gee/` | Earth Engine pipeline: 23 export jobs, waves, task manifest, throttled submission with retry, status monitor | 6, 8, 10, 13-14, 26-39, 73, 92 |
| `configs/gee.yaml` | project, AOI, periods (train 2001-17 / val 2018-19 / test 2020-25), candidate dataset IDs (Appendix B), product parameters | 5, 6, 8 |
| `configs/gee_jobs.yaml` | submission waves 1-4 | 26-39 |
| `scripts/` | data download with sha256 manifest, Sindh admin extraction, zone builder, wide-to-long converter | 8, 11-12, 23, 26 |
| `src/` | code modules from Section 12.3 (zones, VIDs, spatial CV, conformal, metrics, VISTA-Net fusion, GATv2) | 18, 23, 65-86 |
| `documentation/day_tracker.csv` | all 100 daily work orders (objective, outputs, checklist, dependencies, fallback, status column) | all |
| `documentation/` | charter template, LOG, DECISIONS register, compute notes | 1, 6 |
| `tests/` | offline GEE job trace (mocked `ee`), VID stability | 7, 18 |

### Data already downloaded (`data/raw/`, hashes in `data/raw/manifest.csv`)

| source | file | use |
|---|---|---|
| geoBoundaries gbOpen PAK ADM1-3 | `geoboundaries/PAK_ADM{1,2,3}[_simplified].geojson` | provisional admin spine |
| OCHA COD-AB Pakistan (HDX) | `hdx/pak_admin_boundaries.shp.zip` | Day 12 admin boundaries and P-codes (preferred) |
| GeoNames PK | `geonames/PK.zip` + code lists | Day 13/16 place names |
| PBS Mouza Census 2020 country report | `pbs/mouza_census_2020_country_report.pdf` | Day 11 reference |
| PBS Mouza Census 2020 Sindh report | `pbs/mouza_census_2020_sindh_report.pdf` (493 pages) | Day 11 tables |
| Geofabrik OSM Pakistan shapefiles, 2026-07-12 extract (user-provided) | `osm/geofabrik_pakistan_260712_shp/gis_osm_*_free_1.shp` (20 layers, 954 MB) | Day 13 places/landuse/buildings, Day 38-39 roads and canals (`waterways` fclass=canal), Day 71 graph edges |

### Reference material (`data/reference/`, user-provided; hashes also in `data/raw/manifest.csv`)

| source | file | use |
|---|---|---|
| MNFSR *Crops Area & Production (District-wise)* | `crop_statistics/mnfsr_crops_area_production_district_{2021-22,2023-24,2024-25}.pdf` (the 2023-24 issue also covers 2022-23) | Day 33/49 district crop-presence and rank-correlation checks (proxies only, no yield claims) |
| IFPRI MapSPAM 2020 v2r2, physical area | `spam2020/spam2020V2r2_global_physical_area.csv.zip` (109 MB zipped, 893 MB unzipped; keep zipped and read the Pakistan rows with pandas `chunksize`) | Day 33/49 crop-mix context per taluka |

| Sindh Bureau of Statistics | `crop_statistics/sbos_{development_statistics_sindh_2018,sindh_agricultural_statistical_report}.pdf` | Day 11/49 district references |
| Meta Relative Wealth Index (Pakistan, 2.4 km tiles) | `socioeconomic/meta_relative_wealth_index_pak.csv` | context only: stratifying errors (Day 87), discussion; never a target |
| World Bank poverty mapping, district level | `socioeconomic/wb_poverty_mapping_district_pak.xlsx` | same |
| GADM 4.1 Pakistan, all levels | `../raw/gadm/gadm41_PAK.gpkg` | Day 12 admin candidate (alongside geoBoundaries and OCHA) |
| HydroRIVERS (Sindh clip), OSM structural drains, perennial rivers | `../raw/hydrosheds/hydrorivers_sindh.gpkg`, `../raw/osm/derived/*.gpkg` | Day 23 corridors, Day 38 river/drain distances, Day 71 drainage edges |

**Results from your earlier Sindh projects** (`prior_work/`; the originals stay in `C:\Projects`).
These are external comparisons only. They must never become model inputs for test years:

| project | files | use in VISTA |
|---|---|---|
| flood-recovery-sindh | `flood_recovery_sindh/analysis_grid.gpkg` (555k cells), `master_dataset.parquet`, `recovery_metrics.parquet`, `trajectory_clusters.parquet`, `sm_persistence.parquet`, `flood_duration/flood_dur_<district>.csv` (join on `cell_id`) | Day 81-90 validation against the 2022 flood (plan Section 10: "2022 flood products"); Day 60 trajectory comparison |
| RHAI | `rhai/sindh_villages.gpkg` (5,159 OSM villages), `rhai_village_scores.csv`, `rhai_traveltimes.csv`, `village_population.csv`, `district_crosswalk.csv` | Day 12 district name crosswalk, Day 13 settlement cross-check, Day 39 access cross-check |
| SWAI | `swai/village_{water_distance,rainfall_v2,dryrain,elevation_v2,ndwi}.csv`, `indicators_raw.csv` (same 5,159 villages, `village_id`) | Day 26 acceptance (independent local check of the GEE zonal values), Day 38 distances |

Your own manuscripts (FHARI, CODA, the flood-recovery NHAZ submission) are copied into
`documentation/literature/own_work/` for novelty positioning (Days 2 and 98). VISTA must cite them and say how it differs.

Literature PDFs (Day 2 library) go in `documentation/literature/`. So far: Siyal et al. 2015
(JARS, Landsat rice yield in Larkana) and Shah & Ai 2025 (*Land* 14:340, winter crops in Ghotki).

Derived: `data/village_inventory/admin/sindh_adm{1,2,3}[_simplified].geojson` (1 province,
22 districts, 125 talukas) and `sindh_admin_names.csv`.

**Not downloaded, on purpose:**
- Geofabrik OSM PBF (about 250 MB). It isn't needed: the Geofabrik shapefile extract above has the
  same layers. Fetch the PBF with `python scripts/download_data.py --large` only if you need tags the
  shapefiles drop.
- Microsoft/Overture footprints (tens of GB). Open Buildings v3 is pulled through Earth Engine instead (`open_buildings_centroids`).
- Everything satellite or climate: Earth Engine produces it.

### Known data issues

- geoBoundaries ADM2 has **no Larkana district** and uses the pre-2017 district set. That is
  why GEE jobs chunk by taluka (ADM3, 125 units). Rebuild districts from OCHA COD-AB on Day 12 (D002).
- geoBoundaries ADM3 has **no Jacobabad taluka** (3% covered) and lacks Islamkot, Kaloi and Dahli.
  From Day 12 on, OCHA COD-AB 2022 is the admin spine (D005). `open_buildings_gaps` exported the
  buildings that the geoBoundaries-based job missed.
- The PBS Sindh report URL given in the plan (`/sites/default/files/...`) returns 404. The working
  path is `/wp-content/uploads/2020/07/mouza_census_2020_sindh_report.pdf`, and the downloader now uses it.

## Repository layout (Section 12.2)

```
configs/            gee.yaml, gee_jobs.yaml (+ resolved_assets.json after verify-assets)
data/raw/           downloads + manifest.csv
data/village_inventory/{admin,settlements,registry,zones}/
data/{satellite,climate,reference,processed}/
gee/                run.py (CLI), jobs.py (registry), interactive.py, lib/{common,zonal,manifest,
                    optical,radar,coarse,landcover,static,settlements}.py
src/{preprocessing,village_mapping,feature_engineering,temporal_analysis,
     graph_construction,models,validation,visualization,utils}/
scripts/            download_data.py, prepare_admin.py, make_zones.py, gee_to_long.py, drive_fetch.py,
                    parse_pbs_mouza.py, admin_crosswalk.py, admin_history.py, settlement_sources.py,
                    build_settlements.py, attach_names.py, flag_urban.py, parse_deh_list.py,
                    assign_deh.py, build_registry.py
experiments/        gee_task_manifest.csv, run registry
outputs/{maps,figures,tables,predictions}/
documentation/      day_tracker.csv, DECISIONS.csv, LOG.md, charter.md, compute.md, data/model cards
manuscript/  notebooks/  tests/
```

## Earth Engine design

- **Jobs = plan days.** `python -m gee.run list-jobs` prints the table. Zonal jobs take any
  zones asset with `vid`, `zone` (core/resource/connectivity) and `chunk`.
- **Yearly multi-band stacks** (`<var>_<YYYYMM>`) are reduced once per chunk of zones, giving
  about 12x fewer tasks than one task per month (Day 26). Every mean comes with a valid-pixel `count`.
- **Leakage-safe timing.** MODIS composites are re-stamped to their end date before monthly
  grouping. Gap-filled MODIS ET/GPP are flagged non-causal. Embeddings must be lagged one year.
  Climatologies and SPI/SPEI parameters are fitted locally on training years only.
- **Resumable.** `experiments/gee_task_manifest.csv` records every task. Re-running a wave
  skips tasks that are done or active. `retry-failed` re-arms the failed ones.
- **No GCS needed.** Exports go to Drive. Zone uploads are client-side parts, merged when read.

## Day-to-code map for the first 40 days

| day | command / file |
|---|---|
| 6 | `python -m gee.run check`; `environment.yml`, `requirements-gee.txt`, `src/utils/seed.py` |
| 8 | `python -m gee.run verify-assets` |
| 10 | `python -m gee.run smoke5` |
| 11 | `scripts/parse_pbs_mouza.py` -> `data/village_inventory/pbs_sindh_tables/`; `documentation/unit_memo.md` |
| 12 | `scripts/admin_crosswalk.py` -> `admin_boundaries.gpkg`, `taluka_crosswalk.csv` |
| 13 | `submit open_buildings_centroids`, `submit settlement_evidence`; `scripts/settlement_sources.py` |
| 14 | `src/village_mapping/settlements.py`; `scripts/build_settlements.py pilot`, `sensitivity` |
| 15 | `scripts/build_settlements.py province` -> `settlements_v0.parquet` |
| 16 | `scripts/attach_names.py`; `scripts/flag_urban.py` (gee job `smod_grid`) |
| 17 | `scripts/parse_deh_list.py` (Board of Revenue deh list), `scripts/assign_deh.py` (proxy dehs) |
| 18 | `scripts/build_registry.py`, `src/village_mapping/ids.py`, `tests/test_ids.py`, `tests/test_registry.py` |
| 23 | `src/village_mapping/zones.py`, `scripts/make_zones.py` |
| 26 | `gee/lib/zonal.py`, `gee/lib/manifest.py`, `upload-zones`, wave 2 |
| 27-29 | `gee/lib/optical.py` (S2, Cloud Score+), `s2_zonal` |
| 30-31 | `gee/lib/optical.py` (Landsat, Roy 2016), `landsat_zonal`, `landsat_season_zonal` |
| 32 | `gee/lib/radar.py`, `s1_zonal` |
| 33 | `gee/lib/landcover.py`, `dw_zonal` |
| 34 | `gee/lib/coarse.py`, `modis_*_zonal` |
| 35-36 | `chirps_grid`/`chirps_zonal`, `era5_grid`/`era5_zonal` (SPI/SPEI are computed locally) |
| 37 | `jrc_zonal`, `jrc_static_zonal` |
| 38-39 | `terrain_zonal`, `context_zonal` |
| 40 | `scripts/gee_to_long.py` -> env_store_v0.9 |

Days 41-100 (indicators, trajectories, models, validation, manuscript) are local Python under
`src/`. The PDF's code for zones, spatial CV, conformal intervals, skill/bootstrap, fusion and
GATv2 is already in place. The rest is specified day by day in `documentation/day_tracker.csv`.
