"""Day 11: parse PBS Sindh Mouza Census 2020 tables into CSV, with internal reconciliation.

    python scripts/parse_pbs_mouza.py

The provincial report (data/raw/pbs/mouza_census_2020_sindh_report.pdf) is a text PDF. Tables are read
from word coordinates (pdfplumber): words are grouped into lines, the left block is the
administrative unit name, the numbers are assigned to columns. A row with every column present is
assigned in order; a row with gaps uses the per-page median right edge of each column, learned from
the complete rows. '-' means zero.

Outputs (data/village_inventory/pbs_sindh_tables/):
    t1_1_mouzas_by_status.csv      one row per unit (province, division, district, taluka)
    t1_2_settlements.csv           mouzas and settlements by settlements-per-mouza class
    t7_2_natural_disasters.csv     mouzas reporting each disaster type in 2016-2020
    t3_4_groundwater_taste.csv     mouzas by taste of underground water (salinity reference)
    t2_3_water_table_depth.csv     mouzas by depth of water table
    totals_reconciliation.csv      every arithmetic check, with pass/fail
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from statistics import median

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/pbs/mouza_census_2020_sindh_report.pdf"
OUT = ROOT / "data/village_inventory/pbs_sindh_tables"

NUM = re.compile(r"^(\d{1,3}(,\d{3})+|\d+|-|–)$")


def _lines(page, tol: float = 2.5) -> list[list[dict]]:
    words = sorted(page.extract_words(), key=lambda w: (w["top"], w["x0"]))
    lines, cur, top = [], [], None
    for w in words:
        if top is not None and w["top"] - top > tol:  # top of the line's first word
            lines.append(sorted(cur, key=lambda w: w["x0"]))
            cur = []
        if not cur:
            top = w["top"]
        cur.append(w)
    if cur:
        lines.append(sorted(cur, key=lambda w: w["x0"]))
    return lines


def _split_label(w: dict) -> list[dict]:
    """pdfplumber sometimes fuses a wrapped name with the NUMBER/PERCENT label ('DIVISIONNUMBER')."""
    for lab in ("NUMBER", "PERCENT"):
        t = w["text"]
        if t.endswith(lab) and t != lab:
            return [dict(w, text=t[: -len(lab)]), dict(w, text=lab)]
    return [w]


def _val(s: str) -> int:
    return 0 if s in ("-", "–") else int(s.replace(",", ""))


def parse_table(pdf, pages: range, cols: list[str], name_xmax: float, label_rows: str | None = None,
                start_col: int = 2) -> pd.DataFrame:
    """Rows of (name, *cols). label_rows='NUMBER' keeps only the NUMBER rows of NUMBER/PERCENT tables.

    start_col: the printed column number of the first data column (column 1 is the name).
    """
    n = len(cols)
    rows = []
    for pi in pages:
        page = pdf.pages[pi]
        raw = []  # (name_tokens, label, num_tokens)
        header_seen = False
        for ln in _lines(page):
            ln = [_split_label(w) for w in ln]
            ln = [w for part in ln for w in part]
            texts = [w["text"] for w in ln]
            # the column-number row "1 2 3 ... N" ends the header block
            if not header_seen:
                if texts[:3] == ["1", "2", "3"] and len(texts) >= n:
                    header_seen = True
                continue
            if texts and (texts[0].startswith("*") or texts[0].startswith("Note")):
                break  # footnotes run to the end of the page
            name_words = [t for w, t in zip(ln, texts) if w["x0"] < name_xmax]
            if any(t.startswith("*") or t == "Note" for t in name_words):
                ln = ln[:next(i for i, t in enumerate(texts) if t.startswith("*") or t == "Note")]
                texts = [w["text"] for w in ln]
            if texts and texts[0].startswith("Pakistan") or (len(texts) == 1 and texts[0].isdigit() and ln[0]["x0"] > 500):
                continue  # footer / page number
            name = [w for w in ln if w["x0"] < name_xmax and not NUM.match(w["text"])]
            nums = [w for w in ln if w["x0"] >= name_xmax and NUM.match(w["text"])]
            label = None
            if label_rows:
                lab = [w for w in ln if w["text"] in ("NUMBER", "PERCENT")]
                label = lab[0]["text"] if lab else None
                name = [w for w in name if w["text"] not in ("NUMBER", "PERCENT")]
            raw.append((name, label, nums))
        # learn column right edges from complete rows
        full = [nums for _, _, nums in raw if len(nums) == n]
        if not full:
            raise RuntimeError(f"page {pi}: no complete row to learn columns from")
        edges = [median(r[i]["x1"] for r in full) for i in range(n)]
        cur = None
        for name, label, nums in raw:
            if not nums:
                if name and cur is not None and cur["page"] == pi:
                    cur["name"] += " " + " ".join(w["text"] for w in name)
                continue
            if label_rows and label != label_rows:
                # PERCENT row: may still carry a wrapped name token
                if name and cur is not None:
                    cur["name"] += " " + " ".join(w["text"] for w in name)
                continue
            vals: list[int | None] = [None] * n
            if len(nums) == n:
                vals = [_val(w["text"]) for w in nums]
            else:
                for w in nums:
                    j = min(range(n), key=lambda k: abs(edges[k] - w["x1"]))
                    if vals[j] is not None:
                        raise RuntimeError(f"page {pi}: two values in column {cols[j]} for {name}")
                    vals[j] = _val(w["text"])
            cur = {"name": " ".join(w["text"] for w in name), "page": pi, **dict(zip(cols, vals))}
            rows.append(cur)
    df = pd.DataFrame(rows)
    df["name"] = (df["name"].str.replace(r"\s+", " ", regex=True).str.replace("SUB- DIVISION", "SUB-DIVISION")
                  .str.strip())
    return add_hierarchy(df)


def level_of(name: str) -> str:
    if name == "SINDH":
        return "province"
    if name.endswith(" DIVISION") and not name.endswith("SUB-DIVISION"):
        return "division"
    if name.endswith(" DISTRICT"):
        return "district"
    return "taluka"


def add_hierarchy(df: pd.DataFrame) -> pd.DataFrame:
    df["level"] = df["name"].map(level_of)
    div = dist = None
    divs, dists = [], []
    for name, lev in zip(df["name"], df["level"]):
        if lev == "division":
            div, dist = name, None
        elif lev == "district":
            dist = name
        divs.append(div if lev != "province" else None)
        dists.append(dist if lev in ("district", "taluka") else None)
    df["division"], df["district"] = divs, dists
    return df[["level", "division", "district", "name", *[c for c in df.columns
                                                          if c not in ("level", "division", "district", "name")]]]


def check(rec: list, table: str, unit: str, what: str, got, want) -> None:
    rec.append({"table": table, "unit": unit, "check": what, "value": got, "expected": want,
                "ok": bool(got == want)})


def reconcile_hierarchy(df: pd.DataFrame, table: str, cols: list[str], rec: list) -> None:
    """district = sum of its talukas; division = sum of districts; province = sum of divisions."""
    f = df.fillna({c: 0 for c in cols})
    for _, d in f[f.level == "district"].iterrows():
        t = f[(f.level == "taluka") & (f.district == d["name"])]
        for c in cols:
            check(rec, table, d["name"], f"{c} = sum of talukas", int(t[c].sum()), int(d[c]))
    for _, d in f[f.level == "division"].iterrows():
        t = f[(f.level == "district") & (f.division == d["name"])]
        for c in cols:
            check(rec, table, d["name"], f"{c} = sum of districts", int(t[c].sum()), int(d[c]))
    prov = f[f.level == "province"].iloc[0]
    for c in cols:
        check(rec, table, "SINDH", f"{c} = sum of divisions", int(f[f.level == "division"][c].sum()), int(prov[c]))


def find_pages(pdf, title: str, lo: int = 60, hi: int = 493) -> range:
    hits = [i for i in range(lo, min(hi, len(pdf.pages)))
            if title in ((pdf.pages[i].extract_text() or "").splitlines() or [""])[0]]
    if not hits:
        raise RuntimeError(f"no pages for {title}")
    return range(hits[0], hits[-1] + 1)


T11 = ["districts", "qanungo_circles", "patwar_circles", "mouzas_total", "rural", "urban", "partly_urban",
       "forest_populated", "forest_unpopulated", "unpopulated", "rural_populated"]
T12 = ["rural_populated_mouzas", "settlements_total", "m_1", "m_2_3", "s_2_3", "m_4_5", "s_4_5",
       "m_6_9", "s_6_9", "m_10plus", "s_10plus"]


T72 = ["rural_populated_mouzas", "any_disaster", "drought", "flood", "earthquake", "other", "none"]
T34 = ["rural_populated_mouzas", "sweet", "brackish", "avg_km_to_sweet", "km_1_10", "km_11_25", "km_26_50", "km_51plus"]
T23 = ["rural_populated_mouzas", "avg_depth_ft", "ft_0_50", "ft_51_100", "ft_101_250", "ft_251_500", "ft_501plus"]
# extra tables used later as external reference (Day 54): file, title, columns, sum check (parts, total)
EXTRA = [
    ("t7_2_natural_disasters.csv", "TABLE 7.2", T72, (["any_disaster", "none"], "rural_populated_mouzas")),
    ("t3_4_groundwater_taste.csv", "TABLE 3.4", T34, (["sweet", "brackish"], "rural_populated_mouzas")),
    ("t2_3_water_table_depth.csv", "TABLE 2.3", T23,
     (["ft_0_50", "ft_51_100", "ft_101_250", "ft_251_500", "ft_501plus"], "rural_populated_mouzas")),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rec: list = []
    with pdfplumber.open(PDF) as pdf:
        t11 = parse_table(pdf, find_pages(pdf, "TABLE 1.1 :"), T11, name_xmax=150)
        t12 = parse_table(pdf, find_pages(pdf, "TABLE 1.2 :"), T12, name_xmax=104, label_rows="NUMBER")
        extra = {fn: (parse_table(pdf, find_pages(pdf, title), cols, name_xmax=185, label_rows="NUMBER"), cols, chk,
                      title.split()[1])
                 for fn, title, cols, chk in EXTRA}
    # districts column is only filled on division/province rows; other blanks are true blanks
    t11.to_csv(OUT / "t1_1_mouzas_by_status.csv", index=False)
    t12.to_csv(OUT / "t1_2_settlements.csv", index=False)

    f = t11.fillna({c: 0 for c in T11})
    for _, r in f.iterrows():
        parts = ["rural", "urban", "partly_urban", "forest_populated", "forest_unpopulated", "unpopulated"]
        check(rec, "1.1", r["name"], "total = sum of status columns", int(sum(r[c] for c in parts)), int(r["mouzas_total"]))
        check(rec, "1.1", r["name"], "rural_populated = rural + partly_urban + forest_populated",
              int(r["rural"] + r["partly_urban"] + r["forest_populated"]), int(r["rural_populated"]))
    reconcile_hierarchy(t11, "1.1", [c for c in T11 if c != "districts"], rec)

    g = t12.fillna({c: 0 for c in T12})
    for _, r in g.iterrows():
        check(rec, "1.2", r["name"], "mouzas = sum of size classes",
              int(r.m_1 + r.m_2_3 + r.m_4_5 + r.m_6_9 + r.m_10plus), int(r.rural_populated_mouzas))
        check(rec, "1.2", r["name"], "settlements = sum of size classes",
              int(r.m_1 + r.s_2_3 + r.s_4_5 + r.s_6_9 + r.s_10plus), int(r.settlements_total))
    reconcile_hierarchy(t12, "1.2", T12, rec)
    # cross-table: rural populated mouzas agree between 1.1 and 1.2
    m = t11[["name", "rural_populated"]].merge(t12[["name", "rural_populated_mouzas"]], on="name", how="outer",
                                               indicator=True)
    for _, r in m.iterrows():
        if r["_merge"] == "left_only" and not (r.rural_populated or 0) > 0:
            continue  # urban taluka with no rural populated mouza: absent from 1.2 by design
        if r["_merge"] != "both":
            check(rec, "1.1 vs 1.2", r["name"], "unit present in both tables", r["_merge"], "both")
        else:
            check(rec, "1.1 vs 1.2", r["name"], "rural populated mouzas agree",
                  int(0 if pd.isna(r.rural_populated) else r.rural_populated), int(r.rural_populated_mouzas))

    for fn, (t, cols, (parts, total), tab) in extra.items():
        t.to_csv(OUT / fn, index=False)
        g = t.fillna({c: 0 for c in cols})
        for _, r in g.iterrows():
            check(rec, tab, r["name"], f"{total} = {' + '.join(parts)}", int(sum(r[c] for c in parts)), int(r[total]))
        reconcile_hierarchy(t, tab, [c for c in cols if not c.startswith("avg_")], rec)
        print(f"{fn}: {len(t)} rows ({(t.level == 'taluka').sum()} talukas)")

    rc = pd.DataFrame(rec)
    rc.to_csv(OUT / "totals_reconciliation.csv", index=False)
    bad = rc[~rc.ok]
    print(f"1.1: {len(t11)} rows ({(t11.level == 'taluka').sum()} talukas); "
          f"1.2: {len(t12)} rows ({(t12.level == 'taluka').sum()} talukas)")
    print(f"checks: {len(rc)}, failed: {len(bad)}")
    if len(bad):
        print(bad.to_string(max_rows=60))
    prov = t12[t12.level == "province"].iloc[0]
    print(f"Sindh: {int(prov.rural_populated_mouzas)} rural populated mouzas, {int(prov.settlements_total)} settlements")
    return 0 if bad.empty else 1


if __name__ == "__main__":
    sys.exit(main())
