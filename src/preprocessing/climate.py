"""Village climate series from cell series and area weights (Days 35-36, D003).

    from src.preprocessing.climate import ClimateStore
    cs = ClimateStore()                       # data/climate/zonal_local
    p = cs.series("chirps", "precip", ["SD0100...|resource", ...])   # DataFrame keys x YYYYMM (mm)
    spi3 = cs.index("spi", 3, keys)           # DataFrame keys x YYYYMM (area-weighted SPI-3)

Weighted means of standardised indices are area-weighted combinations of cell values; for a zone inside one
cell (the common case) they equal the cell value.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / "data/climate/zonal_local"


class ClimateStore:
    def __init__(self, store: Path = STORE):
        self.store = store
        self._w: dict[str, pd.DataFrame] = {}
        self._cells: dict[str, pd.DataFrame] = {}

    def weights(self, product: str) -> pd.DataFrame:
        if product not in self._w:
            self._w[product] = pd.read_parquet(self.store / f"weights_{product}.parquet")
        return self._w[product]

    def cells(self, product: str) -> pd.DataFrame:
        if product not in self._cells:
            self._cells[product] = pd.read_parquet(self.store / f"cells_{product}.parquet")
        return self._cells[product]

    def _combine(self, product: str, table: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        """table: cell_id + month columns. Returns keys x months, area-weighted, NaN-aware."""
        w = self.weights(product)
        w = w[w.key.isin(keys)]
        months = [c for c in table.columns if c not in ("cell_id", "var", "scale")]
        cell_pos = pd.Series(np.arange(len(table)), index=table.cell_id.values)
        w = w[w.cell_id.isin(cell_pos.index)]
        key_pos = pd.Series(np.arange(len(keys)), index=keys)
        rows, cols = key_pos.loc[w.key.values].values, cell_pos.loc[w.cell_id.values].values
        W = sparse.csr_matrix((w.w.values, (rows, cols)), shape=(len(keys), len(table)))
        V = table[months].values.astype("float64")
        ok = ~np.isnan(V)
        num = W @ np.where(ok, V, 0.0)
        den = W @ ok.astype("float64")
        with np.errstate(invalid="ignore", divide="ignore"):
            out = num / den
        out[den == 0] = np.nan
        return pd.DataFrame(out, index=keys, columns=months)

    def series(self, product: str, var: str, keys: list[str]) -> pd.DataFrame:
        t = self.cells(product)
        return self._combine(product, t[t["var"] == var].drop(columns="var"), keys)

    def index(self, name: str, scale: int, keys: list[str]) -> pd.DataFrame:
        product = "chirps" if name == "spi" else "era5"
        t = pd.read_parquet(self.store / f"{name}_cells.parquet")
        return self._combine(product, t[t.scale == scale].drop(columns="scale"), keys)
