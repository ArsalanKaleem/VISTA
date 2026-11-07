# Days 16-18: urban flag, names, deh assignment, registry v0.5

Pipeline (run in this order; each step reads the previous output):

```
python scripts/build_settlements.py province   # Day 15: settlements_v0.parquet
python scripts/attach_names.py                 # Day 16: names_alt.parquet, settlements_v0_named.parquet
python scripts/flag_urban.py                   # Day 16: SMOD classes (needs gee job smod_grid)
python scripts/parse_deh_list.py               # Day 17: official deh list (Board of Revenue)
python scripts/assign_deh.py                   # Day 17: proxy dehs
python scripts/build_registry.py               # Day 18: village_registry.parquet + crosswalks
python -m pytest tests/test_registry.py
```

## Urban flag (D007)

GHSL SMOD 2020 at each cluster's building-weighted centroid (1 km grid, gee job `smod_grid`), plus a size
cap of 5,000 buildings for chained city fabric.

| class | hamlets | buildings | share of buildings |
|---|---|---|---|
| rural (SMOD 11-13) | 103,248 | 3.35 M | 26.5% |
| peri-urban (SMOD 21) | 52,483 | 3.53 M | 28.0% |
| urban cluster (SMOD 22-23) | 3,133 | 1.10 M | 8.7% |
| urban centre (SMOD 30 or >= 5,000 buildings) | 729 | 4.64 M | 36.8% |

**Rural model population** = rural + peri-urban: 155,731 hamlets, 23,979 villages, 6.9 M buildings, the
largest with 4,793 buildings. Peri-urban is kept but flagged, because dense Sindh villages often sit in SMOD
21 cells; results will be checked without it. SMOD for 2000 and 2010 is also stored: 31,933 clusters moved
from rural to peri-urban or urban between 2000 and 2020.

## Names (Day 16)

OSM places (Geofabrik 2026-07-12) and GeoNames populated places. A point inside a hamlet names it;
otherwise it goes to the nearest hamlet within 250 m (OSM) or 500 m (GeoNames). Raw names are kept.
Latin names get a key: lower-case ASCII, with generic words such as *goth*, *deh* and *jo* removed.
Arabic-script names are kept without a transliteration; their hamlet takes the best Latin key among
its other candidates.

* 72,119 name candidates (OSM 6,384; GeoNames 34,785; GeoNames alternate spellings 30,950).
* Named hamlets: 30,493 of 159,593 (19.1%). These hold 76% of all buildings. 39.6% of village-tier units
  are named. 173 named hamlets have no Latin key.
* Per district: `data/village_inventory/naming_coverage.csv`. Unnamed hamlets keep only their VID, which
  the model does not need (plan fallback).

## Deh assignment (Day 17, D008)

* **Official deh list.** Board of Revenue Sindh, *List of Dehs in Sindh* (sindhzameen.gos.pk, 142 pages).
  It has 6,093 dehs in 125 talukas, and serial numbers and per-taluka sequences check out. 106 of the 107
  rural talukas match OCHA tehsils. Kaloi is missing because the list predates its 2016 split from Diplo:
  BoR shows Diplo with 42 dehs, PBS 2020 shows 26. 73 talukas have exactly the PBS 2020 mouza count, and 95
  are within 2 (`deh_counts_by_taluka.csv`).
* **No deh polygons are public.** The Board of Revenue portal shows only scanned deh sheets, and the PBS
  record request sent on 2026-11-07 may go unanswered. Instead, deh names are matched to named hamlets in
  the same tehsil (1,053 exact matches, 374 spelling variants with difflib >= 0.88). That geolocates 1,427
  of 5,990 dehs (24%). Voronoi cells of these anchors, clipped to the tehsil, give named **proxy dehs**
  (median 38 km², versus an average deh of about 23 km²). 97.2% of rural hamlets fall in one.
* Proxy dehs are aggregation units, not surveyed boundaries. Each one may cover several real dehs, and
  they are replaced if real deh polygons become available.

## Registry v0.5 (Day 18)

* `vid` = `SD` + OCHA district code (2 digits) + tehsil code (3 digits) + H3 res-10 cell of the centroid +
  2-character tie-breaker. Village-tier units get `vvid` with prefix `SV`. IDs contain no names.
* The H3 scheme is now required and explicit (`src/village_mapping/ids.py`). Previously a missing h3
  package would silently switch to geohash, which gives different IDs on different machines.
* 159,593 hamlets with 0 duplicate VIDs. VIDs are identical after a rerun, and the crosswalks have no
  orphans (`tests/test_registry.py`).
* Crosswalks in `registry/crosswalks/`:
  * `vid_cluster.csv`: run cluster ids.
  * `vid_deh.csv`: proxy dehs.
  * `vid_pilot_v0.csv`: links the wave 2 pilot data (geoBoundaries-coded VIDs) to registry VIDs. 8,076 of
    8,245 pilot core zones contain a registry hamlet that lies at least 80% inside them.

## Still open

* Visual QC of 90 clusters (Day 14) and the inventory validation sample (Days 21-22). Both are manual.
* Duplicate detection (Day 19): clusters are disjoint by construction, so this is mainly name duplicates
  within dehs.
* Missing-coordinate records and quality classes (Day 20).
