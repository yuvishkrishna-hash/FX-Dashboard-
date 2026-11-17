"""Current S&P 500 constituents and GICS sectors.

Wikipedia is the source. ``pipeline/data/sp500.csv`` is the committed
fallback used when that page cannot be fetched or parsed.
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import pandas as pd

from pipeline.universe import GICS_SECTORS

CSV_PATH = Path(__file__).resolve().parent / "data" / "sp500.csv"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
COLUMNS = ["Symbol", "Security", "GICS Sector"]
_SYMBOL = r"^[A-Z][A-Z0-9.\-]*$"


def yahoo_symbol(symbol: str) -> str:
    """Yahoo uses a hyphen where the listing symbol uses a dot (BRK.B → BRK-B)."""
    return symbol.replace(".", "-")


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    cols = {str(c).strip(): c for c in frame.columns}
    renamed = frame.rename(columns={raw: name for name, raw in cols.items()})
    if "GICS Sector" not in renamed.columns and "Sector" in renamed.columns:
        renamed = renamed.rename(columns={"Sector": "GICS Sector"})
    missing = [c for c in COLUMNS if c not in renamed.columns]
    if missing:
        raise ValueError(f"Constituent table is missing {missing}.")
    out = renamed.loc[:, COLUMNS].copy()
    for col in COLUMNS:
        out[col] = out[col].astype(str).str.strip()
    out = out[out["Symbol"].str.match(_SYMBOL, na=False)]
    out = out.drop_duplicates(subset="Symbol", keep="first")
    out = out[(out["Security"] != "") & (out["GICS Sector"] != "")]
    return out.reset_index(drop=True)


def _usable(frame: pd.DataFrame) -> bool:
    if len(frame) < 400:
        return False
    if frame["GICS Sector"].nunique() < 8:
        return False
    return True


def _from_wikipedia() -> pd.DataFrame:
    req = urllib.request.Request(
        WIKI_URL,
        headers={"User-Agent": "fx-research-dashboard/1.0 (research; educational)"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        html = resp.read()
    tables = pd.read_html(io.BytesIO(html))
    if not tables:
        raise ValueError("Wikipedia returned no tables.")
    frame = _normalize(tables[0])
    if not _usable(frame):
        raise ValueError(f"Wikipedia table has {len(frame)} usable rows.")
    return frame


def _from_csv() -> pd.DataFrame:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"No constituent fallback at {CSV_PATH}.")
    frame = _normalize(pd.read_csv(CSV_PATH))
    if not _usable(frame):
        raise ValueError(f"Committed constituent CSV has {len(frame)} usable rows.")
    return frame


def load_constituents() -> tuple[pd.DataFrame, str]:
    """Return Symbol, Security, GICS Sector, and a short source label."""
    try:
        frame = _from_wikipedia()
        source = "Wikipedia: List of S&P 500 companies"
    except Exception as exc:
        print(f"Wikipedia constituent fetch failed ({exc}). Using the committed CSV.", flush=True)
        frame = _from_csv()
        source = "Committed S&P 500 CSV (Wikipedia was unavailable)"
    known = [s for s in GICS_SECTORS if s in set(frame["GICS Sector"])]
    extra = sorted(set(frame["GICS Sector"]) - set(GICS_SECTORS))
    print(
        f"Constituents: {len(frame)} names, {frame['GICS Sector'].nunique()} sectors, source: {source}",
        flush=True,
    )
    if extra:
        print(f"  sectors not in the standard 11: {extra}", flush=True)
    missing = [s for s in GICS_SECTORS if s not in known]
    if missing:
        print(f"  standard sectors with no names: {missing}", flush=True)
    return frame, source
