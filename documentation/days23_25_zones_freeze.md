# Days 23-25: province-wide zones, coverage and the v1.0 freeze

```
python scripts/build_zones_v1.py        # core, resource, upload table, QC  (8 min)
python scripts/build_connectivity.py    # knn8 edges, connectivity zones   (resumable; ~15 min)
python scripts/coverage_report.py       # Day 24 tables, QC map, atlas
python scripts/freeze_inventory.py      # Day 25 freeze -> village_inventory_v1.0/
python -m gee.run upload-zones data/village_inventory/zones/v1/zones_upload_q12.parquet zones/v1_0 --part-size 1000
```

## Zones (D010)

| zone | definition | n | empty | median km² | p90 km² | max km² | total km² |
|---|---|---|---|---|---|---|---|
| core | settlement polygon + 100 m | 155,731 | 0 | 0.136 | 0.30 | 6.9 | 28,076 |
| resource | Voronoi cell of the centroid (all hamlets, urban included) clipped to the OCHA tehsil, within r_max of the settlement (2 km; 4 km in Tharparkar and Umerkot), minus every core and the OSM water / urban mask | 155,731 | 722 | 0.213 | 1.15 | 31.0 | 85,312 |
| connectivity | roads, canals and drains (OSM) inside 100 m corridors to the 8 nearest rural hamlets, buffered 25 m, within 5 km of the core | 155,731 | see zone_qc.csv | | | | |

* Resource zones never overlap a core: 0 overlapping pairs in a 20,000-zone sample (and none by construction).
* 0 invalid geometries after `make_valid`.
* 722 hamlets have an empty resource zone (dense clusters whose Voronoi cell is entirely cores or mask); 1,065
  Q1-Q2 hamlets have an empty or zero-area resource zone and keep only their core. The upload table holds
  206,782 features for 103,659 Q1-Q2 hamlets.
* The resource median (0.21 km²) is far below the 2 km disc (12.6 km²) because neighbouring hamlets are
  typically a few hundred metres apart; the Voronoi bound, not r_max, limits most zones. Day 44 tests r_max.
* Village graph: 728,883 unique k = 8 edges with road / canal / drain length per edge
  (`village_graph_knn8.parquet`), the input for the connectivity graph of Day 81.
* Changes from pilot zones v0: resource excludes the own core (plan text "minus all cores"), is masked for
  water and urban fabric, and uses OCHA tehsils.

## Coverage (Day 24)

See `documentation/coverage_report.md`: Q1-Q2 hamlets hold 76.6% of the non-urban buildings of Sindh,
85-93% in the 25 non-Karachi districts. `outputs/maps/interactive_map.html` is the QC map;
`outputs/maps/atlas_v0.1.pdf` has 20 sheets (no satellite backdrop; not visually checked).

## Freeze (Day 25)

`data/village_inventory/village_inventory_v1.0/` (GeoParquet and one GeoPackage with four layers, crosswalks,
logs, sha256 manifest, CHANGELOG.md), Git tag `v0.2.0`. Decision memo:
`documentation/decision_memo_inventory.md`; dictionary: `documentation/data_dictionary.md`. Zenodo draft:
not created (external account action).

## Earth Engine upload and quota

The 206,782 Q1-Q2 zones go up as 208 parts of 1,000 features (`zones/v1_0/part_000..207`). On submission
the API reported the project in **restricted mode**: the Community tier allows 150 EECU-hours per month and
the pilot wave used 157. Wave 3 is therefore tiered (D011) and gated on the tier change proposed in D012.
