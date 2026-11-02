"""Convert wide zonal CSV exports into the long Parquet schema of Day 26.

Input columns: vid, zone, chunk, <var>_<YYYYMM>_<stat> (monthly / seasonal) or <var>_<stat>
(static). Output columns:
    vid, zone, product, band, date_start, date_end, available_at, stat, value, n_valid
available_at = window end (+ product lag); n_valid = the matching *_count column if present.

    python scripts/gee_to_long.py data/satellite/s2/raw/*.csv --product s2_zonal \
        --out data/satellite/s2/s2_zonal_v1.parquet
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

PAT = re.compile(r"^(?P<band>.+?)_(?P<ym>\d{6})_(?P<stat>mean|count|median|sum|min|max|stdDev)$")
STATIC = re.compile(r"^(?P<band>.+?)_(?P<stat>mean|count|median|sum|min|max|stdDev)$")
SEASONAL = {"landsat_season_zonal": 6}          # window length in months
LAG_DAYS = {"chirps_zonal": 0, "era5_zonal": 0}  # extra publication lag if needed (sensitivity)


def to_long(df: pd.DataFrame, product: str) -> pd.DataFrame:
    id_cols = [c for c in ("vid", "zone") if c in df.columns]
    val_cols = [c for c in df.columns if c not in ("vid", "zone", "chunk", "system:index", ".geo")]
    m = df.melt(id_vars=id_cols, value_vars=val_cols, var_name="col", value_name="value")
    parsed = m["col"].str.extract(PAT)
    static = parsed["band"].isna()
    st = m.loc[static, "col"].str.extract(STATIC)
    parsed.loc[static, ["band", "stat"]] = st[["band", "stat"]].values
    m = pd.concat([m.drop(columns="col"), parsed], axis=1)
    months = SEASONAL.get(product, 1)
    start = pd.to_datetime(m["ym"], format="%Y%m", errors="coerce")
    m["date_start"] = start
    m["date_end"] = start + pd.DateOffset(months=months) - pd.Timedelta(days=1)
    m["available_at"] = m["date_end"] + pd.Timedelta(days=LAG_DAYS.get(product, 0))
    m["product"] = product
    counts = m[m.stat == "count"][id_cols + ["band", "ym", "value"]].rename(columns={"value": "n_valid"})
    out = m[m.stat != "count"].merge(counts, on=id_cols + ["band", "ym"], how="left")
    return out[id_cols + ["product", "band", "date_start", "date_end", "available_at", "stat", "value", "n_valid"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--product", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    frames = [to_long(pd.read_csv(p), args.product) for p in args.inputs]
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    dups = out.duplicated(["vid", "zone", "band", "date_start", "stat"]).sum()
    if dups:
        print(f"WARNING: {dups} duplicate keys (re-run chunks?)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"{args.out}: {len(out):,} rows, {out.vid.nunique():,} villages, bands {sorted(out.band.unique())[:12]}...")


if __name__ == "__main__":
    main()
