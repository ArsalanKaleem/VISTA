# Earth Engine runbook for tomorrow (2 November 2026)

You do this once the Cloud project exists. Every step is one command. Run them from the repo
root (`C:\Projects\VIsta`). Expect about 1 hour of hands-on time; the batch exports keep running
in Google's queue after that.

> **Status (2026-11-01, evening):** steps 1-7 are done on project `vista-sindh`. Check, verify-assets
> (all 33 IDs resolve) and smoke5 (MAE 0.032) all passed, and wave 1 has been submitted. Asset
> writes first returned 404, because the project's asset root did not exist yet. It became writable
> about 7 minutes after the project was opened in the Code Editor, and then step 8 (upload-admin) went
> through. Drive exports land in the Drive of the Google account that is signed in to Earth Engine on this PC.

## 0. Before you start

- **Disk:** C: had only about 2-3 GB free tonight. Free at least 10 GB before installing
  anything. The full environment with PyTorch needs about 6 GB. The GEE-only install needs about 200 MB.
- Exports go to **Google Drive** (folders `vista_gee_<product>`). Check that Drive has a few GB free.

## 1. Cloud project and Earth Engine registration (Day 6)

1. Go to https://console.cloud.google.com and create a project, e.g. `vista-sindh`. Note its **project ID**.
2. Enable the **Earth Engine API** for that project (APIs & Services, then Library).
3. Register the project for Earth Engine at https://code.earthengine.google.com/register
   (noncommercial / research use).
4. Record the project ID, quota tier and concurrent-task limit in `documentation/compute.md`.

## 2. Install and authenticate

```bash
pip install -r requirements-gee.txt
```

```bash
earthengine authenticate
```

## 3. Point the config at your project

In `configs/gee.yaml` replace both `YOUR_CLOUD_PROJECT_ID` values:

```yaml
gee:
  project: vista-sindh
  asset_root: projects/vista-sindh/assets/vista
```

## 4. Run the offline test (optional, 5 s)

```bash
python -m pytest -q tests
```

## 5. Day 6: connectivity check

This prints the monthly NDVI over a 10 km box near Hyderabad, creates the asset folder, and
submits one tiny Drive export.

```bash
python -m gee.run check
```

## 6. Day 8: verify every dataset ID

This writes `configs/resolved_assets.json` (which every job then uses),
`documentation/assets_report.md` and `outputs/tables/assets_verification.csv`.

```bash
python -m gee.run verify-assets
```

Read the report. Things to act on:
- Any `MISS` row means you need a successor ID: edit the candidate list in `configs/gee.yaml` and re-run.
- In the S1 orbit counts by year (in the JSON at the end), pick the pass with more scenes over
  Sindh and set `products.s1.orbit_pass`.
- The ERA5 PET sign is expected to be negative (ECMWF convention); the code multiplies it by -1000.
- Check the JRC monthly last date (expected 2021-12) and the S1B last date (expected Dec 2021).

## 7. Day 10: smoke test (5 points, leakage guard)

```bash
python -m gee.run smoke5
```

Writes `data/processed/smoke_s2_ndvi.csv` and `documentation/smoke_test_report.md`.

## 8. Upload the Sindh admin layers (3 small tasks)

```bash
python -m gee.run upload-admin
```

```bash
python -m gee.run status
```

Wait until the three `upload_admin_*` tasks show `SUCCEEDED`/`COMPLETED` (1-5 minutes). Wave 1
needs them for the per-taluka jobs.

## 9. Wave 1: the batch to submit tomorrow (about 223 tasks)

Preview first, then submit:

```bash
python -m gee.run wave 1 --dry-run
```

```bash
python -m gee.run wave 1
```

| job | tasks | output (Drive folder) | plan day |
|---|---|---|---|
| chirps_grid | 45 | `vista_gee_chirps_grid/chirps_grid_<year>.tif` (60 bands: precip, rdays, rx1, rx5, cdd x 12) | 35 |
| era5_grid | 45 | `vista_gee_era5_grid/era5_grid_<year>.tif` (11 vars x 12 months) | 36 |
| grace_grid | 1 | `vista_gee_grace/grace_lwe_2002_2025.tif` (regional context only) | 36 |
| settlement_evidence | 1 | `vista_gee_settlements/settlement_evidence_by_taluka.csv` | 13 |
| provisional_settlements | 6 | asset `settlements/provisional_<TALUKA>` + `prov_settlements_<TALUKA>.geojson` | 14 |
| open_buildings_centroids | 125 | `vista_gee_open_buildings/open_buildings_<TALUKA>.csv` | 13 |

Monitor (refreshes every 10 minutes, Ctrl+C to stop):

```bash
python -m gee.run status --watch 10
```

If tasks fail, read the error in `experiments/gee_task_manifest.csv`, fix the cause, then:

```bash
python -m gee.run retry-failed
```

```bash
python -m gee.run wave 1
```

Re-running a wave only resubmits tasks that are not already done or running.

## 10. Wave 2: pilot zonal run (Day 26 test), once wave 1's provisional settlements finish

**State on 2026-11-02:** wave 1 finished (224/224). Already downloaded and checked: the 3 pilot
settlement GeoJSONs, settlement evidence, CHIRPS 45/45, ERA5 45/45, GRACE. Still to download: 112 of
the 125 Open Buildings CSVs (13 Karachi ones are here). Still to install: geopandas, pyogrio, pyarrow,
h3 and pyproj. The connection was too unstable for both. On a good connection:

```bash
pip install -r requirements-gee.txt
```

```bash
python scripts/drive_fetch.py get vista_gee_open_buildings data/village_inventory/raw/footprints/open_buildings
```

`scripts/drive_fetch.py` uses the Earth Engine login's Drive access. It resumes interrupted files
(`.part`), skips files already complete, and `list` shows every `vista_gee_*` folder.

1. The pilot `prov_settlements_*.geojson` files are already in `data/village_inventory/settlements/`.
2. Build the zones (needs geopandas; Thar talukas get r_max = 4 km):

```bash
python scripts/make_zones.py data/village_inventory/settlements/prov_settlements_MITHI.geojson data/village_inventory/settlements/prov_settlements_SANGHAR.geojson data/village_inventory/settlements/prov_settlements_SHAH_BUNDER.geojson --out data/village_inventory/zones/pilot_zones_v0.geojson
```

3. Upload them and wait for the part tasks to finish:

```bash
python -m gee.run upload-zones data/village_inventory/zones/pilot_zones_v0.geojson zones/pilot_v0
```

4. Submit the 12 pilot jobs (one year each):

```bash
python -m gee.run wave 2
```

5. Convert a result to long format and compare it with a local check (Day 26 acceptance):

```bash
python scripts/gee_to_long.py path/to/s2_zonal_pilot_v0_2023_c0000-0003.csv --product s2_zonal --out data/satellite/s2/pilot_s2.parquet
```

Waves 3 (province run on inventory v1.0, Days 28-39) and 4 (embeddings, chips, maps) come
later. They use the same commands; see `configs/gee_jobs.yaml`.

## Likely problems and what to do

| symptom | likely cause | fix |
|---|---|---|
| `ee.Initialize failed` | not authenticated / project not registered | step 1.3 and `earthengine authenticate` |
| chirps_grid task "computation timed out" or "memory" | RX5 nested 5-day sums | lower to one task per half-year, or drop rx5 and derive it locally |
| provisional_settlements "too many pixels"/memory | large taluka at 10 m | `submit provisional_settlements --regions <smaller taluka>`, or set `settlements.raster_scale: 20` |
| zonal task "Computation timed out" / "memory limit exceeded" | chunk group too large | re-run the same `wave`/`submit`: failed groups are split into halves automatically (and halved again if those fail). For a whole new run, lower `chunk_group` (e.g. s2 4 -> 2) |
| `Dictionary.get: Dictionary does not contain key` in s1 | month with images but no pixels in the region | report it; set the month's threshold to the fallback |
| an `open_buildings` CSV is very large | dense taluka | normal; buildings on taluka borders appear twice, so dedupe by `plus_code` locally |


## Status 2026-11-11: province zones uploaded, quota

* `zones/v1_0`: 207 parts of 1,000 features (206,782 Q1-Q2 core + resource zones) submitted as asset-export
  tasks; they run one at a time in **restricted mode** (the Community tier's 150 EECU-hours per month were
  used by the pilot wave). Check with `python -m gee.run status`; when no `upload_zones_v1_0_*` task is
  PENDING or RUNNING, submit `python -m gee.run wave 3` (coarse products, about 70 EECU-hours, D011), then
  fetch with `scripts/drive_fetch.py`. Waves `3b` and `3c` wait for the tier change (D012).
* Before any province submission after the 1st of the month, re-read documentation/compute_budget.md.
