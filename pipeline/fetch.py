"""Fetch daily FX closes for the 28-pair universe.

Yahoo Finance is tried first, with retries, because a single download is
often incomplete. Stooq fills any pair Yahoo still cannot supply. The build
stops if the aligned weekday panel is short of 28 pairs.
"""

from __future__ import annotations

import socket
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from pipeline.universe import EST_N, LOOKBACK_DAYS, N_RETURNS, PAIRS

YAHOO_ATTEMPTS = 4
STOOQ_ATTEMPTS = 2
STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}&i=d"
MIN_ROWS = EST_N + N_RETURNS  # 500 estimation days + 250 in the window
socket.setdefaulttimeout(60)


def yahoo_ticker(pair: str) -> str:
    return f"{pair}=X"


def _naive_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _clean_series(series: pd.Series, pair: str) -> pd.Series | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[s > 0]
    if s.empty:
        return None
    s = pd.Series(s.to_numpy(dtype=float), index=_naive_index(s.index), name=pair)
    s = s[s.index.dayofweek < 5]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if len(s) < MIN_ROWS:
        return None
    return s


def _close_series(raw: pd.DataFrame, ticker: str) -> pd.Series | None:
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = raw.columns.get_level_values(0)
        level1 = raw.columns.get_level_values(1)
        if ticker in level0:
            sub = raw[ticker]
            if isinstance(sub, pd.DataFrame) and "Close" in sub.columns:
                return sub["Close"]
            if isinstance(sub, pd.Series):
                return sub
        if "Close" in set(level0) and ticker in set(level1):
            sub = raw["Close"]
            if isinstance(sub, pd.DataFrame) and ticker in sub.columns:
                return sub[ticker]
            if isinstance(sub, pd.Series):
                return sub
        return None
    if "Close" in raw.columns:
        return raw["Close"]
    return None


def _download_yahoo(pairs: list[str], start: datetime, end: datetime) -> dict[str, pd.Series]:
    tickers = [yahoo_ticker(p) for p in pairs]
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
    for pair, ticker in zip(pairs, tickers):
        series = _close_series(raw, ticker)
        if series is None:
            continue
        cleaned = _clean_series(series, pair)
        if cleaned is not None:
            found[pair] = cleaned
    return found


def _fetch_yahoo_with_retries(pairs: list[str], start: datetime, end: datetime) -> dict[str, pd.Series]:
    found: dict[str, pd.Series] = {}
    missing = list(pairs)
    delay = 3.0
    for attempt in range(1, YAHOO_ATTEMPTS + 1):
        if not missing:
            break
        if attempt == 1:
            groups = [list(missing)]
        elif attempt == 2:
            groups = [list(missing)]
        elif attempt == 3:
            groups = _chunks(missing, 7)
        else:
            groups = [[p] for p in missing]
        print(
            f"Yahoo attempt {attempt}/{YAHOO_ATTEMPTS}: {len(missing)} pairs in {len(groups)} request(s)",
            flush=True,
        )
        still = []
        try:
            for group in groups:
                try:
                    got = _download_yahoo(group, start, end)
                except Exception as exc:
                    print(f"  Yahoo request failed for {group}: {exc}", file=sys.stderr, flush=True)
                    got = {}
                for pair in group:
                    if pair in got:
                        found[pair] = got[pair]
                        print(
                            f"  {pair}: {len(got[pair])} weekday closes "
                            f"{got[pair].index.min().date()} → {got[pair].index.max().date()}",
                            flush=True,
                        )
                    else:
                        still.append(pair)
        except Exception as exc:
            print(f"  Yahoo attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
            still = [p for p in missing if p not in found]
        missing = still
        if missing and attempt < YAHOO_ATTEMPTS:
            print(f"  still missing: {missing}; retrying in {delay:.0f}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return found


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_stooq_pair(pair: str, start: datetime) -> pd.Series | None:
    url = STOOQ_URL.format(ticker=pair.lower())
    req = urllib.request.Request(url, headers={"User-Agent": "fx-research-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        frame = pd.read_csv(resp)
    if frame is None or frame.empty:
        return None
    cols = {c.lower(): c for c in frame.columns}
    if "date" not in cols or "close" not in cols:
        print(f"  Stooq unexpected columns for {pair}: {list(frame.columns)}", file=sys.stderr)
        return None
    dates = pd.to_datetime(frame[cols["date"]], errors="coerce")
    close = pd.to_numeric(frame[cols["close"]], errors="coerce")
    series = pd.Series(close.to_numpy(), index=dates, name=pair)
    series = series[series.index.notna()]
    series = series[series.index >= (start - timedelta(days=30))]
    return _clean_series(series, pair)


def _fetch_stooq(pairs: list[str], start: datetime) -> dict[str, pd.Series]:
    found = {}
    for pair in pairs:
        series = None
        for attempt in range(1, STOOQ_ATTEMPTS + 1):
            try:
                series = _fetch_stooq_pair(pair, start)
            except Exception as exc:
                print(f"  Stooq failed for {pair} (attempt {attempt}): {exc}", file=sys.stderr, flush=True)
                series = None
            if series is not None:
                break
            time.sleep(2)
        if series is None:
            print(f"  Stooq has no usable history for {pair}", file=sys.stderr, flush=True)
        else:
            found[pair] = series
            print(
                f"  Stooq {pair}: {len(series)} weekday closes "
                f"{series.index.min().date()} → {series.index.max().date()}",
                flush=True,
            )
    return found


def align_panel(found: dict[str, pd.Series]) -> pd.DataFrame:
    present = [p for p in PAIRS if p in found]
    if not present:
        raise SystemExit("No FX pairs were fetched.")
    panel = pd.concat([found[p] for p in present], axis=1).sort_index()
    panel = panel[panel.index.dayofweek < 5]
    panel = panel.dropna(how="any")
    panel = panel[(panel > 0).all(axis=1)]
    panel = panel[~panel.index.duplicated(keep="last")].sort_index()
    return panel


def fetch_panel(pairs: list[str] | None = None) -> tuple[pd.DataFrame, str]:
    """Return the aligned weekday panel and a source label.

    Raises SystemExit if fewer than 28 pairs survive, or if the common
    history is shorter than the 750 sessions the Kalman sample needs.
    """
    pairs = list(pairs or PAIRS)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    print(
        f"Fetching {len(pairs)} pairs from {start.date()} to {end.date()} (UTC)",
        flush=True,
    )
    found = _fetch_yahoo_with_retries(pairs, start, end)
    missing = [p for p in pairs if p not in found]
    source = "Yahoo Finance"
    if missing:
        print(f"Yahoo still missing {missing}. Trying Stooq.", flush=True)
        stooq = _fetch_stooq(missing, start)
        found.update(stooq)
        if stooq:
            source = "Yahoo Finance, with Stooq fallback for some pairs"
    missing = [p for p in pairs if p not in found]
    if missing or len(found) < len(PAIRS):
        raise SystemExit(
            f"Only {len(found)} of {len(PAIRS)} pairs fetched. Missing: {missing or 'unknown'}. "
            "Refusing to build a partial dashboard."
        )
    panel = align_panel(found)
    if list(panel.columns) != list(PAIRS):
        raise SystemExit(f"Aligned panel columns are {list(panel.columns)}, expected the 28-pair universe.")
    if len(panel) < MIN_ROWS:
        raise SystemExit(
            f"Only {len(panel)} common weekday closes after alignment; need {MIN_ROWS} "
            f"({EST_N} estimation sessions + {N_RETURNS} in the window)."
        )
    panel = panel.iloc[-MIN_ROWS:]
    print(
        f"Aligned {len(panel)} weekday closes, {panel.index[0].date()} → {panel.index[-1].date()}",
        flush=True,
    )
    return panel, source
