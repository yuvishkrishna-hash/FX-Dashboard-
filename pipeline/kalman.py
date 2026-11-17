"""Kalman hedge-ratio screen for all 378 unordered FX pairs.

The per-pair arithmetic matches ``kalman/update_kalman.py``: EM is fit on
the 500 weekday closes before the dashboard window and then frozen, and the
tested spread is the tradeable re-hedged cumulative sum.
"""

from __future__ import annotations

import math
import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np
import pandas as pd
from scipy import stats

from pipeline import kalman_core as km
from pipeline.ols import residual_adf_p
from pipeline.universe import EST_N, N_PAIRS, N_RETURNS, PAIRS

WINDOW_N = N_RETURNS
WEAK_BETA = 0.1
DEGEN_BSTD_REL = 0.005
DEGEN_DELTA_B = 1e-9
ROLL_WIN = 120
Z_OPP = 2.0

_LOGP: np.ndarray | None = None


def kpss_p(series) -> float:
    from statsmodels.tsa.stattools import kpss

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return float(kpss(np.asarray(series, float), regression="c", nlags="auto")[1])
        except Exception:
            return float("nan")


def half_life(series) -> float:
    """AR(1) with intercept: dS_t = a + b S_{t-1}; HL = -ln2 / ln(1+b)."""
    s = np.asarray(series, float)
    ds, lag = np.diff(s), s[:-1]
    b = np.polyfit(lag, ds, 1)[0]
    if not np.isfinite(b) or b >= 0 or b <= -1:
        return float("nan")
    return float(-math.log(2) / math.log(1 + b))


def hurst(series, max_lag: int = 20) -> float:
    """Variance-of-lagged-differences Hurst: std(s_{t+k}-s_t) ~ k^H, k=2..20."""
    s = np.asarray(series, float)
    lags = np.arange(2, max_lag + 1)
    tau = np.array([np.std(s[k:] - s[:-k]) for k in lags])
    ok = tau > 0
    if ok.sum() < 3:
        return float("nan")
    return float(np.polyfit(np.log(lags[ok]), np.log(tau[ok]), 1)[0])


def rolling_ols_beta(y: np.ndarray, x: np.ndarray, start: int, win: int = ROLL_WIN) -> np.ndarray:
    """Slope of ln Y on ln X over the `win` closes that end the day before each index.

    The hedge used on the return into day t is fit on y[t-win:t], x[t-win:t].
    It does not use day t, matching the Kalman spread's no-look-ahead hedge.
    """
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    n = len(y)
    if start < win:
        raise ValueError(f"Need {win} closes before index {start}.")
    cy = np.cumsum(y)
    cx = np.cumsum(x)
    cxy = np.cumsum(y * x)
    cxx = np.cumsum(x * x)
    t = np.arange(start, n)
    right = t - 1
    left = t - win - 1
    sy = cy[right] - cy[left]
    sx = cx[right] - cx[left]
    sxy = cxy[right] - cxy[left]
    sxx = cxx[right] - cxx[left]
    den = win * sxx - sx * sx
    den = np.where(np.abs(den) < 1e-18, np.nan, den)
    return (win * sxy - sx * sy) / den


def compute_pair(i: int, j: int, ly: np.ndarray, lx: np.ndarray) -> dict:
    ly = np.asarray(ly, float)
    lx = np.asarray(lx, float)
    n = len(ly)
    w0 = n - WINDOW_N
    params = km.shumway_stoffer_em(ly[:w0], lx[:w0])
    fwd = km.kalman_forward(ly, lx, params)
    b_pred = fwd["b_pred"][w0:]
    b_filt = fwd["b_filt"][w0:]
    yw, xw = ly[w0:], lx[w0:]
    level = yw - b_pred * xw
    dly = np.diff(ly)[w0 - 1 :]
    dlx = np.diff(lx)[w0 - 1 :]
    spread_inc = dly - b_pred * dlx
    spread = np.cumsum(spread_inc)
    innov = fwd["innov"][w0:]
    b_std = fwd["b_std"][w0:]
    mu, sd = float(spread.mean()), float(spread.std(ddof=1))
    z = (spread - mu) / sd if sd > 0 else np.zeros_like(spread)
    abs_z = np.abs(z)
    z_pct = float(np.mean(abs_z <= abs_z[-1]) * 100.0)
    roll_b = rolling_ols_beta(ly, lx, w0, ROLL_WIN)
    roll_spread = np.cumsum(dly - roll_b * dlx)
    r_mu, r_sd = float(roll_spread.mean()), float(roll_spread.std(ddof=1))
    roll_z = (roll_spread - r_mu) / r_sd if r_sd > 0 else np.zeros_like(roll_spread)
    roll_adf = residual_adf_p(roll_spread)
    roll_kpss = kpss_p(roll_spread)
    roll_stat = bool(roll_adf < 0.05 and roll_kpss > 0.05)
    roll_z_now = float(roll_z[-1])
    roll_pass = bool(roll_stat and abs(roll_z_now) >= Z_OPP)
    res = stats.linregress(xw, yw)
    ols_resid = yw - res.intercept - res.slope * xw
    bstd = float(np.std(b_filt, ddof=1))
    bmean = float(np.mean(b_filt))
    delta_b = float(params["delta_b"])
    degenerate = bool(
        (abs(bmean) > 0 and bstd / abs(bmean) < DEGEN_BSTD_REL) or delta_b < DEGEN_DELTA_B
    )
    return {
        "i": i,
        "j": j,
        "y": PAIRS[i],
        "x": PAIRS[j],
        "adf": residual_adf_p(spread),
        "kpss": kpss_p(spread),
        "hl": half_life(spread),
        "hurst": hurst(spread),
        "z": float(z[-1]),
        "spreadMean": mu,
        "spreadSd": sd,
        "betaNow": float(b_filt[-1]),
        "betaMin": float(b_filt.min()),
        "betaMax": float(b_filt.max()),
        "betaStd": bstd,
        "betaMean": bmean,
        "betaStdRel": bstd / abs(bmean) if bmean else float("nan"),
        "deltaB": delta_b,
        "ve": float(params["ve"]),
        "emIters": int(params["iters"]),
        "degenerate": degenerate,
        "weakHedge": bool(max(abs(float(b_filt.min())), abs(float(b_filt.max()))) < WEAK_BETA),
        "innovAdf": residual_adf_p(innov),
        "innovHl": half_life(innov),
        "lvlAdf": residual_adf_p(level),
        "lvlHl": half_life(level),
        "olsBeta": float(res.slope),
        "olsR2": float(res.rvalue ** 2),
        "olsAdf": residual_adf_p(ols_resid),
        "betaSeries": b_filt.tolist(),
        "betaStdSeries": b_std.tolist(),
        "zSeries": z.tolist(),
        "zAbsPercentile": z_pct,
        "spreadInc": spread_inc.tolist(),
        "rollBetaLast": float(roll_b[-1]),
        "rollZNow": roll_z_now,
        "rollAdf": roll_adf,
        "rollKpss": roll_kpss,
        "rollStat": roll_stat,
        "rollPass": roll_pass,
        "rollZSeries": roll_z.tolist(),
    }


def level_rolling_z(ly: np.ndarray, lx: np.ndarray, win: int = ROLL_WIN) -> float:
    """OLS log-price residual at the last close.

    The line is fit on ``[t−win, t)`` and applied at ``t``. The residual is
    divided by that fit's sample residual standard deviation (ddof=1).
    """
    ly = np.asarray(ly, float)
    lx = np.asarray(lx, float)
    t = len(ly) - 1
    if t < win:
        return float("nan")
    fit = km.ols_fit(ly[t - win : t], lx[t - win : t])
    sd = fit["sd"]
    if not np.isfinite(sd) or sd <= 0:
        return float("nan")
    return float((ly[t] - fit["a"] - fit["b"] * lx[t]) / sd)


def run_log_pair(ly: np.ndarray, lx: np.ndarray, y_name: str, x_name: str) -> dict:
    """One pair through the same Kalman spread as the FX screen.

    ``rollZNow`` is then replaced with the 120-day level residual z. The FX
    page keeps the cumulative rolling-spread z that ``compute_pair`` stores.
    """
    ly = np.asarray(ly, float)
    lx = np.asarray(lx, float)
    row = compute_pair(0, 1, ly, lx)
    row["y"] = y_name
    row["x"] = x_name
    row["rollZNow"] = level_rolling_z(ly, lx)
    return row


def _run_named_job(job: tuple) -> dict:
    y_name, x_name, ly, lx = job
    try:
        return run_log_pair(ly, lx, y_name, x_name)
    except Exception as exc:
        return {"y": y_name, "x": x_name, "error": f"{type(exc).__name__}: {exc}"}


def run_named_pairs(jobs: list[tuple], workers: int | None = None) -> list[dict]:
    """Fit the listed ``(y_name, x_name, ly, lx)`` jobs. One failure does not stop the rest."""
    if not jobs:
        return []
    if workers is None:
        workers = min(8, os.cpu_count() or 1)
    workers = max(1, int(workers))
    # Spawning a pool costs more than a handful of fits.
    if workers <= 1 or len(jobs) < 12:
        print(f"Kalman on {len(jobs)} pairs, single process…", flush=True)
        rows = []
        for k, job in enumerate(jobs, 1):
            rows.append(_run_named_job(job))
            if k == len(jobs) or k % 20 == 0:
                print(f"  Kalman {k}/{len(jobs)}", flush=True)
        return rows
    print(f"Kalman on {len(jobs)} pairs with {workers} worker(s)…", flush=True)
    ctx = get_context("spawn")
    rows = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        for k, row in enumerate(pool.map(_run_named_job, jobs, chunksize=2), 1):
            rows.append(row)
            if k == len(jobs) or k % 20 == 0:
                print(f"  Kalman {k}/{len(jobs)}", flush=True)
    return rows


def _init_worker(logp: np.ndarray) -> None:
    global _LOGP
    _LOGP = np.asarray(logp, float)


def _worker(ij: tuple[int, int]) -> dict:
    if _LOGP is None:
        raise RuntimeError("Kalman worker started without price data.")
    i, j = ij
    try:
        return compute_pair(i, j, _LOGP[:, i], _LOGP[:, j])
    except Exception as exc:
        raise RuntimeError(f"Kalman failed for {PAIRS[i]}/{PAIRS[j]}: {exc}") from exc


def _run_pairs(logp: np.ndarray, workers: int) -> list[dict]:
    jobs = [(i, j) for i in range(N_PAIRS) for j in range(i + 1, N_PAIRS)]
    if len(jobs) != N_PAIRS * (N_PAIRS - 1) // 2:
        raise RuntimeError("Pair grid is not the 378-pair upper triangle.")
    if workers <= 1:
        _init_worker(logp)
        results = []
        for k, job in enumerate(jobs, 1):
            results.append(_worker(job))
            if k % 40 == 0 or k == len(jobs):
                print(f"  Kalman {k}/{len(jobs)}", flush=True)
        return results
    ctx = get_context("spawn")
    results = []
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=ctx,
        initializer=_init_worker,
        initargs=(logp,),
    ) as pool:
        for k, row in enumerate(pool.map(_worker, jobs, chunksize=4), 1):
            results.append(row)
            if k % 40 == 0 or k == len(jobs):
                print(f"  Kalman {k}/{len(jobs)}", flush=True)
    return results


def _check_rolling_beta(logp: np.ndarray, row: dict) -> None:
    """The last rolling hedge must match a direct 120-day linregress, excluding today."""
    ly = logp[:, row["i"]]
    lx = logp[:, row["j"]]
    res = stats.linregress(lx[-ROLL_WIN - 1 : -1], ly[-ROLL_WIN - 1 : -1])
    if not np.isfinite(row["rollBetaLast"]) or abs(float(res.slope) - row["rollBetaLast"]) > 1e-8:
        raise SystemExit(
            f"Rolling OLS beta for {row['y']}/{row['x']} is {row['rollBetaLast']}, "
            f"linregress slope is {float(res.slope)}."
        )


def compute_kalman(frame: pd.DataFrame, workers: int | None = None) -> dict:
    if frame.shape[1] != N_PAIRS:
        raise SystemExit(f"Kalman expected {N_PAIRS} columns, got {frame.shape[1]}.")
    need = WINDOW_N + EST_N
    if len(frame) < need:
        raise SystemExit(f"Kalman needs {need} weekday closes; got {len(frame)}.")
    closes = frame.iloc[-need:]
    logp = np.log(closes.to_numpy(dtype=float))
    dates = [d.strftime("%Y-%m-%d") for d in closes.index]
    if workers is None:
        workers = min(8, os.cpu_count() or 1)
    workers = max(1, int(workers))
    print(f"Kalman EM on {N_PAIRS * (N_PAIRS - 1) // 2} pairs with {workers} worker(s)…", flush=True)
    results = _run_pairs(logp, workers)
    results.sort(key=lambda r: (r["i"], r["j"]))
    if len(results) != 378:
        raise SystemExit(f"Expected 378 Kalman pairs, got {len(results)}.")
    _check_rolling_beta(logp, results[0])

    for row in results:
        row["kStat"] = bool(row["adf"] < 0.05 and row["kpss"] > 0.05)
        row["kAdf"] = bool(row["adf"] < 0.05)
        row["oStat"] = bool(row["olsAdf"] < 0.05)

    def _finite(key, pred):
        return [r[key] for r in results if pred(r) and np.isfinite(r[key])]

    innov_hl = _finite("innovHl", lambda r: True)
    level_hl = _finite("lvlHl", lambda r: True)
    stat_hl = _finite("hl", lambda r: r["kStat"])
    counts = {
        "nPairs": len(results),
        "kalmanStationary": sum(r["kStat"] for r in results),
        "kalmanAdfOnly": sum(r["kAdf"] for r in results),
        "olsAdf": sum(r["oStat"] for r in results),
        "olsAdfR2": sum(r["oStat"] and r["olsR2"] >= 0.5 for r in results),
        "bothStat": sum(r["kStat"] and r["oStat"] for r in results),
        "kalmanOnlyStat": sum(r["kStat"] and not r["oStat"] for r in results),
        "olsOnlyStat": sum(r["oStat"] and not r["kStat"] for r in results),
        "bothAdf": sum(r["kAdf"] and r["oStat"] for r in results),
        "kalmanOnlyAdf": sum(r["kAdf"] and not r["oStat"] for r in results),
        "olsOnlyAdf": sum(r["oStat"] and not r["kAdf"] for r in results),
        "degenerate": sum(r["degenerate"] for r in results),
        "degenerateStationary": sum(r["degenerate"] and r["kStat"] for r in results),
        "weakHedgeStationary": sum(r["weakHedge"] and r["kStat"] for r in results),
        "innovAdf": sum(r["innovAdf"] < 0.05 for r in results),
        "levelAdf": sum(r["lvlAdf"] < 0.05 for r in results),
        "innovHlMedian": float(np.median(innov_hl)) if innov_hl else None,
        "levelHlMedian": float(np.median(level_hl)) if level_hl else None,
        "deltaBMedian": float(np.median([r["deltaB"] for r in results])),
        "stationaryHlMedian": float(np.median(stat_hl)) if stat_hl else None,
    }
    own_adf = [residual_adf_p(logp[-WINDOW_N:, k]) for k in range(N_PAIRS)]
    wdates = dates[-WINDOW_N:]
    return {
        "windowN": WINDOW_N,
        "estN": EST_N,
        "windowStart": wdates[0],
        "windowEnd": wdates[-1],
        "estStart": dates[0],
        "estEnd": dates[-WINDOW_N - 1],
        "windowDates": wdates,
        "degenBstdRel": DEGEN_BSTD_REL,
        "degenDeltaB": DEGEN_DELTA_B,
        "weakBeta": WEAK_BETA,
        "ownAdf": own_adf,
        "counts": counts,
        "records": results,
    }
