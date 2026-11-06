"""Day 12: year-by-year history of Sindh districts and talukas, 2017-2025.

    python scripts/admin_history.py

Evidence:
  * PBS Mouza Census 2020 (Day 11 tables): talukas of the 2020 rural enumeration
  * OCHA COD-AB (valid_on 2022-09-09): 29 districts, 125 tehsils incl. 18 old Karachi towns
  * PBS Census 2023 units (data/village_inventory/admin/pbs2023_units.csv, transcribed from
    citypopulation.de, which republishes PBS Census 2023 at 2023 boundaries with 1998/2017 rebased):
    30 districts, 138 talukas / sub-divisions
  * dated change events with sources (EVENTS below)

Writes data/village_inventory/admin/{admin_events,district_history,taluka_history}.csv.
Rule: a unit exists in year Y if it exists at the 2017 baseline or was created by an event on or before
1 July of Y, and was not removed. Rural talukas outside Karachi are the same 107 in PBS 2020, OCHA 2022 and
PBS 2023 (checked below), and the last change found before the window is Kaloi (June 2016), so they are
taken as stable over 2017-2025.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "data/village_inventory/admin"
YEARS = range(2017, 2026)

EVENTS = [
    # date, unit_level, unit, event, from_unit, status, source
    ("2016-06-13", "taluka", "Kaloi", "created from parts of Diplo and Mithi talukas (Tharparkar)", "Diplo; Mithi",
     "notified", "Dawn, 14 Jun 2016, https://www.dawn.com/news/1264627"),
    ("2020-09-04", "district", "Keamari", "created from Karachi West: Baldia, Harbour (Keamari), Mauripur and SITE "
     "sub-divisions; West keeps Manghopir, Mominabad, Orangi", "Karachi West", "notified",
     "Sindh cabinet approval 20 Aug 2020 (Dawn https://www.dawn.com/news/1575499); Revenue Dept notification "
     "dated 4 Sep 2020 under s.6 Sindh Land Revenue Act 1967 (The News https://thenews.com.pk/amp/710719-sindh-"
     "govt-notifies-keamari-as-7th-district-of-karachi; ARY https://arynews.tv/en/sindh-govt-keamari-seventh-"
     "district-karachi/)"),
    ("2021-03-28", "district", "Chachro; Thari Mirwah; Shahdadpur", "new districts announced (from Tharparkar, "
     "Khairpur, Sanghar)", "Tharparkar; Khairpur; Sanghar", "proposed, no notification found",
     "24 News HD, 28 Mar 2021, https://www.24newshd.tv/28-Mar-2021/sindh-govt-to-divide-tharparkar-in-two-"
     "districts (via Wikipedia, List of districts in Sindh)"),
    ("2024-03-29", "district", "Karachi East; West; South; Central", "renaming reported (Gulshan, Orangi, Karachi, "
     "Nazimabad); boundaries unchanged", "", "reported, not verified as notified",
     "MM News, 29 Mar 2024, https://mmnews.tv/four-karachi-districts-to-be-renamed/ (via Wikipedia)"),
]

ALIAS = {  # normalised key variants -> one key (talukas)
    "GOLARCHISFRAHU": "GOLARCHI", "SHAHEEDFAZILRAHU": "GOLARCHI", "SHAHEEDFAZALRAHU": "GOLARCHI",
    "PANOAKIL": "PANOAQIL", "KASHMOR": "KASHMORE", "SEHWANSHARIF": "SEHWAN", "QAMBARALIKHAN": "KAMBARALIKHAN",
    "MEEROKHAN": "MIROKHAN", "SIJAWALJUNEJO": "SUJAWALJUNEJO", "BAQRANI": "BAKRANI", "HUSSAINBUXMUREE":
    "HUSSAINBUXMARI", "THARIMEERWAH": "MIRWAH", "DAULATPUR": "KAZIAHMED", "SHUJAABAD": "SHUJAABAD",
    "SUKKUR": "SUKKURCITY",  # OCHA labels the city taluka "Sukkur"
}
D_ALIAS = {"KAMBARSHAHDADKOT": "QAMBARSHAHDADKOT", "SHAHEEDBENAZIRABAD": "SHAHEEDBENAZIRABAD",
           "WESTKARACHI": "KARACHIWEST", "MALIRKARACHI": "MALIR", "UMERKOT": "UMERKOT"}


def key(s: str, alias: dict) -> str:
    s = re.sub(r"\b(TALUKA|TEHSIL|DISTRICT|TOWN|SUB-DIVISION)\b", "", str(s).upper())
    s = re.sub(r"[^A-Z]", "", s)
    return alias.get(s, s)


def is_karachi(d: str) -> bool:
    return bool(re.search(r"KARACHI|MALIR|KORANGI|KEAMARI|KIAMARI", str(d).upper()))


def main() -> int:
    ev = pd.DataFrame(EVENTS, columns=["date", "level", "unit", "event", "from_unit", "status", "source"])
    ev.to_csv(ADMIN / "admin_events.csv", index=False)

    u23 = pd.read_csv(ADMIN / "pbs2023_units.csv")
    d23 = u23[u23.level == "district"].name.tolist()
    t11 = pd.read_csv(ADMIN.parent / "pbs_sindh_tables/t1_1_mouzas_by_status.csv")
    import geopandas as gpd
    o3 = gpd.read_file(ADMIN / "admin_boundaries.gpkg", layer="ocha_adm3")
    d_ocha = sorted(o3.adm2_name.unique())

    # ---- districts x years
    baseline = [d for d in d23 if d != "Keamari"]          # 29 districts at the 2017 census
    created = {"Keamari": 2020}                             # notified 4 Sep 2020 -> exists from 2021-01-01
    rows = []
    for d in d23:
        for y in YEARS:
            start = created.get(d)
            exists = start is None or y > start or (y == start and False)
            note = ""
            if d == "Keamari":
                note = "notified 2020-09-04 from Karachi West; counted from 2021 (exists for <4 months of 2020)"
            if d == "Karachi West" and y <= 2020:
                note = "includes the later Keamari sub-divisions (Baldia, Harbour, Mauripur, SITE)"
            rows.append({"year": y, "district": d, "exists": exists, "in_pbs_mouza_2020":
                         key(d, D_ALIAS) in {key(x.replace(" DISTRICT", ""), D_ALIAS)
                                             for x in t11[t11.level == "district"].name},
                         "in_ocha_2022": key(d, D_ALIAS) in {key(x, D_ALIAS) for x in d_ocha},
                         "in_pbs_census_2023": True, "note": note})
    dh = pd.DataFrame(rows)
    dh.to_csv(ADMIN / "district_history.csv", index=False)

    # ---- talukas across the three sources (outside Karachi)
    a = t11[(t11.level == "taluka") & ~t11.district.map(is_karachi)]
    a = pd.DataFrame({"dk": a.district.map(lambda s: key(s, D_ALIAS)), "tk": a.name.map(lambda s: key(s, ALIAS)),
                      "pbs_mouza_2020": a.name})
    b = o3[~o3.adm2_name.map(is_karachi)]
    b = pd.DataFrame({"dk": b.adm2_name.map(lambda s: key(s, D_ALIAS)), "tk": b.adm3_name.map(lambda s: key(s, ALIAS)),
                      "ocha_2022": b.adm3_name, "ocha_pcode": b.adm3_pcode})
    c = u23[(u23.level == "taluka")]
    c = pd.DataFrame({"dk": c.parent_district.map(lambda s: key(s, D_ALIAS)), "tk": c.name.map(lambda s: key(s, ALIAS)),
                      "pbs_census_2023": c.name})
    th = a.merge(b, on=["dk", "tk"], how="outer").merge(c, on=["dk", "tk"], how="outer")
    th["in_all_three"] = th[["pbs_mouza_2020", "ocha_2022", "pbs_census_2023"]].notna().all(axis=1)
    th["valid_years"] = th.in_all_three.map({True: "2017-2025", False: "check"})
    th.loc[th.tk == "KALOI", "note"] = "created 2016-06 (before the window)"
    # Karachi: sub-divisions of the 2023 census; OCHA keeps the 18 pre-2011 towns, PBS 2020 only rural ones
    k = u23[(u23.level == "sub-division")]
    kar = pd.DataFrame({"dk": k.parent_district.map(lambda s: key(s, D_ALIAS)), "tk": k.name.map(lambda s: key(s, ALIAS)),
                        "pbs_census_2023": k.name, "valid_years": k.parent_district.map(
                            lambda d: "2021-2025" if d == "Keamari" else "2017-2025 (Karachi West part of Keamari until 2020)"
                            if d == "Karachi West" else "2017-2025"),
                        "note": "Karachi sub-division; OCHA 2022 uses the old towns, so no one-to-one tehsil"})
    th = pd.concat([th, kar], ignore_index=True).rename(columns={"dk": "district_key", "tk": "taluka_key"})
    th.to_csv(ADMIN / "taluka_history.csv", index=False)

    rural = th[th.note.isna() | (th.taluka_key == "KALOI")]
    print(f"districts: 2017 {len(baseline)}, 2025 {int(dh[(dh.year == 2025)].exists.sum())}; "
          f"OCHA 2022 {len(d_ocha)}, PBS 2023 {len(d23)}")
    print(f"talukas outside Karachi: in all three sources {int(rural.in_all_three.eq(True).sum())} of {len(rural)}")
    bad = rural[rural.in_all_three.ne(True)]
    if len(bad):
        print(bad[["district_key", "taluka_key", "pbs_mouza_2020", "ocha_2022", "pbs_census_2023"]].to_string())
    print(f"Karachi sub-divisions 2023: {len(kar)}")
    return 0 if bad.empty else 1


if __name__ == "__main__":
    sys.exit(main())
