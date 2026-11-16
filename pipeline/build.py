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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.fetch import fetch_panel  # noqa: E402
from pipeline.kalman import compute_kalman  # noqa: E402
from pipeline.ols import compute_ols  # noqa: E402
from pipeline.render import render_page  # noqa: E402
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
        "betaSeries", "zSeries",
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


def _write_site(data: dict) -> None:
    SITE.mkdir(parents=True, exist_ok=True)
    html = render_page(data)
    for needle in (
        data["generatedAtSast"],
        "OLS regression matrix",
        "Kalman hedge",
        "Research only",
    ):
        if needle not in html:
            raise SystemExit(f"Rendered page is missing {needle!r}.")
    embedded = _embedded_payload(html)
    if embedded["generatedAtSast"] != data["generatedAtSast"]:
        raise SystemExit("Embedded timestamp does not match site/data.json.")
    if embedded["ols"]["beta"][0][1] != data["ols"]["beta"][0][1]:
        raise SystemExit("Embedded OLS beta does not match site/data.json.")
    if embedded["kalman"]["records"][0]["adf"] != data["kalman"]["records"][0]["adf"]:
        raise SystemExit("Embedded Kalman ADF does not match site/data.json.")
    if len(embedded["kalman"]["records"]) != 378 or len(embedded["pairs"]) != N_PAIRS:
        raise SystemExit("Embedded payload does not contain 28 pairs and 378 Kalman records.")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static FX research dashboard")
    parser.add_argument("--workers", type=int, default=0, help="Kalman worker processes (default: up to 8)")
    parser.add_argument("--from-csv", type=str, default="", help="Aligned closes CSV; skips the fetch")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Rebuild site/index.html from the existing site/data.json",
    )
    args = parser.parse_args(argv)

    if args.render_only:
        path = SITE / "data.json"
        if not path.exists():
            raise SystemExit(f"No {path}. Run a full build first.")
        data = json.loads(path.read_text(encoding="utf-8"))
        _write_site(data)
        _print_summary(data)
        return 0

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

    stamp = datetime.now(SAST).strftime("%Y-%m-%d %H:%M SAST")
    data = {
        "generatedAtSast": stamp,
        "timezone": SAST_NAME,
        "source": source,
        "pairs": list(PAIRS),
        "ols": _public_ols(ols),
        "kalman": _public_kalman(kalman),
    }
    _write_site(data)
    _print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
