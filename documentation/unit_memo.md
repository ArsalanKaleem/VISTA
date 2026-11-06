# Unit memo: mouza / deh, settlement and VISTA village (Day 11)

Source: PBS, *Mouza Census 2020, Sindh Provincial Report* (data/raw/pbs/mouza_census_2020_sindh_report.pdf),
tables parsed by `scripts/parse_pbs_mouza.py` into `data/village_inventory/pbs_sindh_tables/`.
All 2,456 arithmetic checks pass (`totals_reconciliation.csv`): every status total equals the sum of its
columns, every district equals the sum of its talukas, every division equals the sum of its districts,
Sindh equals the sum of its divisions, and Table 1.1 and Table 1.2 agree on rural populated mouzas for
every unit.

## PBS units

| unit | PBS definition (paraphrased) | Sindh 2020 |
|---|---|---|
| Mouza / deh | Demarcated revenue estate with its own revenue record and cadastral map. It may hold one or more settlements, or none (*bechiragh*) | 5,976 mouzas, of which 5,428 are rural populated (rural + partly urban + populated forest) |
| Settlement | Population settlement within a mouza's boundary, counted per mouza | 30,065 in the rural populated mouzas (5.5 per mouza) |
| Taluka | Revenue sub-division (tehsil). Karachi uses sub-divisions | 114 talukas in Table 1.1. Table 1.2 has 110 because 4 urban talukas have no rural mouza |

Coverage gap: Karachi East, Central, South and Korangi were not enumerated because they are urbanised.
Karachi West and Malir appear with 66 rural populated mouzas.

## How VISTA uses them

1. **VISTA village = settlement cluster**, not mouza. The inventory unit is a contiguous cluster of
   building footprints (Days 14-15), which is the physical unit that floods, dries out or recovers. It
   carries a persistent `vid` and no administrative meaning.
2. **Deh / mouza = aggregation and reference unit.** Each cluster is assigned to one deh where deh polygons
   exist (Day 17), otherwise to its taluka. PBS figures are only ever compared at taluka level or above,
   because no deh-level geometry is published with the census.
3. **Counts are not expected to match one-to-one.** The PBS settlement count is a revenue-record notion:
   a named *goth* with its hamlets usually counts as one settlement. Building clusters split hamlets that
   are more than about 80 m apart (40 m dilation on both sides). Provisional pilot clusters versus PBS:

   | pilot taluka (OCHA tehsil) | PBS rural populated mouzas | PBS settlements | clusters, 40 m and >= 5 buildings | ratio |
   |---|---|---|---|---|
   | Mithi (Thar desert) | 26 | 161 | 898 | 5.6 |
   | Sanghar (canal plain) | 65 | 411 | 5,215 | 12.7 |
   | Shah Bunder (delta) | 72 | 336 | 1,261 | 3.8 |

   (The geoBoundaries Mithi polygon used for the GEE pilot is about twice the OCHA tehsil, because it still
   includes the newer Islamkot and Kaloi talukas, so its 1,999 clusters are not comparable with PBS.)

   The ratio is expected, not an error. Day 14 (documentation/day14_settlement_clustering.md) adopts the
   two-tier definition: hamlets (40 m) are the inventory unit, and a village tier (hamlets merged at 150 m)
   is used for comparisons with PBS.
4. **PBS reference variables for later validation (Day 54), never model inputs:** Table 7.2 (mouzas
   reporting drought / flood / other disasters in the last five years), Table 3.4 (sweet vs brackish
   groundwater, a salinity reference) and Table 2.3 (water-table depth classes). These are 2016-2020
   reports, inside the training window, and are used only as taluka-level comparisons.

## Not available

* Record-level (per-mouza) data: not published. A request to PBS Agricultural Census Wing is drafted in
  `documentation/data_request_letters/pbs_mouza_records.md` (not sent; it needs the author's signature).
* Deh boundaries: not in the PBS release. Candidate sources are listed for Day 17.
