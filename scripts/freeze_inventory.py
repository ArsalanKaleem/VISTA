"""Day 25: freeze the village inventory as v1.0 (immutable; later changes go to v1.1 with a change log).

    python scripts/freeze_inventory.py

Copies registry v0.6 and zones v1 into data/village_inventory/village_inventory_v1.0/, writes a GeoPackage of
the registry (one layer) and of the zones (three layers), a sha256 manifest, and CHANGELOG.md. Refuses to
overwrite an existing v1.0.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
DST = VI / "village_inventory_v1.0"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    if DST.exists():
        raise SystemExit(f"{DST} exists: v1.0 is frozen. Make v1.1 instead.")
    (DST / "crosswalks").mkdir(parents=True)
    reg = gpd.read_parquet(VI / "registry/village_registry.parquet")
    reg["registry_version"] = "v1.0"
    reg.to_parquet(DST / "village_registry_v1.0.parquet")
    reg.to_file(DST / "village_inventory_v1.0.gpkg", layer="registry", driver="GPKG")
    for z in ("core", "resource", "connectivity"):
        g = gpd.read_parquet(VI / f"zones/v1/zones_{z}.parquet")
        g.to_parquet(DST / f"zones_{z}.parquet")
        g.to_file(DST / "village_inventory_v1.0.gpkg", layer=f"zones_{z}", driver="GPKG")
    for f in ("village_graph_knn8.parquet", "zones_upload_q12.parquet", "zone_qc.csv"):
        shutil.copy(VI / "zones/v1" / f, DST / f)
    for f in (VI / "registry/crosswalks").glob("*.csv"):
        shutil.copy(f, DST / "crosswalks" / f.name)
    for f in ("merge_log.csv", "review_sample.csv", "unmatched_records.csv", "quality_summary.csv", "registry_summary.csv"):
        shutil.copy(VI / "registry" / f, DST / f)
    rows = [{"file": str(p.relative_to(DST)), "sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted(DST.rglob("*")) if p.is_file()]
    pd.DataFrame(rows).to_csv(DST / "MANIFEST.sha256.csv", index=False)
    r = reg[reg.in_rural_population]
    (DST / "CHANGELOG.md").write_text(f"""# Village inventory v1.0 ({date.today().isoformat()})

Frozen on Day 25 from registry v0.6 and zones v1. Immutable: corrections create v1.1 with an entry here.

* N hamlets = {len(reg):,}; rural population {len(r):,} (Q1 {int((r.quality_class == 'Q1').sum()):,},
  Q2 {int((r.quality_class == 'Q2').sum()):,}, Q3 {int((r.quality_class == 'Q3').sum()):,}); village-tier units {reg.vvid.nunique():,}
* Decisions D005-D011; data dictionary in documentation/data_dictionary.md; coverage in documentation/coverage_report.md
* Known gaps carried into v1.0: Day 19 review sample not reviewed; Day 21-22 validation sample not labelled;
  proxy dehs, not surveyed deh boundaries (D008)
""", encoding="utf-8")
    print(f"frozen {len(rows)} files, {sum(x['bytes'] for x in rows) / 2**20:.0f} MB -> {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
