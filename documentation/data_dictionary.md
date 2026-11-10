# Data dictionary: village inventory v1.0

Files under `data/village_inventory/registry/` (frozen copy in `data/village_inventory/village_inventory_v1.0/`,
see `CHANGELOG.md` there). CRS EPSG:4326 unless noted; areas in square metres computed in EPSG:32642.

## village_registry.parquet (GeoParquet), one row per hamlet

| column | type | meaning |
|---|---|---|
| vid | str | persistent hamlet ID: `SD` + OCHA district code (2) + tehsil code (3) + H3 res-10 cell of the building-weighted centroid + 2-char tie-breaker. Never encodes a name. Rerun-identical (tests/test_registry.py) |
| vvid | str | village-tier ID (`SV` + same scheme) of the hamlets merged at 150 m (D006) |
| district_code, taluka_code | str | from the OCHA p-codes PK7dd / PK7ddtt; 99 / 999 outside every tehsil |
| adm2_pcode, adm2_name, adm3_pcode, adm3_name | str | OCHA COD-AB 2022 district and tehsil containing the centroid (D005) |
| deh, deh_sno, deh_method | str, int, str | proxy deh (Board of Revenue name) by name-anchored Voronoi (D008); `deh_method` = `name_anchor_voronoi` or `none` |
| name | str | primary place name, raw spelling from OSM or GeoNames (Arabic script kept as is) |
| name_key | str | matching key: lower-case ASCII, generic words (goth, deh, jo, ...) removed |
| name_source, name_match | str | `osm` / `geonames`; `inside` (point inside the polygon) or `near` (nearest within 250 / 500 m) |
| n_name_candidates | int | number of OSM + GeoNames records attached to the hamlet |
| name_status | str | `unnamed`, `unique`, `homonym` (same name elsewhere in the tehsil, > 600 m), `village_shared` (hamlets of one village), `conflict_kept` / `conflict_dropped` (one place named twice, Day 19) |
| village_name | str | name of the village tier (its largest named hamlet) |
| settlement_class | str | `rural` (SMOD 11-13), `peri_urban` (21), `urban_cluster` (22-23), `urban_centre` (30 or >= 5,000 buildings) (D007) |
| in_rural_population | bool | rural or peri-urban: the model population |
| smod_2000, smod_2010, smod_2020, smod_max_2020 | uint8 | GHSL SMOD L2 code at the centroid (and the highest code under the polygon, 2020) |
| quality_class | str | Q1 corroborated (>= 10 buildings and an independent name), Q2 robust (>= 10 buildings, confidence >= 0.70), Q3 weak (D009) |
| n_buildings | int | Open Buildings v3 centroids (confidence >= 0.65) in the cluster |
| building_area_m2 | float | sum of footprint areas |
| mean_conf | float | mean Open Buildings confidence |
| area_m2 | float | cluster polygon area (10 m grid, 40 m dilation) |
| village_tier_buildings, village_tier_hamlets | int | size of the village tier the hamlet belongs to |
| lon, lat | float | building-weighted centroid (WGS84) |
| source, params | str | `open_buildings_v3`; clustering parameters |
| registry_version, id_scheme | str | `v0.6` -> frozen as `v1.0`; ID scheme string |
| geometry | polygon | cluster polygon |

## crosswalks/

| file | columns | meaning |
|---|---|---|
| vid_cluster.csv | vid, cluster | run-specific cluster integer of settlements_v0 |
| vid_deh.csv | vid, deh, deh_sno, deh_method | proxy deh |
| vid_pilot_v0.csv | pilot_vid, vid, share_of_pilot, share_of_registry, n_registry_overlaps | wave 2 pilot zone VIDs (geoBoundaries codes) to registry VIDs by core overlap |

## Other registry files

| file | meaning |
|---|---|
| merge_log.csv | every Day 19 decision (rules R1-R4) with the VIDs involved |
| review_sample.csv | 300 decisions for manual review (blank `reviewer_verdict`) |
| unmatched_records.csv | named places and dehs without a hamlet, with the reason |
| quality_summary.csv | Q1-Q3 counts and excluded shares by district |
| registry_summary.csv | headline counts |

## zones/v1/ (Day 23, D010)

| file | key columns | meaning |
|---|---|---|
| zones_core.parquet | vid, quality_class, adm3_pcode, area_m2 | settlement polygon buffered 100 m |
| zones_resource.parquet | vid, r_max, area_m2 | Voronoi cell clipped to the tehsil, within r_max of the settlement, minus all cores and the water / urban mask |
| zones_connectivity.parquet | vid, n_edges, network_km, area_m2 | roads / canals / drains (25 m buffer) inside the 100 m corridors to the 8 nearest hamlets, within 5 km |
| village_graph_knn8.parquet | vid_i, vid_j, dist_m, road_m, canal_m, drain_m, same_tehsil | k-nearest-neighbour edges with network length by class |
| zones_upload_q12.parquet | vid, zone, area_m2 | long table of Q1-Q2 core + resource zones, simplified 5 m, for `gee.run upload-zones` |
| zone_qc.csv | | area distributions, empty and invalid counts, overlap check |

## Licences

Open Buildings v3 (CC BY 4.0 / ODbL), OpenStreetMap (ODbL), GeoNames (CC BY 4.0), OCHA COD-AB (CC BY-IGO),
GHSL (CC BY 4.0), Board of Revenue Sindh deh list (public listing). See
`documentation/licences_settlement_sources.md`. Derived inventory files are released under CC BY 4.0 with
attribution to those sources.
