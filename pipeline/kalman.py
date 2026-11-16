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
    spread = np.cumsum(dly - b_pred * dlx)
    innov = fwd["innov"][w0:]
    mu, sd = float(spread.mean()), float(spread.std(ddof=1))
    z = (spread - mu) / sd if sd > 0 else np.zeros_like(spread)
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
        "zSeries": z.tolist(),
    }


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
