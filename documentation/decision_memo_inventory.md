# Decision memo: village inventory v1.0 (Day 25, Milestone 2)

Decision: **go**, with the gaps listed in section 4 carried forward as named limitations. The inventory is
frozen as `data/village_inventory/village_inventory_v1.0/` (sha256 manifest inside), tagged `v0.2.0`.

## 1. Final analysis unit

The unit is the **hamlet**: a contiguous cluster of Open Buildings v3 footprints (confidence >= 0.65) joined at
40 m with at least 5 buildings (D006), identified by a persistent, name-free `vid`. The **village tier**
(hamlets merged at 150 m, `vvid`) exists for comparison with PBS and for sensitivity tests, not as the
modelling unit. Reasons: the hamlet is the physical unit that floods, dries or recovers; it reproduces the
Earth Engine pilot geometry (area IoU 0.88-0.94); and the village tier matches PBS settlement counts only
in the canal plain (Sanghar 0.91, Dadu 0.95) and not in the Thar (4.0), so no single merge distance defines
a village across Sindh.

## 2. Counts, measured from the frozen files

| population | hamlets | village-tier units | buildings |
|---|---|---|---|
| all clusters, Sindh | 159,593 | 24,077 | 12,627,875 |
| urban centre / urban cluster (excluded, D007) | 3,862 | | 5,744,974 (45%) |
| **rural model population** (rural + peri-urban) | **155,731** | 23,979 | 6,882,901 |
| of which Q1 corroborated | 27,002 | | |
| of which Q2 robust | 76,657 | | |
| of which Q3 weak (5-9 buildings or confidence < 0.70) | 52,072 | | 5% of rural buildings |
| **Q1-Q2 = extraction population** | **103,659** | | 95% of rural buildings |

Building coverage of Q1-Q2 (share of non-urban Open Buildings inside Q1-Q2 hamlets): 0.766 province-wide,
0.85-0.93 in the 25 non-Karachi districts (`outputs/tables/coverage_by_district.csv`).

## 3. Excluded areas and populations

* Karachi Central, East, Korangi and South (not enumerated by the Mouza Census, almost entirely urban) and
  the urban-class clusters everywhere (SMOD >= 22 or >= 5,000 buildings). Cities chain into single
  clusters (Karachi Central is one cluster of 1.9 M buildings) and are not villages.
* 287 hamlets outside every OCHA tehsil polygon (coast and border slivers) are kept with empty admin codes
  and take the nearest tehsil for the zone clip.
* Groups of fewer than 5 buildings (not clustered) and the 1,775 named places without a hamlet
  (`unmatched_records.csv`).

## 4. Known gaps carried into v1.0

| gap | plan item | status |
|---|---|---|
| visual QC of 90 pilot clusters | Day 14 | not done (manual) |
| review of 300 duplicate decisions | Day 19 | sample prepared, not reviewed |
| validation sample (600 + 150 units) and precision / recall | Days 21-22 | not designed or labelled; coverage tables carry empty columns |
| deh boundaries | Day 17 | proxy dehs by name-anchored Voronoi (D008); 24% of dehs geolocated |
| names | Day 16 | 19% of hamlets named (76% of buildings); no transliteration of Arabic-script names |
| atlas sheets | Day 24 | 20 sheets without satellite backdrop, not visually checked |

If the Day 22 validation later shows poor recall in some districts, those districts are labelled low
confidence and models are trained where confidence is adequate (plan fallback), as v1.1.

## 5. Zones (Day 23, D010)

See section 6 of `documentation/days23_25_zones_freeze.md` for the QC table. Core = settlement + 100 m;
resource = Voronoi cell within r_max (2 km; 4 km in Tharparkar and Umerkot) minus every core and the
OSM water / urban mask; connectivity = roads, canals and drains inside 100 m corridors to the 8 nearest
hamlets within 5 km. The resource-zone radius is a parameter to be justified on Day 44, not a claim.

## 6. What changes from the pilot (zones v0)

* Admin codes in VIDs come from OCHA p-codes, not geoBoundaries indices; the pilot wave 2 data are linked
  through `crosswalks/vid_pilot_v0.csv` (8,076 of 8,245 pilot cores contain a v1.0 hamlet at >= 80%).
* Resource zones exclude the hamlet's own core (plan text), so core and resource are disjoint; pilot v0
  resource zones included it.
* Resource zones are masked for OSM water and urban clusters; pilot v0 zones were not.
