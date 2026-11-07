"""Day 17: official list of dehs (Board of Revenue Sindh) -> CSV, joined to the OCHA tehsil spine.

    python scripts/parse_deh_list.py

Input  data/raw/bor/listofdeh.pdf (sindhzameen.gos.pk, 142 pages, sha256 in data/raw/manifest.csv)
Output data/village_inventory/deh/bor_dehs.csv          one row per deh: district, taluka, seq, deh, keys, pcode
       data/village_inventory/deh/deh_counts_by_taluka.csv  BoR dehs vs PBS 2020 mouzas per OCHA tehsil
Checks S.No runs 1..N without gaps or repeats, and the per-taluka sequence restarts at 1 for each taluka.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from admin_history import ALIAS, D_ALIAS, key  # noqa: E402

PDF = ROOT / "data/raw/bor/listofdeh.pdf"
OUT = ROOT / "data/village_inventory/deh"

# BoR spellings -> keys used by admin_history (district keys, then taluka keys)
BOR_D = {"KAMBERSHAHDADKOT": "QAMBARSHAHDADKOT", "KARACHIMALIR": "MALIR", "KARACHIKORANGI": "KORANGI", "KARACHIWEST": "KARACHIWEST",
         "KARACHIEAST": "KARACHIEAST", "KARACHISOUTH": "KARACHISOUTH", "KARACHICENTRAL": "KARACHICENTRAL",
         "KARACHIKEAMARI": "KEAMARI", "KEMARI": "KEAMARI", "KAMBARSHAHDADKOT": "QAMBARSHAHDADKOT",
         "QAMBARSHAHDADKOT": "QAMBARSHAHDADKOT", "SHAHEEDBENAZIRABAD": "SHAHEEDBENAZIRABAD",
         "NAWABSHAH": "SHAHEEDBENAZIRABAD", "BENAZIRABAD": "SHAHEEDBENAZIRABAD", "MIRPURKHAS": "MIRPURKHAS",
         "TANDOMUHAMMADKHAN": "TANDOMUHAMMADKHAN", "TMKHAN": "TANDOMUHAMMADKHAN", "NAUSHAHROFEROZE":
         "NAUSHAHROFEROZE", "NFEROZE": "NAUSHAHROFEROZE", "UMERKOT": "UMERKOT", "UMARKOT": "UMERKOT"}


BOR_T = {"KGMB": "KOTGHULAMMUHAMMAD", "TGHHYDER": "TANDOGHULAMHYDER", "TMKHAN": "TANDOMUHAMMADKHAN",
         "SFRAHU": "GOLARCHI", "KAMBER": "KAMBARALIKHAN", "SHAHDADOT": "SHAHDADKOT", "CITYSUKKUR": "SUKKURCITY",
         "QAZIAHMED": "KAZIAHMED"}


def match_taluka(df: pd.DataFrame, th: pd.DataFrame) -> pd.Series:
    """Exact key, then abbreviation table, then closest key within the same district (difflib >= 0.75)."""
    import difflib
    known = th.groupby("district_key").taluka_key.apply(list).to_dict()
    out = []
    for dk, tk in zip(df.district_key, df.taluka_key):
        cands = known.get(dk, [])
        tk = BOR_T.get(tk, tk)
        if tk not in cands:
            close = difflib.get_close_matches(tk, cands, n=1, cutoff=0.75)
            tk = close[0] if close else tk
        out.append(tk)
    return pd.Series(out, index=df.index)


def parse() -> pd.DataFrame:
    rows = []
    with pdfplumber.open(PDF) as pdf:
        for pi, page in enumerate(pdf.pages):
            for tbl in page.extract_tables():
                for r in tbl:
                    if not r or not r[0] or not str(r[0]).strip().isdigit():
                        continue  # header row
                    r = [(c or "").replace("\n", " ").strip() for c in r]
                    rows.append({"sno": int(r[0]), "district": r[1], "taluka": r[2],
                                 "seq": int(r[3]) if r[3].isdigit() else None, "deh": r[4], "page": pi + 1})
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    df = parse()
    problems = []
    if not (df.sno.diff().dropna() == 1).all():
        gaps = df[df.sno.diff() != 1].sno.tolist()[1:]
        problems.append(f"S.No not consecutive at {gaps[:10]}")
    starts = df[df.seq == 1]
    changes = df[(df.district != df.district.shift()) | (df.taluka != df.taluka.shift())]
    if len(starts) != len(changes):
        problems.append(f"{len(changes)} taluka blocks but {len(starts)} sequences start at 1")
    df["district_key"] = df.district.map(lambda s: key(s, D_ALIAS)).map(lambda k: BOR_D.get(k, k))
    df["taluka_key"] = df.taluka.map(lambda s: key(s, ALIAS))
    df["deh_key"] = df.deh.str.upper().str.replace(r"[^A-Z]", "", regex=True)
    df["under_sea"] = df.deh.str.contains("under sea", case=False)

    th = pd.read_csv(ROOT / "data/village_inventory/admin/taluka_history.csv")
    th = th.dropna(subset=["ocha_pcode"])[["district_key", "taluka_key", "ocha_pcode", "pbs_mouza_2020"]]
    df["taluka_key_raw"] = df.taluka_key
    df["taluka_key"] = match_taluka(df, th)
    df = df.merge(th, on=["district_key", "taluka_key"], how="left")
    df.to_csv(OUT / "bor_dehs.csv", index=False)

    cnt = df.groupby(["district", "taluka", "district_key", "taluka_key"], dropna=False).agg(
        bor_dehs=("deh", "size"), under_sea=("under_sea", "sum"), ocha_pcode=("ocha_pcode", "first")).reset_index()
    t11 = pd.read_csv(ROOT / "data/village_inventory/pbs_sindh_tables/t1_1_mouzas_by_status.csv")
    t11 = t11[t11.level == "taluka"][["name", "mouzas_total", "rural_populated"]].rename(columns={"name": "pbs_mouza_2020"})
    cw = th.merge(t11, on="pbs_mouza_2020", how="left")[["ocha_pcode", "mouzas_total", "rural_populated"]]
    cnt = cnt.merge(cw, on="ocha_pcode", how="left")
    cnt["bor_minus_pbs"] = cnt.bor_dehs - cnt.mouzas_total
    cnt.to_csv(OUT / "deh_counts_by_taluka.csv", index=False)

    print(f"{len(df):,} dehs in {df.district.nunique()} districts / {cnt.shape[0]} talukas; pages {df.page.max()}")
    print("problems:", problems or "none")
    m = cnt.ocha_pcode.notna()
    print(f"talukas matched to OCHA: {int(m.sum())} of {len(cnt)} ({int(cnt[m].bor_dehs.sum()):,} dehs)")
    print(cnt[~m][["district", "taluka", "bor_dehs"]].to_string())
    both = cnt[m & cnt.mouzas_total.notna()]
    print(f"BoR vs PBS total mouzas on {len(both)} talukas: BoR {int(both.bor_dehs.sum())}, PBS {int(both.mouzas_total.sum())}; "
          f"exact equal {int((both.bor_minus_pbs == 0).sum())}, |diff|<=2 {int((both.bor_minus_pbs.abs() <= 2).sum())}")
    print(both.reindex(both.bor_minus_pbs.abs().sort_values(ascending=False).index)
          [["district", "taluka", "bor_dehs", "mouzas_total", "bor_minus_pbs"]].head(10).to_string())
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
