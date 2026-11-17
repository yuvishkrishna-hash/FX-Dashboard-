"""Commodity and S&P 500 pair screens on the shared Kalman spread.

Each pair is aligned on its own common closes. The fit itself is
``pipeline.kalman.run_log_pair``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from pipeline.kalman import run_named_pairs
from pipeline.prices import fetch_closes
from pipeline.screen import annotate_asset_row, assert_asset_rows
from pipeline.sp500 import load_constituents, yahoo_symbol
from pipeline.universe import (
    COMMODITY_PAIRS,
    CORR_N,
    EST_N,
    GICS_SECTORS,
    NEED_N,
    N_RETURNS,
    TOP_PER_SECTOR,
)

WINDOW_DATES = N_RETURNS


def cnum(value, sig: int = 6):
    if isinstance(value, bool) or value is None:
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(number):
        return None
    if number == 0.0:
        return 0
    rounded = float(format(number, f".{sig}g"))
    if rounded == 0.0:
        return 0
    return rounded


def _pack(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Calendar dates as YYYYMMDD. Pandas 3 stores microseconds, so raw asi8 is not nanoseconds."""
    idx = (
        series.index.year.to_numpy(dtype=np.int64) * 10000
        + series.index.month.to_numpy(dtype=np.int64) * 100
        + series.index.day.to_numpy(dtype=np.int64)
    )
    val = series.to_numpy(dtype=float)
    order = np.argsort(idx, kind="mergesort")
    idx = idx[order]
    val = val[order]
    if idx.size > 1:
        keep = np.empty(idx.size, dtype=bool)
        keep[-1] = True
        keep[:-1] = idx[:-1] != idx[1:]
        idx = idx[keep]
        val = val[keep]
    return idx, val


def _align(left, right, need: int):
    """Last ``need`` common positive closes, or None when the overlap is shorter."""
    ia, va = left
    ib, vb = right
    common = np.intersect1d(ia, ib, assume_unique=True)
    if common.size < need:
        return None
    common = common[-need:]
    ya = va[np.searchsorted(ia, common)]
    yb = vb[np.searchsorted(ib, common)]
    ok = (ya > 0) & (yb > 0) & np.isfinite(ya) & np.isfinite(yb)
    if not ok.all():
        common, ya, yb = common[ok], ya[ok], yb[ok]
        if common.size < need:
            return None
        common, ya, yb = common[-need:], ya[-need:], yb[-need:]
    return common, ya, yb


def _window_dates(common: np.ndarray) -> list[str]:
    out = []
    for value in common[-WINDOW_DATES:]:
        n = int(value)
        out.append(f"{n // 10000:04d}-{(n // 100) % 100:02d}-{n % 100:02d}")
    return out


def _corr(ya: np.ndarray, yb: np.ndarray) -> float:
    ry = np.diff(np.log(ya))[-CORR_N:]
    rx = np.diff(np.log(yb))[-CORR_N:]
    if ry.size < CORR_N or rx.size < CORR_N:
        return float("nan")
    if not np.all(np.isfinite(ry)) or not np.all(np.isfinite(rx)):
        return float("nan")
    if float(np.std(ry)) == 0 or float(np.std(rx)) == 0:
        return float("nan")
    return float(np.corrcoef(ry, rx)[0, 1])


def _share_dates(rows: list[dict]) -> list[list[str]]:
    sets: list[list[str]] = []
    index: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = tuple(row.pop("dates"))
        slot = index.get(key)
        if slot is None:
            slot = len(sets)
            index[key] = slot
            sets.append(list(key))
        row["dateSet"] = slot
    return sets


def _block(
    *,
    kind: str,
    stamp: str,
    source: str,
    rows: list[dict],
    dropped: list[dict],
    warnings: list[str],
    lead: str,
    multiple_testing: str | None,
    extra: dict | None = None,
) -> dict:
    if not rows:
        detail = "; ".join(warnings[:6]) or "no pair had 750 common closes"
        return {
            "kind": kind,
            "generatedAtSast": stamp,
            "source": source,
            "error": f"No {kind} pairs could be tested ({detail}).",
            "pairs": [],
            "dropped": dropped,
            "warnings": warnings,
            "dateSets": [],
            "nTested": 0,
            "nOpportunities": 0,
            "nWatchlist": 0,
            "lead": lead,
            "multipleTesting": multiple_testing,
            **(extra or {}),
        }
    date_sets = _share_dates(rows)
    starts = [item[0] for item in date_sets]
    ends = [item[-1] for item in date_sets]
    opps = [r for r in rows if r["status"] == "opportunity"]
    watch = [r for r in rows if r["status"] == "watchlist"]
    block = {
        "kind": kind,
        "generatedAtSast": stamp,
        "source": source,
        "error": None,
        "pairs": rows,
        "dropped": dropped,
        "warnings": warnings,
        "dateSets": date_sets,
        "nTested": len(rows),
        "nOpportunities": len(opps),
        "nWatchlist": len(watch),
        "priceStart": min(starts),
        "priceEnd": max(ends),
        "lead": lead,
        "multipleTesting": multiple_testing,
        "estN": EST_N,
        "windowN": N_RETURNS,
    }
    if extra:
        block.update(extra)
    assert_asset_rows(rows)
    return block


def _publish(raw: dict, dates: list[str], fields: dict) -> dict:
    row = {
        "y": raw["y"],
        "x": raw["x"],
        "z": cnum(raw.get("z")),
        "hl": cnum(raw.get("hl")),
        "adf": cnum(raw.get("adf")),
        "kpss": cnum(raw.get("kpss")),
        "betaNow": cnum(raw.get("betaNow")),
        "rollZNow": cnum(raw.get("rollZNow")),
        "zSeries": [cnum(v, 4) for v in raw["zSeries"]],
        "dates": dates,
    }
    row.update(fields)
    if "corr" in row:
        row["corr"] = cnum(row["corr"], 4)
    return annotate_asset_row(row)


def _fit(prepared: list[dict], workers: int | None) -> tuple[list[dict], list[str]]:
    jobs = [(item["y"], item["x"], item["ly"], item["lx"]) for item in prepared]
    fitted = run_named_pairs(jobs, workers=workers)
    by_key = {(row["y"], row["x"]): row for row in fitted}
    published = []
    warnings = []
    for item in prepared:
        raw = by_key.get((item["y"], item["x"]))
        if raw is None or raw.get("error"):
            message = (raw or {}).get("error") or "no result"
            warnings.append(f"{item['y']}/{item['x']} failed: {message}")
            continue
        fields = {k: v for k, v in item.items() if k not in ("ly", "lx", "dates")}
        published.append(_publish(raw, item["dates"], fields))
    return published, warnings


def build_commodities(workers: int | None, stamp: str) -> dict:
    catalog = [dict(row) for row in COMMODITY_PAIRS]
    tickers = list(dict.fromkeys(t for row in catalog for t in (row["y"], row["x"])))
    series, errors, warnings, source = fetch_closes(tickers)
    prepared = []
    for row in catalog:
        missing = [t for t in (row["y"], row["x"]) if t not in series]
        if missing:
            why = ", ".join(f"{t}: {errors.get(t, 'no prices')}" for t in missing)
            warnings.append(f"{row['yName']}/{row['xName']} skipped ({why}).")
            continue
        aligned = _align(_pack(series[row["y"]]), _pack(series[row["x"]]), NEED_N)
        if aligned is None:
            warnings.append(
                f"{row['yName']}/{row['xName']} skipped (fewer than {NEED_N} common closes)."
            )
            continue
        _common, ya, yb = aligned
        prepared.append(
            {
                "id": row["id"],
                "y": row["y"],
                "x": row["x"],
                "yName": row["yName"],
                "xName": row["xName"],
                "ly": np.log(ya),
                "lx": np.log(yb),
                "dates": _window_dates(_common),
            }
        )
    rows, fit_warnings = _fit(prepared, workers)
    warnings.extend(fit_warnings)
    lead = (
        "Seven pairs. Natural gas (NG=F) is excluded because contract-roll jumps dominate the spread."
    )
    return _block(
        kind="commodities",
        stamp=stamp,
        source=source,
        rows=rows,
        dropped=[],
        warnings=warnings,
        lead=lead,
        multiple_testing=None,
        extra={"catalog": catalog},
    )


def build_stocks(workers: int | None, stamp: str) -> dict:
    constituents, list_source = load_constituents()
    records = constituents.to_dict("records")
    yahoo = [yahoo_symbol(row["Symbol"]) for row in records]
    series, errors, warnings, price_source = fetch_closes(yahoo)

    kept: dict[str, dict] = {}
    dropped: list[dict] = []
    for row in records:
        symbol = row["Symbol"]
        ticker = yahoo_symbol(symbol)
        name = row["Security"]
        sector = row["GICS Sector"]
        if ticker in errors or ticker not in series:
            dropped.append(
                {
                    "ticker": symbol,
                    "name": name,
                    "sector": sector,
                    "reason": errors.get(ticker, "Yahoo returned no prices"),
                }
            )
            continue
        closes = series[ticker]
        if len(closes) < NEED_N:
            dropped.append(
                {
                    "ticker": symbol,
                    "name": name,
                    "sector": sector,
                    "reason": f"{len(closes)} closes, need {NEED_N}",
                }
            )
            continue
        kept[symbol] = {
            "symbol": symbol,
            "yahoo": ticker,
            "name": name,
            "sector": sector,
            "packed": _pack(closes),
        }

    sectors = [s for s in GICS_SECTORS if any(item["sector"] == s for item in kept.values())]
    extra_sectors = sorted({item["sector"] for item in kept.values()} - set(sectors))
    sectors.extend(extra_sectors)

    prepared = []
    tested_by_sector: dict[str, int] = {}
    for sector in sectors:
        members = sorted((item for item in kept.values() if item["sector"] == sector), key=lambda item: item["symbol"])
        scored = []
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                y_sym, x_sym = left["symbol"], right["symbol"]
                if y_sym > x_sym:
                    y_sym, x_sym = x_sym, y_sym
                    left_pack, right_pack = right["packed"], left["packed"]
                    y_item, x_item = right, left
                else:
                    left_pack, right_pack = left["packed"], right["packed"]
                    y_item, x_item = left, right
                aligned = _align(left_pack, right_pack, NEED_N)
                if aligned is None:
                    continue
                common, ya, yb = aligned
                corr = _corr(ya, yb)
                if not math.isfinite(corr):
                    continue
                scored.append((corr, y_sym, x_sym, y_item, x_item, common, ya, yb))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        top = scored[:TOP_PER_SECTOR]
        tested_by_sector[sector] = len(top)
        print(
            f"  {sector}: {len(members)} names with history, {len(scored)} pairs ranked, testing {len(top)}",
            flush=True,
        )
        for corr, y_sym, x_sym, y_item, x_item, common, ya, yb in top:
            prepared.append(
                {
                    "id": yahoo_symbol(y_sym) + "_" + yahoo_symbol(x_sym),
                    "y": y_sym,
                    "x": x_sym,
                    "yName": y_item["name"],
                    "xName": x_item["name"],
                    "sector": sector,
                    "corr": corr,
                    "ly": np.log(ya),
                    "lx": np.log(yb),
                    "dates": _window_dates(common),
                }
            )

    rows, fit_warnings = _fit(prepared, workers)
    warnings.extend(fit_warnings)
    # A fit failure drops a selected pair. Recount from the rows that published.
    tested_by_sector = {}
    for row in rows:
        tested_by_sector[row["sector"]] = tested_by_sector.get(row["sector"], 0) + 1
    n = len(rows)
    chance = int(round(n * 0.05))
    note = f"With {n} pairs tested, roughly {chance} pass ADF by chance alone." if n else None
    dropped.sort(key=lambda item: (item["sector"], item["ticker"]))
    source = price_source + " · " + list_source
    lead = (
        f"{len(kept)} of {len(records)} constituents have {NEED_N} closes. "
        f"Within each GICS sector the top {TOP_PER_SECTOR} pairs by 504-day log-return correlation are tested."
    )
    return _block(
        kind="stocks",
        stamp=stamp,
        source=source,
        rows=rows,
        dropped=dropped,
        warnings=warnings,
        lead=lead,
        multiple_testing=note,
        extra={
            "listSource": list_source,
            "nConstituents": len(records),
            "nKept": len(kept),
            "sectors": [
                {"sector": sector, "tested": tested_by_sector.get(sector, 0)}
                for sector in sectors
            ],
            "universeNote": "Tickers use a hyphen on Yahoo where the listing symbol uses a dot (BRK.B is BRK-B).",
        },
    )
