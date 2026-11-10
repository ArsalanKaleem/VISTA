# Coverage report, inventory v1.0 (Day 24)

Tables: `outputs/tables/coverage_by_district.csv`, `outputs/tables/coverage_by_tehsil.csv`. Map:
`outputs/maps/interactive_map.html` (tehsil choropleth of building coverage; the three pilot talukas' hamlets
by quality class, over OpenStreetMap or Esri imagery). Script: `scripts/coverage_report.py`.

## Definitions

* **Unit.** A hamlet is a cluster of Open Buildings v3 footprints (confidence >= 0.65) joined at 40 m with at
  least 5 buildings (D006). The *rural population* excludes urban-class clusters (GHSL SMOD 2020 >= 22 or >= 5,000
  buildings, D007). Quality classes Q1-Q3 are defined in D009.
* **Building coverage (Q1-Q2)** of a tehsil = buildings inside its Q1-Q2 rural hamlets / all Open Buildings in
  the tehsil that are not in an urban-class cluster. The denominator counts buildings in Q3 hamlets and in groups
  of fewer than 5 buildings, so the measure is the share of rural built fabric the model population represents.
  It is computed from the footprint and registry files, never assumed.
* **PBS comparison** = village-tier units (hamlets merged at 150 m) per PBS 2020 rural settlement of the same
  OCHA tehsil (crosswalk of Day 12). PBS counts are a comparison, not ground truth: PBS counts a named *goth*
  with its hamlets as one settlement.
* **Matching accuracy** (precision, recall, boundary IoU, name agreement, kappa) comes from the Day 21-22
  validation sample. **That sample has not been labelled**, so the `validation_precision` and
  `validation_recall` columns are empty.
* The plan's variant "share of PBS-reported rural populated area" cannot be computed: the PBS tables parsed on
  Day 11 report mouza and settlement counts, not area, by taluka.

## Province

| measure | value |
|---|---|
| rural hamlets (29 districts, 125 tehsils) | 155,444 with a tehsil, plus 287 coastal / border slivers outside every tehsil |
| Q1 / Q2 / Q3 | 27,002 / 76,657 / 52,072 (Q1-Q2 share 66.6%) |
| village-tier units | 23,979 |
| building coverage Q1-Q2, province | 0.766 (dragged down by the Karachi districts) |
| building coverage Q1-Q2, 25 non-Karachi districts | 0.85-0.93 (median 0.90) |
| villages per PBS settlement, non-Karachi districts | 0.17 (Hyderabad) to 2.5 (Tharparkar); median 0.75 |

Lowest non-Karachi coverage: Sujawal 0.85, Jamshoro 0.86, Kashmore 0.87, Thatta 0.88 (delta and riverine
districts with many small hamlets below 10 buildings). Highest: Tando Allahyar 0.93, Larkana 0.93, Mirpur
Khas 0.93.

## Reading the PBS ratio

Villages per PBS settlement is near 1 in the canal plain (Dadu 0.95, Ghotki 0.98, Sujawal 0.95) and in the
delta, above 1 where settlement is dispersed (Tharparkar 2.5, Jamshoro 2.1, Kambar Shahdadkot 1.4), and well
below 1 in districts where OSM / GeoNames names are sparse and large *goths* are counted by PBS as several
settlements (Hyderabad 0.17, Naushahro Feroze 0.42). Neither direction is an error of the inventory; the
ratio is reported so that later comparisons with PBS statistics use the right expectation.

## Atlas

`outputs/maps/atlas_v0.1.pdf`: 20 sheets (2 per district for 10 districts, one small and one large Q1 hamlet
each) showing the settlement polygon, core (100 m), resource zone, connectivity corridors, neighbouring
hamlets, building centroids, roads and waterways. There is no satellite backdrop: no Sentinel-2 imagery is
held locally. The sheets have not been visually checked by a person.
