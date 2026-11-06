# Day 14: pilot settlement clustering and parameter choice

Scripts: `src/village_mapping/settlements.py` (method), `scripts/build_settlements.py pilot|sensitivity`,
tests in `tests/test_settlements.py`. Tables: `outputs/tables/day14_local_vs_gee.csv`,
`outputs/tables/day14_parameter_sensitivity.csv`.

## Method

Open Buildings v3 centroids (confidence >= 0.65) are painted on a 10 m grid in EPSG:32642, dilated with
a square of half-width `dilate_m`, split into 8-connected components, and components with at least
`min_buildings` buildings are kept. This is the method of the Earth Engine job `provisional_settlements`,
run locally in 40 km tiles. Union-find across tile seams makes the result identical to clustering in a
single tile (tested).

## 1. Local run vs Earth Engine (40 m, >= 5 buildings, geoBoundaries pilot polygons)

| pilot | buildings | local clusters | GEE clusters | buildings in clusters, local / GEE | area IoU | GEE clusters matched 1:1 |
|---|---|---|---|---|---|---|
| Mithi | 298,397 | 2,038 | 1,999 | 279,060 / 279,391 | 0.943 | 95.5% |
| Sanghar | 190,006 | 5,241 | 5,002 | 180,686 / 181,424 | 0.902 | 94.6% |
| Shah Bunder | 51,655 | 1,318 | 1,244 | 48,932 / 49,150 | 0.884 | 94.3% |

The local clusters are slightly smaller (area 5-11% less), as expected: GEE paints footprint
polygons and the local run paints centroids. A few GEE clusters split into two local ones (61 / 237 / 63),
where two hamlets are joined only through building edges. The local method reproduces GEE closely
enough to replace it for the province run, which avoids about 125 Earth Engine tasks and seams at
taluka borders.

## 2. Sensitivity (OCHA tehsil polygons, so PBS 2020 counts refer to the same area)

Clusters per PBS settlement, `min_buildings = 5`:

| dilate_m | Mithi (desert) | Sanghar (canal plain) | Shah Bunder (delta) |
|---|---|---|---|
| 20 | 8.10 | 15.92 | 4.71 |
| 40 | 5.58 | 12.69 | 3.75 |
| 60 | 4.99 | 9.32 | 2.88 |
| 100 | 4.96 | 3.82 | 1.58 |
| 150 | 4.03 | 1.00 | 0.72 |
| 250 | 1.38 | 0.21 | 0.17 |

At every setting, 91-100% of buildings fall in a kept cluster. The full grid (6 dilations x 5
minimum sizes) is in the CSV.

## Decision (D006)

1. **Hamlet tier = inventory unit: 40 m, >= 5 buildings.** This is the setting the GEE pilot zones and the
   Day 26 acceptance already use. It is a physical unit: a contiguous group of houses that shares one core
   and resource zone. It is 4-13x finer than the PBS settlement count, because PBS counts a named *goth*
   with its outlying hamlets as one settlement.
2. **Village tier = hamlets merged at 150 m**, stored as `village_tier` on every hamlet. In the canal plain
   it reproduces the PBS count exactly (411 vs 411) and in the delta it is close (0.72). The desert stays
   high (4.0) because Thar *dhanis* are spread out over kilometres, and no single distance fits Thar and
   the canal plain together. The village tier is used only for comparisons with PBS and for sensitivity
   tests, not as the modelling unit.
3. Thresholds above 150 m start chaining villages along canals and roads (Sanghar: 86 clusters at 250 m),
   so they are rejected.

Still open from the Day 14 checklist: visual QC of 90 clusters (30 per pilot) against imagery. This has
to be done by hand, so it is left for the author.
