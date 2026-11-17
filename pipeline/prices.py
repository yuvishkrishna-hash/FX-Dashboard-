"""Batched Yahoo Finance closes for commodities and equities.

One ticker that fails, or comes back short, is reported and skipped. The
FX fetch in ``pipeline.fetch`` is separate and still refuses a partial basket.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from pipeline.fetch import _close_series
from pipeline.universe import PRICE_LOOKBACK_DAYS

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "pipeline" / ".cache" / "yf"
NY = ZoneInfo("America/New_York")
ATTEMPTS = 4
BATCH = 30


def last_complete_date(now: datetime | None = None):
    """Calendar date of the last finished US daily bar.

    The bar is treated as complete after 17:15 America/New_York, which is
    after the equity close and the usual futures settlement print. Weekends
    roll back to Friday. A later holiday simply has no row to keep.
    """
    current = now or datetime.now(NY)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NY)
    else:
        current = current.astimezone(NY)
    if (current.hour, current.minute) >= (17, 15):
        day = current.date()
    else:
        day = current.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _naive_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def clean_closes(series: pd.Series, ticker: str, complete) -> pd.Series | None:
    """Positive weekday closes up to and including the last complete session."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[s > 0]
    if s.empty:
        return None
    s = pd.Series(s.to_numpy(dtype=float), index=_naive_index(s.index), name=ticker)
    s = s[s.index.dayofweek < 5]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    cutoff = pd.Timestamp(complete)
    s = s[s.index <= cutoff]
    if s.empty:
        return None
    return s


def _cache_path(ticker: str) -> Path:
    safe = urllib.parse.quote(ticker, safe="")
    return CACHE / f"{safe}.csv"


def _read_cache(ticker: str) -> tuple[pd.Series | None, str | None]:
    path = _cache_path(ticker)
    if not path.exists():
        return None, None
    try:
        frame = pd.read_csv(path, comment="#", parse_dates=["date"])
    except Exception:
        return None, None
    if frame.empty or "close" not in frame.columns:
        return None, None
    series = pd.Series(frame["close"].to_numpy(dtype=float), index=pd.DatetimeIndex(frame["date"]), name=ticker)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    complete = None
    first = path.read_text(encoding="utf-8").splitlines()[:1]
    if first and first[0].startswith("#"):
        try:
            meta = json.loads(first[0][1:])
            complete = meta.get("completeThrough")
        except json.JSONDecodeError:
            complete = None
    return series, complete


def _write_cache(ticker: str, series: pd.Series, complete) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker)
    meta = json.dumps({"ticker": ticker, "completeThrough": complete.isoformat()}, separators=(",", ":"))
    body = series.rename("close").rename_axis("date").reset_index()
    text = body.to_csv(index=False)
    path.write_text("#" + meta + "\n" + text, encoding="utf-8")


def _download_batch(tickers: list[str], start: datetime, end: datetime) -> dict[str, pd.Series]:
    raw = yf.download(
        tickers if len(tickers) > 1 else tickers[0],
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=False,
        group_by="ticker",
    )
    found = {}
    for ticker in tickers:
        series = _close_series(raw, ticker)
        if series is not None:
            found[ticker] = series
    return found


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_closes(tickers: list[str]) -> tuple[dict[str, pd.Series], dict[str, str], list[str], str]:
    """Return cleaned closes, per-ticker errors, warnings, and a source label.

    A fresh cache hit is a series stored through ``last_complete_date``.
    A download failure falls back to an older cache when one exists.
    """
    ordered = list(dict.fromkeys(tickers))
    complete = last_complete_date()
    end = datetime.now(NY)
    start = end - timedelta(days=PRICE_LOOKBACK_DAYS)
    found: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    warnings: list[str] = []
    needed: list[str] = []
    stale: dict[str, pd.Series] = {}

    for ticker in ordered:
        cached, through = _read_cache(ticker)
        if cached is not None and through == complete.isoformat() and len(cached) > 0:
            cleaned = clean_closes(cached, ticker, complete)
            if cleaned is not None:
                found[ticker] = cleaned
                continue
        if cached is not None and len(cached) > 0:
            stale[ticker] = cached
        needed.append(ticker)

    if needed:
        print(
            f"Yahoo: {len(found)} cached through {complete.isoformat()}, downloading {len(needed)}",
            flush=True,
        )
    missing = list(needed)
    delay = 3.0
    for attempt in range(1, ATTEMPTS + 1):
        if not missing:
            break
        groups = _chunks(missing, BATCH if attempt < ATTEMPTS else 1)
        print(
            f"Yahoo attempt {attempt}/{ATTEMPTS}: {len(missing)} tickers in {len(groups)} request(s)",
            flush=True,
        )
        still: list[str] = []
        for group in groups:
            try:
                got = _download_batch(group, start, end)
            except Exception as exc:
                print(f"  Yahoo request failed ({len(group)} tickers): {exc}", file=sys.stderr, flush=True)
                got = {}
            for ticker in group:
                raw = got.get(ticker)
                cleaned = clean_closes(raw, ticker, complete) if raw is not None else None
                if cleaned is None:
                    still.append(ticker)
                    continue
                found[ticker] = cleaned
                _write_cache(ticker, cleaned, complete)
            if attempt < ATTEMPTS and group is not groups[-1]:
                time.sleep(0.4)
        missing = still
        if missing and attempt < ATTEMPTS:
            print(f"  still missing {len(missing)}; retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 30)

    used_stale = False
    for ticker in missing:
        fallback = stale.get(ticker)
        cleaned = clean_closes(fallback, ticker, complete) if fallback is not None else None
        if cleaned is None:
            errors[ticker] = "Yahoo returned no prices"
            continue
        found[ticker] = cleaned
        used_stale = True
        warnings.append(f"{ticker} is cached through {cleaned.index.max().date().isoformat()}; the refresh failed.")
        print(f"  {ticker}: using cache through {cleaned.index.max().date().isoformat()}", flush=True)

    source = "Yahoo Finance"
    if used_stale:
        source = "Yahoo Finance, with cached closes where the refresh failed"
    print(f"Prices: {len(found)} series, {len(errors)} failed, complete through {complete.isoformat()}", flush=True)
    return found, errors, warnings, source
