# Day 15: province-wide settlement polygons v0

Command: `python scripts/build_settlements.py province` (about 8 minutes on 12 CPU threads, a single
process). Output: `data/village_inventory/settlements/settlements_v0.parquet` (GeoParquet, EPSG:4326,
76 MB, not in Git). Tables: `outputs/tables/day15_qc_topology.csv`,
`outputs/tables/day15_settlement_counts_by_taluka.csv`.

## Inputs

* Open Buildings v3 centroids from 127 files: the 125 geoBoundaries talukas plus the 2 OCHA gap tehsils
  (Jacobabad, Bin Qasim) exported by `open_buildings_gaps`. 13,011,001 unique buildings after
  de-duplication by plus_code.
* Parameters (D006): 40 m dilation, at least 5 buildings, 10 m grid. Village tier at 150 m.

## Result

| item | value |
|---|---|
| hamlet clusters (inventory unit) | 159,593 |
| village tier | 24,077 |
| buildings in clusters | 12,627,875 (97.1%) |
| buildings per cluster | median 15, p90 103, p99 614 |
| invalid geometries | 2,360 before `make_valid`, 0 after |
| overlapping cluster pairs | 0 |
| clusters whose centroid lies outside every OCHA tehsil | 304 (coast and border slivers; kept, `adm3_pcode` empty) |
| tehsils with clusters | 122 of 125, in all 29 districts |

Compared with PBS 2020 across the 105 talukas that have rural settlements, hamlets are a median 5.4x
the PBS settlement count (IQR 3.8-7.8). The village tier is a median 0.69x (IQR 0.45-1.26). The pilots
agree with Day 14: Sanghar 0.91, Shah Bunder 0.64, Mithi 3.99 at the village tier. Jacobabad, which
was missing before D005, now has 1,221 hamlets (village tier 0.55x PBS).

## Known limits (to handle on Days 16-20)

* **Cities chain into single clusters.** The 105 clusters with >= 5,000 buildings hold 4.6 M
  buildings. Karachi Central alone is one 1.9 M-building cluster, and Landhi, Hyderabad City, Larkana
  and Sukkur form similar large blocks. They are urban fabric, not villages. They will be flagged with
  GHSL SMOD and a size threshold, and left out of the rural model population. This is not done yet.
* Clusters are built from centroids, so they are about half a building width smaller than the GEE
  footprint version (Day 14, area 5-11% less).
* No names, VIDs or deh assignment yet (Days 16-18). `cluster` is a run-specific integer: it is
  deterministic for a given input but is not a persistent ID.
