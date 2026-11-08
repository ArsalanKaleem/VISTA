# Days 19-20: duplicates, unmatched records and quality classes (registry v0.6)

Run after `build_registry.py`. Both scripts update `village_registry.parquet` in place, so rerun all three
in this order:

```
python scripts/build_registry.py      # v0.5: VIDs and crosswalks
python scripts/dedupe_inventory.py    # Day 19 -> v0.6: name_status, village_name
python scripts/quality_classes.py     # Day 20: quality_class
python -m pytest tests/test_registry.py
```

## Day 19: duplicates

**Matching distance from data.** We have 2,149 verified pairs: a hamlet named by an OSM point inside it,
plus a GeoNames point with the same name in the same tehsil. Measured on them, GeoNames position error
is 0 m at the median (the point lies inside the hamlet), 4 m at p90 and 502 m at p95
(`outputs/tables/day19_geonames_position_error.csv`). So the duplicate distance is D = 600 m, and the
500 m GeoNames matching radius of Day 16 is confirmed.

| check | result | resolution |
|---|---|---|
| D1 duplicated detections: building pairs < 1 m apart | 1,290 of 13.0 M buildings (0.01%) | Negligible. Counts inflated by at most 1,290 buildings, and no change to cluster membership. Hamlets are disjoint by construction |
| D2 several name records of one place on one hamlet | 2,269 hamlets | R1: merged into one name entity |
| D3 same name on hamlets of one village tier | 309 names | R2: becomes the village name (631 hamlets, `village_shared`) |
| D3 same name, different villages, < 600 m apart | 32 | R3: one place named twice. The name stays on the best-supported hamlet (OSM inside > GeoNames inside > near, then size) and is dropped from the other |
| D3 same name, different villages, > 600 m apart | 574 names (1,231 hamlets) | R4: homonyms such as Mirpur or Kotri, all kept and told apart by VID |

All 3,184 decisions are in `registry/merge_log.csv`.

`registry/review_sample.csv` holds 300 decisions for manual review, with a blank `reviewer_verdict` column:
all 32 R3, 80 R2, 80 R4 and 108 R1. **This review is not done.** It needs a person looking at the imagery,
and if it finds errors the 600 m rule should be revised.

Village-tier names: 39.5% of the 24,077 village-tier units have a name (that of their largest named hamlet).

## Day 20: records without coordinates

`registry/unmatched_records.csv` lists them; nothing is forced into a match.

| record | count | explanation |
|---|---|---|
| named place, 1-4 buildings within the radius | 799 | real settlement below the 5-building minimum |
| named place, no building within the radius | 976 | misplaced point, abandoned site, or building missed by Open Buildings |
| BoR deh with no hamlet name match | 4,564 | no geolocation, so it stays a name only (D008) |
| BoR deh in a taluka not on the OCHA spine (Karachi) | 102 | out of the rural scope |

## Day 20: quality classes (D009)

| class | rule | all hamlets | rural hamlets |
|---|---|---|---|
| Q1 corroborated | >= 10 buildings and a name from OSM / GeoNames | 28,410 | 27,002 |
| Q2 robust | >= 10 buildings, mean confidence >= 0.70 | 78,219 | 76,657 |
| Q3 weak | 5-9 buildings or mean confidence < 0.70 | 52,964 | 52,072 |

**Why these cuts.** The share of hamlets an independent source confirms (`day20_quality_thresholds.csv`)
is:

- by size: 3.4% at 5-6 buildings, 4.5% at 7-9, 6.2% at 10-14, 21% at 25-49 and 76% at 100+;
- by confidence: 3.4% below 0.70, against 6.5-24% above it.

So both cuts sit where confirmation starts to rise.

Rural Q1-Q2 = 103,659 hamlets, holding 95.0% of rural buildings. By district (`registry/quality_summary.csv`):

- the rural Q3 share is 30-40% of hamlets;
- Q3 hamlets hold only about 4-7% of rural buildings;
- the urban-excluded share ranges from under 1% to 100% (the Karachi districts).

The plan's later checks ("zones for every Q1-Q2 village", "no NaN for Q1-Q2") refer to these classes.
