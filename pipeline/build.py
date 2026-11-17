#!/usr/bin/env python3
"""Fetch FX closes, fit the OLS and Kalman screens, and write the static site.

Run from the repository root:

    python -m pipeline.build

Writes ``site/index.html`` (self-contained) and ``site/data.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.assets import build_commodities, build_stocks  # noqa: E402
from pipeline.fetch import fetch_panel  # noqa: E402
from pipeline.kalman import compute_kalman  # noqa: E402
from pipeline.ols import compute_ols  # noqa: E402
from pipeline.render import render_page  # noqa: E402
from pipeline.screen import assert_asset_rows, assert_screen, build_screen  # noqa: E402
from pipeline.universe import N_PAIRS, N_RETURNS, PAIRS, SAST_NAME  # noqa: E402

SITE = ROOT / "site"
CACHE = ROOT / "pipeline" / ".cache" / "closes.csv"
SAST = ZoneInfo(SAST_NAME)

SCALAR_SIG = 6
SERIES_SIG = 5


def cnum(value, sig: int = SCALAR_SIG):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int,)) and not isinstance(value, bool):
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


def cmat(matrix, sig: int = SCALAR_SIG):
    return [[cnum(value, sig) for value in row] for row in matrix]


def crow(row: dict, keys: list[str], sig: int = SCALAR_SIG) -> dict:
    out = {}
    for key in keys:
        value = row[key]
        if isinstance(value, str) or isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [cnum(item, SERIES_SIG) for item in value]
        else:
            out[key] = cnum(value, sig)
    return out


def _assert_ols(ols: dict) -> None:
    n = len(ols["beta"])
    if n != N_PAIRS:
        raise SystemExit(f"OLS matrix is {n}×{n}, expected {N_PAIRS}.")
    for i in range(n):
        if abs(ols["beta"][i][i] - 1.0) > 1e-12 or abs(ols["r2"][i][i] - 1.0) > 1e-12:
            raise SystemExit("OLS diagonal is not the identity fit.")
        for j in range(i + 1, n):
            if abs(ols["r2"][i][j] - ols["r2"][j][i]) > 1e-8:
                raise SystemExit(f"Return R² is not symmetric at {(i, j)}.")
            if abs(ols["priceR2"][i][j] - ols["priceR2"][j][i]) > 1e-8:
                raise SystemExit(f"Price R² is not symmetric at {(i, j)}.")
            if abs(ols["corr"][i][j] - ols["corr"][j][i]) > 1e-8:
                raise SystemExit(f"Return correlation is not symmetric at {(i, j)}.")


def _public_ols(ols: dict) -> dict:
    _assert_ols(ols)
    top_keys = ["i", "j", "y", "x", "r2", "corr", "betaYX", "betaXY"]
    price_keys = top_keys + ["adfP", "dw", "spurious", "cointegrated"]
    return {
        "nReturns": ols["nReturns"],
        "nPrices": ols["nPrices"],
        "nCloses": ols["nCloses"],
        "returnStart": ols["returnStart"],
        "returnEnd": ols["returnEnd"],
        "priceStart": ols["priceStart"],
        "priceEnd": ols["priceEnd"],
        "closeStart": ols["closeStart"],
        "closeEnd": ols["closeEnd"],
        "beta": cmat(ols["beta"]),
        "r2": cmat(ols["r2"]),
        "corr": cmat(ols["corr"]),
        "pvalue": cmat(ols["pvalue"]),
        "priceBeta": cmat(ols["priceBeta"]),
        "priceR2": cmat(ols["priceR2"]),
        "priceCorr": cmat(ols["priceCorr"]),
        "pricePvalue": cmat(ols["pricePvalue"]),
        "priceAdf": cmat(ols["priceAdf"]),
        "priceDw": cmat(ols["priceDw"], 4),
        "spurious": ols["spurious"],
        "spuriousRule": ols["spuriousRule"],
        "topReturns": [crow(row, top_keys) for row in ols["topReturns"]],
        "topPrices": [crow(row, price_keys) for row in ols["topPrices"]],
    }


def _public_kalman(kalman: dict) -> dict:
    if len(kalman["records"]) != 378:
        raise SystemExit(f"Expected 378 Kalman records, got {len(kalman['records'])}.")
    if kalman["windowDates"][0] != kalman["windowStart"] or kalman["windowDates"][-1] != kalman["windowEnd"]:
        raise SystemExit("Kalman window dates do not match the window bounds.")
    keep = [
        "i", "j", "y", "x", "adf", "kpss", "hl", "hurst", "z",
        "spreadMean", "spreadSd", "betaNow", "betaMin", "betaMax", "betaStd",
        "betaStdRel", "deltaB", "ve", "emIters", "degenerate", "weakHedge",
        "olsBeta", "olsR2", "olsAdf", "kStat", "kAdf", "oStat",
        "betaSeries", "betaStdSeries", "zSeries", "zAbsPercentile",
        "rollBetaLast", "rollZNow", "rollAdf", "rollKpss", "rollStat", "rollPass",
        "rollZSeries",
    ]
    counts = {}
    for key, value in kalman["counts"].items():
        counts[key] = cnum(value) if isinstance(value, float) else value
    return {
        "windowN": kalman["windowN"],
        "estN": kalman["estN"],
        "windowStart": kalman["windowStart"],
        "windowEnd": kalman["windowEnd"],
        "estStart": kalman["estStart"],
        "estEnd": kalman["estEnd"],
        "windowDates": kalman["windowDates"],
        "degenBstdRel": kalman["degenBstdRel"],
        "degenDeltaB": kalman["degenDeltaB"],
        "weakBeta": kalman["weakBeta"],
        "ownAdf": [cnum(v, 4) for v in kalman["ownAdf"]],
        "counts": counts,
        "records": [crow(row, keep) for row in kalman["records"]],
    }


def cobj(value, sig: int = SCALAR_SIG):
    if isinstance(value, str) or isinstance(value, bool) or value is None:
        return value
    if isinstance(value, dict):
        return {key: cobj(item, sig) for key, item in value.items()}
    if isinstance(value, list):
        return [cobj(item, sig) for item in value]
    return cnum(value, sig)


def _check_windows(ols: dict, kalman: dict) -> None:
    if ols["priceStart"] != kalman["windowStart"] or ols["priceEnd"] != kalman["windowEnd"]:
        raise SystemExit(
            "OLS price window "
            f"{ols['priceStart']}→{ols['priceEnd']} does not match the Kalman window "
            f"{kalman['windowStart']}→{kalman['windowEnd']}."
        )
    if ols["nReturns"] != N_RETURNS or kalman["windowN"] != N_RETURNS:
        raise SystemExit("Window length is not 250 sessions.")


def _embedded_payload(html: str) -> dict:
    marker = '<script id="payload" type="application/json">'
    start = html.find(marker)
    if start < 0:
        raise SystemExit("Rendered page has no embedded data.")
    start = html.find(">", start) + 1
    end = html.find("</script>", start)
    if end < 0:
        raise SystemExit("Embedded data script is not closed.")
    return json.loads(html[start:end])


def _assert_asset_block(embedded: dict, data: dict, key: str) -> None:
    block = data.get(key)
    if not isinstance(block, dict):
        raise SystemExit(f"The {key} tab is missing from the payload.")
    if embedded.get(key) != block:
        raise SystemExit(f"Embedded {key} payload does not match site/data.json.")
    if block.get("error"):
        if not str(block["error"]).strip():
            raise SystemExit(f"The {key} error message is empty.")
        return
    pairs = block.get("pairs") or []
    if not pairs:
        raise SystemExit(f"The {key} tab has no pairs and no error.")
    assert_asset_rows(pairs)
    if block.get("nTested") != len(pairs):
        raise SystemExit(f"{key} tested-count does not match the pair list.")
    n_opp = sum(row["status"] == "opportunity" for row in pairs)
    n_watch = sum(row["status"] == "watchlist" for row in pairs)
    if block.get("nOpportunities") != n_opp or block.get("nWatchlist") != n_watch:
        raise SystemExit(f"{key} screen counts do not match the pair statuses.")
    if key == "stocks":
        note = block.get("multipleTesting") or ""
        if "pass ADF by chance alone" not in note:
            raise SystemExit("The stocks tab is missing the multiple-testing note.")
        if not isinstance(block.get("dropped"), list):
            raise SystemExit("The stocks tab is missing the dropped-ticker list.")
        if not any(row.get("sector") and row.get("yName") for row in pairs):
            raise SystemExit("Stock pairs are missing a sector or a company name.")


def _write_site(data: dict) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    html = render_page(data)
    for needle in (
        data["generatedAtSast"],
        "OLS regression matrix",
        "Kalman hedge",
        "Research only, not trading advice",
        "How to read this",
        "Opportunities",
        "Commodities",
        "Stocks",
    ):
        if needle not in html:
            raise SystemExit(f"Rendered page is missing {needle!r}.")
    embedded = _embedded_payload(html)
    if embedded["generatedAtSast"] != data["generatedAtSast"]:
        raise SystemExit("Embedded timestamp does not match site/data.json.")
    if data.get("ols") and data.get("kalman"):
        if embedded["ols"]["beta"][0][1] != data["ols"]["beta"][0][1]:
            raise SystemExit("Embedded OLS beta does not match site/data.json.")
        if embedded["kalman"]["records"][0]["adf"] != data["kalman"]["records"][0]["adf"]:
            raise SystemExit("Embedded Kalman ADF does not match site/data.json.")
        if len(embedded["kalman"]["records"]) != 378 or len(embedded["pairs"]) != N_PAIRS:
            raise SystemExit("Embedded payload does not contain 28 pairs and 378 Kalman records.")
        screen = embedded.get("screen")
        if not screen or "opportunities" not in screen or "watchlist" not in screen:
            raise SystemExit("Embedded payload is missing the opportunity screen.")
        if screen["nOpportunities"] != len(screen["opportunities"]) or screen["nWatchlist"] != len(screen["watchlist"]):
            raise SystemExit("Screen counts do not match the embedded lists.")
        rec = embedded["kalman"]["records"][0]
        for key in ("rollZSeries", "betaStdSeries", "zSeries", "betaSeries"):
            if len(rec[key]) != 250:
                raise SystemExit(f"Embedded {key} is not 250 points.")
        if embedded["screen"] != data["screen"]:
            raise SystemExit("Embedded opportunity screen does not match site/data.json.")
    elif data.get("fxError"):
        if embedded.get("fxError") != data["fxError"]:
            raise SystemExit("Embedded FX error does not match site/data.json.")
    else:
        raise SystemExit("FX payload is missing.")
    if data.get("fxError") and embedded.get("fxError") != data["fxError"]:
        raise SystemExit("Embedded FX error does not match site/data.json.")
    _assert_asset_block(embedded, data, "commodities")
    _assert_asset_block(embedded, data, "stocks")
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    (SITE / "data.json").write_text(text + "\n", encoding="utf-8")
    if not html.endswith("\n"):
        html += "\n"
    (SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"Wrote {SITE / 'index.html'} ({len(html):,} bytes)", flush=True)
    print(f"Wrote {SITE / 'data.json'} ({len(text):,} bytes)", flush=True)


def _load_csv(path: Path) -> tuple[pd.DataFrame, str]:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame = frame[[p for p in PAIRS if p in frame.columns]]
    if list(frame.columns) != list(PAIRS):
        missing = [p for p in PAIRS if p not in frame.columns]
        raise SystemExit(f"{path} is missing pairs: {missing}")
    frame = frame.dropna(how="any")
    frame = frame[(frame > 0).all(axis=1)]
    frame = frame[frame.index.dayofweek < 5]
    need = 500 + N_RETURNS
    if len(frame) < need:
        raise SystemExit(f"{path} has {len(frame)} weekday rows; need {need}.")
    return frame.iloc[-need:], "saved closes (weekend bars already dropped)"


def _print_summary(data: dict) -> None:
    if not data.get("ols") or not data.get("kalman") or not data.get("screen"):
        print(data.get("fxError") or "FX payload is missing.", flush=True)
        for key in ("commodities", "stocks"):
            _print_asset(data.get(key) or {}, key)
        return
    ols = data["ols"]
    kalman = data["kalman"]
    counts = kalman["counts"]
    print(flush=True)
    print(f"Generated: {data['generatedAtSast']}", flush=True)
    print(f"Source:    {data['source']}", flush=True)
    print(
        f"Window:    {ols['returnStart']} → {ols['returnEnd']} "
        f"({ols['nReturns']} sessions; closes {ols['closeStart']} → {ols['closeEnd']})",
        flush=True,
    )
    print(
        f"EM sample: {kalman['estStart']} → {kalman['estEnd']} ({kalman['estN']} sessions, then frozen)",
        flush=True,
    )
    print("Top return relationships by R²:", flush=True)
    for rank, row in enumerate(ols["topReturns"][:5], 1):
        print(
            f"  {rank}. {row['y']} on {row['x']}: R²={row['r2']}  corr={row['corr']}  "
            f"β={row['betaYX']}/{row['betaXY']}",
            flush=True,
        )
    print("Top log-price relationships by R²:", flush=True)
    for rank, row in enumerate(ols["topPrices"][:5], 1):
        flag = "spurious" if row["spurious"] else ("ADF<0.05" if row["cointegrated"] else "")
        print(
            f"  {rank}. {row['y']} on {row['x']}: R²={row['r2']}  β={row['betaYX']}  "
            f"ADF p={row['adfP']}  DW={row['dw']}  {flag}",
            flush=True,
        )
    print(
        "Kalman counts: "
        f"stationary={counts['kalmanStationary']}  "
        f"ADF-only={counts['kalmanAdfOnly']}  "
        f"OLS ADF={counts['olsAdf']}  "
        f"static β={counts['degenerate']}  "
        f"median HL={counts['stationaryHlMedian']}",
        flush=True,
    )
    screen = data["screen"]
    print(
        f"Opportunities: {screen['nOpportunities']}   Watchlist: {screen['nWatchlist']}   "
        f"Eligible (stationary, half-life 3–30d): {screen['nEligible']}",
        flush=True,
    )
    for rank, row in enumerate(screen["opportunities"][:8], 1):
        print(
            f"  {rank}. {row['y']} vs {row['x']}: z={row['z']} ({row['direction']})  "
            f"β={row['betaNow']}  HL={row['hl']}  roll={'yes' if row['rollPass'] else 'no'}  "
            f"{' '.join(row['currencies'])}",
            flush=True,
        )
    if data.get("fxError"):
        print(f"FX error: {data['fxError']}", flush=True)
    for key in ("commodities", "stocks"):
        _print_asset(data.get(key) or {}, key)


def _print_asset(block: dict, key: str) -> None:
    print(flush=True)
    if block.get("error"):
        print(f"{key}: {block['error']}", flush=True)
        return
    print(
        f"{key}: tested {block.get('nTested')}   "
        f"opportunities {block.get('nOpportunities')}   "
        f"watchlist {block.get('nWatchlist')}   "
        f"prices {block.get('priceStart')} → {block.get('priceEnd')}",
        flush=True,
    )
    rows = list(block.get("pairs") or [])
    rows.sort(key=lambda row: abs(float(row["z"])) if isinstance(row.get("z"), (int, float)) else -1, reverse=True)
    shown = [row for row in rows if row["status"] in ("opportunity", "watchlist")]
    if not shown:
        print("  no opportunity or watchlist pairs", flush=True)
    preview = rows if key == "commodities" else (shown or rows[:8])
    for row in preview:
        flag = "yes" if row.get("rollingAgrees") else "no"
        print(
            f"  {row['status']}: {row.get('yName', row['y'])}/{row.get('xName', row['x'])} "
            f"({row['y']}/{row['x']}) z={row['z']}  HL={row['hl']}  "
            f"roll={flag} ({row.get('rollZNow')})  {row['why']}",
            flush=True,
        )
    if key == "stocks":
        print(f"  {block.get('multipleTesting')}", flush=True)
        print(f"  dropped tickers: {len(block.get('dropped') or [])}", flush=True)
    for note in (block.get("warnings") or [])[:8]:
        print(f"  warning: {note}", flush=True)


def _read_previous() -> dict:
    path = SITE / "data.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not read the previous snapshot: {exc}", file=sys.stderr, flush=True)
        return {}


def _empty_asset(kind: str, message: str, stamp: str) -> dict:
    return {
        "kind": kind,
        "generatedAtSast": stamp,
        "source": "unavailable",
        "error": message,
        "pairs": [],
        "dropped": [],
        "warnings": [],
        "dateSets": [],
        "nTested": 0,
        "nOpportunities": 0,
        "nWatchlist": 0,
        "lead": "",
        "multipleTesting": None,
    }


def _failed_asset(kind: str, exc: BaseException, stamp: str) -> dict:
    print(f"{kind} failed: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc()
    return _empty_asset(
        kind,
        f"{kind.capitalize()} could not be built ({exc}). The other tabs are still published.",
        stamp,
    )


def _build_fx(args, stamp: str) -> dict:
    if args.from_csv:
        frame, source = _load_csv(Path(args.from_csv))
        print(f"Loaded {frame.shape[0]} closes from {args.from_csv}", flush=True)
    else:
        frame, source = fetch_panel(PAIRS)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(CACHE, index_label="date")
        print(f"Cached closes at {CACHE}", flush=True)

    if frame.shape[1] != N_PAIRS:
        raise SystemExit(f"Refusing to continue with {frame.shape[1]} pairs.")

    ols = compute_ols(frame)
    workers = args.workers or None
    kalman = compute_kalman(frame, workers=workers)
    _check_windows(ols, kalman)
    screen = build_screen(kalman["records"])
    assert_screen(kalman["records"], screen)
    return {
        "generatedAtSast": stamp,
        "timezone": SAST_NAME,
        "source": source,
        "pairs": list(PAIRS),
        "ols": _public_ols(ols),
        "kalman": _public_kalman(kalman),
        "screen": cobj(screen),
    }


def _preserve_fx(previous: dict, message: str, stamp: str) -> dict:
    if previous.get("ols") and previous.get("kalman") and previous.get("pairs") and previous.get("screen"):
        print(message, file=sys.stderr, flush=True)
        return {
            "generatedAtSast": previous.get("generatedAtSast", stamp),
            "timezone": previous.get("timezone", SAST_NAME),
            "source": previous.get("source", ""),
            "pairs": previous["pairs"],
            "ols": previous["ols"],
            "kalman": previous["kalman"],
            "screen": previous["screen"],
            "fxError": message,
        }
    return {
        "generatedAtSast": stamp,
        "timezone": SAST_NAME,
        "source": "unavailable",
        "fxError": message,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static research dashboard")
    parser.add_argument("--workers", type=int, default=0, help="Kalman worker processes (default: up to 8)")
    parser.add_argument("--from-csv", type=str, default="", help="Aligned FX closes CSV; skips the FX fetch")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Rebuild site/index.html from the existing site/data.json",
    )
    parser.add_argument(
        "--only",
        choices=("all", "fx", "commodities", "stocks"),
        default="all",
        help="Rebuild one asset class and keep the others from the current snapshot",
    )
    args = parser.parse_args(argv)
    stamp = datetime.now(SAST).strftime("%Y-%m-%d %H:%M SAST")

    if args.render_only:
        path = SITE / "data.json"
        if not path.exists():
            raise SystemExit(f"No {path}. Run a full build first.")
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, label in (("commodities", "Commodities"), ("stocks", "Stocks")):
            data.setdefault(key, _empty_asset(key, f"{label} are not in this snapshot.", data.get("generatedAtSast", stamp)))
        _write_site(data)
        _print_summary(data)
        return 0

    previous = _read_previous()
    workers = args.workers or None
    if args.only in ("all", "fx"):
        try:
            data = _build_fx(args, stamp)
        except (Exception, SystemExit) as exc:
            traceback.print_exc()
            data = _preserve_fx(
                previous,
                f"FX could not be refreshed ({exc}). This tab is the last snapshot"
                + (f", from {previous.get('generatedAtSast')}." if previous.get("generatedAtSast") else "."),
                stamp,
            )
    else:
        if previous.get("ols") and previous.get("kalman"):
            data = {
                "generatedAtSast": previous.get("generatedAtSast", stamp),
                "timezone": previous.get("timezone", SAST_NAME),
                "source": previous.get("source", ""),
                "pairs": previous["pairs"],
                "ols": previous["ols"],
                "kalman": previous["kalman"],
                "screen": previous["screen"],
            }
            if previous.get("fxError"):
                data["fxError"] = previous["fxError"]
        else:
            data = _preserve_fx(previous, "FX has not been built in this snapshot.", stamp)

    # A partial rebuild keeps the asset classes it did not touch.
    if args.only in ("all", "commodities"):
        try:
            data["commodities"] = build_commodities(workers, stamp)
        except (Exception, SystemExit) as exc:
            data["commodities"] = _failed_asset("commodities", exc, stamp)
    else:
        data["commodities"] = previous.get("commodities") or _empty_asset(
            "commodities", "Commodities were not built in this run.", stamp
        )

    if args.only in ("all", "stocks"):
        try:
            data["stocks"] = build_stocks(workers, stamp)
        except (Exception, SystemExit) as exc:
            data["stocks"] = _failed_asset("stocks", exc, stamp)
    else:
        data["stocks"] = previous.get("stocks") or _empty_asset(
            "stocks", "Stocks were not built in this run.", stamp
        )

    _write_site(data)
    _print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
