# Compute budget for the province-wide extraction (Day 9 item, written Day 23)

Source: Earth Engine operations list for project vista-sindh (`experiments/ee_operations_snapshot.csv`,
350 operations, fetched 2026-11-11). Pilot wave 2 = 12 products, one year each, 8,245 hamlets / 16,489 zones.

## Measured

| product (pilot, monthly stacks unless noted) | EECU-s per task (median) | hamlets per task | EECU-hours per 1,000 hamlet-years |
|---|---|---|---|
| Sentinel-2 (10 m, 12 monthly medians, 7 vars) | 26,739 | 1,000 | 7.4 |
| Sentinel-1 (20 m, flood logic) | 7,047 | 500 | 14.1 |
| Dynamic World (10 m, 8 classes) | 4,423 | 1,000 | 1.2 |
| Landsat (30 m, 4 sensors) | 3,424 | 1,000 | 0.95 |
| MODIS LST (1 km) | 58 | 2,000 | 0.008 |
| MODIS VI (250 m) | 26 | 2,000 | 0.004 |
| JRC monthly water (30 m) | 88 | 2,000 | 0.012 |
| CHIRPS zonal (sampled at 100 m) | 278 | 4,000 | 0.019 |
| ERA5-Land zonal (sampled at 100 m) | 170 | 4,000 | 0.012 |
| terrain / context / JRC static (one-off) | 36-72 | 2,000 | 0.005-0.010 per 1,000 hamlets |

Whole pilot wave: 157 EECU-hours of batch compute in 83 wall-clock hours. At most **one task ran at a
time** (noncommercial batch queue), so throughput is about **1.9 EECU-hours per wall hour**. Everything
below converts EECU-hours to days with that rate. Local disk: 12 GB free (2026-11-11).

## The quota (found 2026-11-11)

On submitting the v1.0 zone upload the API warned: *project has exceeded its noncommercial compute quota and is
now in restricted mode*. Earth Engine's noncommercial tiers (developers.google.com/earth-engine/guides/
noncommercial_tiers) give a **Community tier of 150 EECU-hours per calendar month** (reset on the 1st, midnight
PT, no carry-over), a **Contributor tier of 1,000 EECU-hours per month** (needs a billing account attached;
noncommercial use is not charged) and a **Partner tier of 100,000 EECU-hours** (application, review of up to
several weeks). The pilot wave used 157 EECU-hours: it consumed the whole November allowance, which is why
tasks ran one at a time ("restricted mode limits your online and batch concurrency"). Tasks still run in
restricted mode, only slowly.

Consequence: the plan below is a budget against **1,000 EECU-hours per month at best without a Partner
application**. Wave 3A (about 70 EECU-hours) fits any tier; wave 3B (about 1,575) needs the Contributor tier
for two months or the Partner tier; wave 3C (about 700) likewise. See D012.

## Province (Q1-Q2 rural hamlets: 103,659, core + resource zones = 12.6 x pilot)

| product, period | EECU-hours | wall days at 1.9/h | verdict |
|---|---|---|---|
| S2 monthly 2017-2025 | 6,900 | 150 | not feasible |
| S1 monthly 2015-2025 | 16,100 | 350 | not feasible |
| Landsat monthly 2000-2025 | 2,550 | 56 | not feasible |
| Dynamic World monthly 2016-2025 | 1,240 | 27 | marginal |
| **S2 seasonal (Rabi/Kharif) 2017-2025** | ~1,150 | 25 | run in two batches |
| **Landsat seasonal 2000-2025** | ~425 | 9 | run |
| **MODIS VI + LST + ET 2000-2025** | ~40 | 1 | run first |
| JRC monthly 2000-2021 | 26 | 0.6 | run first |
| terrain, context, JRC static | ~3 | 0.1 | run first |
| CHIRPS + ERA5 zonal 1981-2025 | 144 | 3 | **compute locally** from the exported grids (D003; Day 26 showed 99-100% agreement) |

## Decision D011: tiered extraction

1. **Wave 3A, province, now.** terrain, context, jrc_static, jrc (2000-2021), modis_vi, modis_lst, modis_et
   (2000-2025), on all Q1-Q2 zones, `chunk_group: 40` (10,000 hamlets per task). About 70 EECU-hours,
   about 2 days of queue time, roughly 330 tasks.
2. **Wave 3B, province, after 3A.** `s2_season_zonal` 2019-2025 (test window first), then
   `landsat_season_zonal` 2000-2025, then `s2_season_zonal` 2017-2018. About 1,575 EECU-hours, five weeks
   of queue time. Submitted in that order because the queue is serial.
3. **Wave 3C, samples.** Monthly S2 (2017-2025, about 530 EECU-hours) and Dynamic World on the three pilot
   talukas; Sentinel-1 only for flood years (2022 exists; 2020 and 2023 to add). Monthly dynamics are
   modelled province-wide from MODIS (16-day, 250 m) and seasonal S2 / Landsat; the pilot sample
   quantifies what the seasonal composites miss.
4. **Local.** CHIRPS and ERA5-Land zonal series 1981-2025 from the grids; SPI/SPEI fitted on training years.
   GHSL SMOD and other context rasters likewise.

What this gives up, stated plainly: there is no province-wide monthly 10 m optical series and no
province-wide SAR flood series. Flood exposure province-wide comes from JRC monthly water (to 2021),
MODIS-scale inundation signals and the seasonal S2 water fraction; the S1 flood product is a pilot-only
layer unless the quota changes. The ablation of Milestone 3 ("proceed without a product and register the
loss") applies to S1.

## Decision D012: quota actions (user actions, proposed)

1. Attach a billing account to project vista-sindh and select the Contributor tier (free for noncommercial
   use; +850 EECU-hours per month, applied immediately).
2. Apply for the Partner tier with the budget above (draft text: documentation/ee_partner_tier_request.md).
3. Until then: submit wave 3A as soon as the zones are uploaded (it runs in restricted mode and completes
   within the December allowance); hold 3B and 3C; CHIRPS/ERA5/SMOD stay local.

## Decision (user, 2026-11-11): stay on the Community tier

150 EECU-hours per month is the budget. What fits, by month, after the zone upload finishes:

| month | run | EECU-hours |
|---|---|---|
| December 2026 | wave 3A: terrain, context, JRC static + monthly, MODIS VI / LST / ET, all Q1-Q2 zones | ~70 |
| December 2026 | wave 3s-1: Landsat seasonal 2000-2025 on a stratified sample of 10,000 Q1-Q2 hamlets | ~40 |
| January 2027 | wave 3s-2: S2 seasonal 2017-2025 on the same 10,000-hamlet sample | ~110 |
| February 2027 | wave 3s-3: S2 monthly 2017-2025 on 2,000 of those hamlets (the fine-scale sample) | ~135 |
| later / never | province-wide seasonal S2 (~1,150), S1 (pilot only), DW province | not on this tier |

So the design becomes **province coarse + sample fine**: MODIS (250 m, 16-day) and the local CHIRPS/ERA5
series carry every Q1-Q2 hamlet; Sentinel-2 and Landsat describe a 10,000-hamlet stratified sample (by
district, ecoregion and quality class), and monthly 10 m dynamics a 2,000-hamlet subsample. Models that need
10 m inputs are trained and evaluated on the sample, and the sampling weights are reported. Samples are drawn
on Day 27 with a logged seed (`scripts/sample_hamlets.py`, to write).

## Checks to keep

* Record EECU per task from the operations list after each wave (`experiments/ee_operations_snapshot.csv`).
* If more than one task is ever observed RUNNING at once, the wall-day figures above shrink accordingly.
