"""Research screen on the Kalman tradeable spread.

A pair is eligible when the Kalman spread passes ADF and KPSS, and its
half-life is between 3 and 30 trading days. Opportunities also have
|z| >= 2. The watchlist is the same stationarity and half-life screen
with 1.5 <= |z| < 2. Nothing here is a trade instruction.
"""

from __future__ import annotations

import math

import numpy as np

from pipeline.universe import PAIRS

ADF_MAX = 0.05
KPSS_MIN = 0.05
HL_MIN = 3.0
HL_MAX = 30.0
Z_OPP = 2.0
Z_WATCH = 1.5
DUP_CORR = 0.8
ROLL_WIN = 120
STALE_DAYS = 3
# Shown as "Rolling agrees": same sign as the Kalman z, and stretched.
ROLL_AGREE_ABS = 1.5


def currencies_of(pair: str) -> tuple[str, str]:
    return pair[:3], pair[3:]


def exposure(y: str, x: str) -> list[str]:
    return sorted(set(currencies_of(y) + currencies_of(x)))


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def eligible(row: dict) -> bool:
    hl = row.get("hl")
    return bool(row.get("kStat")) and _finite(hl) and HL_MIN <= float(hl) <= HL_MAX


def rolling_agrees(row: dict) -> bool:
    """120-day rolling OLS z matches the Kalman sign and |z| is at least 1.5."""
    z = row.get("z")
    rz = row.get("rollZNow")
    if not _finite(z) or not _finite(rz):
        return False
    zf, rzf = float(z), float(rz)
    if zf == 0 or rzf == 0:
        return False
    return (zf > 0) == (rzf > 0) and abs(rzf) >= ROLL_AGREE_ABS


def direction(z: float) -> str:
    if z > 0:
        return "rich"
    if z < 0:
        return "cheap"
    return "flat"


def _similar(opps: list[dict]) -> dict[tuple[int, int], list[dict]]:
    out = {(r["i"], r["j"]): [] for r in opps}
    incs = [np.asarray(r["spreadInc"], float) for r in opps]
    for a in range(len(opps)):
        for b in range(a + 1, len(opps)):
            left, right = incs[a], incs[b]
            if left.shape != right.shape or left.size < 3:
                continue
            if float(np.std(left)) == 0 or float(np.std(right)) == 0:
                continue
            corr = float(np.corrcoef(left, right)[0, 1])
            if not math.isfinite(corr) or corr <= DUP_CORR:
                continue
            ra, rb = opps[a], opps[b]
            out[(ra["i"], ra["j"])].append({"y": rb["y"], "x": rb["x"], "corr": corr})
            out[(rb["i"], rb["j"])].append({"y": ra["y"], "x": ra["x"], "corr": corr})
    for key in out:
        out[key].sort(key=lambda item: item["corr"], reverse=True)
    return out


def _currency_groups(opps: list[dict]) -> list[dict]:
    groups: dict[str, list[str]] = {}
    for row in opps:
        label = row["y"] + "/" + row["x"]
        for ccy in exposure(row["y"], row["x"]):
            groups.setdefault(ccy, []).append(label)
    n = len(opps)
    ranked = [
        {"currency": ccy, "count": len(pairs), "n": n, "pairs": pairs}
        for ccy, pairs in groups.items()
    ]
    ranked.sort(key=lambda item: (-item["count"], item["currency"]))
    return ranked


def _public_row(row: dict, similar: list[dict]) -> dict:
    return {
        "i": row["i"],
        "j": row["j"],
        "y": row["y"],
        "x": row["x"],
        "betaNow": row["betaNow"],
        "z": row["z"],
        "direction": direction(float(row["z"])),
        "hl": row["hl"],
        "adf": row["adf"],
        "kpss": row["kpss"],
        "hurst": row["hurst"],
        "rollPass": bool(row["rollPass"]),
        "rollingAgrees": rolling_agrees(row),
        "rollStat": bool(row["rollStat"]),
        "rollZNow": row["rollZNow"],
        "rollAdf": row["rollAdf"],
        "rollKpss": row["rollKpss"],
        "zAbsPercentile": row["zAbsPercentile"],
        "currencies": exposure(row["y"], row["x"]),
        "similar": similar,
    }


def build_screen(records: list[dict]) -> dict:
    if len(records) != 378:
        raise SystemExit(f"Screen expected 378 Kalman pairs, got {len(records)}.")
    base = [row for row in records if eligible(row)]
    opps = [row for row in base if abs(float(row["z"])) >= Z_OPP]
    watch = [row for row in base if Z_WATCH <= abs(float(row["z"])) < Z_OPP]
    opps.sort(key=lambda row: abs(float(row["z"])), reverse=True)
    watch.sort(key=lambda row: abs(float(row["z"])), reverse=True)
    similar = _similar(opps)
    return {
        "rules": {
            "adfMax": ADF_MAX,
            "kpssMin": KPSS_MIN,
            "halfLifeMin": HL_MIN,
            "halfLifeMax": HL_MAX,
            "zOpportunity": Z_OPP,
            "zWatchMin": Z_WATCH,
            "duplicateCorr": DUP_CORR,
            "rollWindow": ROLL_WIN,
            "rollingAgreesAbs": ROLL_AGREE_ABS,
            "rollingAgreesRule": "same sign as the Kalman z and |rolling OLS z| >= 1.5",
            "staleDays": STALE_DAYS,
        },
        "opportunities": [
            _public_row(row, similar[(row["i"], row["j"])]) for row in opps
        ],
        "watchlist": [_public_row(row, []) for row in watch],
        "currencies": _currency_groups(opps),
        "nOpportunities": len(opps),
        "nWatchlist": len(watch),
        "nEligible": len(base),
    }


def assert_screen(records: list[dict], screen: dict) -> None:
    """The published lists must be exactly the filter, in |z| order."""
    again = build_screen(records)
    if [ (r["y"], r["x"]) for r in again["opportunities"] ] != [ (r["y"], r["x"]) for r in screen["opportunities"] ]:
        raise SystemExit("Opportunity list does not match the ADF, KPSS, half-life, and |z| filters.")
    if [ (r["y"], r["x"]) for r in again["watchlist"] ] != [ (r["y"], r["x"]) for r in screen["watchlist"] ]:
        raise SystemExit("Watchlist does not match the stationarity, half-life, and z-score band.")
    opp_keys = {(r["y"], r["x"]) for r in screen["opportunities"]}
    watch_keys = {(r["y"], r["x"]) for r in screen["watchlist"]}
    if opp_keys & watch_keys:
        raise SystemExit("A pair is in both the opportunity list and the watchlist.")
    zs = [abs(float(r["z"])) for r in screen["opportunities"]]
    if zs != sorted(zs, reverse=True):
        raise SystemExit("Opportunities are not sorted by |z| descending.")
    for row in screen["opportunities"]:
        if row["direction"] not in ("rich", "cheap"):
            raise SystemExit(f"{row['y']}/{row['x']} has no rich/cheap direction.")
        if not (HL_MIN <= float(row["hl"]) <= HL_MAX):
            raise SystemExit(f"{row['y']}/{row['x']} half-life is outside 3–30 days.")
        if abs(float(row["z"])) < Z_OPP:
            raise SystemExit(f"{row['y']}/{row['x']} |z| is below 2.")
        if bool(row["rollingAgrees"]) != rolling_agrees(row):
            raise SystemExit(f"Rolling-agrees flag is wrong for {row['y']}/{row['x']}.")
    for row in screen["watchlist"]:
        if bool(row["rollingAgrees"]) != rolling_agrees(row):
            raise SystemExit(f"Rolling-agrees flag is wrong for {row['y']}/{row['x']}.")
        for other in row["similar"]:
            if float(other["corr"]) <= DUP_CORR:
                raise SystemExit(f"Similar-pair correlation is not above {DUP_CORR}.")
        if set(row["currencies"]) != set(exposure(row["y"], row["x"])):
            raise SystemExit(f"Currency tag for {row['y']}/{row['x']} is wrong.")
    counts = {item["currency"]: item["count"] for item in screen["currencies"]}
    expected: dict[str, int] = {}
    for row in screen["opportunities"]:
        for ccy in row["currencies"]:
            expected[ccy] = expected.get(ccy, 0) + 1
    if counts != expected:
        raise SystemExit("Currency concentration counts do not match the opportunity list.")
    known = set(PAIRS)
    for row in records:
        for key in ("rollZSeries", "betaStdSeries", "zSeries", "betaSeries"):
            if len(row[key]) != 250:
                raise SystemExit(f"{row['y']}/{row['x']} {key} is not 250 points.")
        if row["y"] not in known or row["x"] not in known:
            raise SystemExit("A record names a pair outside the 28-pair basket.")
