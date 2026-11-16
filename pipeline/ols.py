"""28x28 OLS on daily log returns and on log prices.

The regressions, residual ADF, Durbin–Watson, and the spurious-fit rule
are the same calculations as the original ``update.py``.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.stattools import durbin_watson
from statsmodels.tsa.stattools import adfuller

from pipeline.universe import N_RETURNS

ADF_REGRESSION = "c"
SPURIOUS_R2 = 0.5
SPURIOUS_ADF_P = 0.05


def residual_adf_p(resid: np.ndarray) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            series = np.asarray(resid, float)
            maxlag = int(12 * (len(series) / 100) ** 0.25)
            res = adfuller(series, maxlag=maxlag, autolag="AIC", regression=ADF_REGRESSION)
            p = float(res[1])
            if math.isnan(p) or math.isinf(p):
                return 1.0
            return p
        except Exception:
            return 1.0


def ols_return_matrices(log_ret: pd.DataFrame) -> dict[str, list[list[float]]]:
    cols = list(log_ret.columns)
    n = len(cols)
    x = log_ret.to_numpy(dtype=float)
    beta = [[0.0] * n for _ in range(n)]
    r2 = [[0.0] * n for _ in range(n)]
    corr_m = [[0.0] * n for _ in range(n)]
    pvalue = [[0.0] * n for _ in range(n)]
    cmat = np.corrcoef(x, rowvar=False)
    for i in range(n):
        yv = x[:, i]
        for j in range(n):
            xv = x[:, j]
            if i == j:
                beta[i][j] = 1.0
                r2[i][j] = 1.0
                corr_m[i][j] = 1.0
                pvalue[i][j] = 0.0
                continue
            res = stats.linregress(xv, yv)
            r = float(res.rvalue)
            beta[i][j] = float(res.slope)
            r2[i][j] = float(r * r)
            corr_m[i][j] = float(cmat[i, j])
            pvalue[i][j] = float(res.pvalue)
    return {"beta": beta, "r2": r2, "corr": corr_m, "pvalue": pvalue}


def ols_price_matrices(prices: pd.DataFrame) -> dict[str, list[list[float]]]:
    """OLS on log prices: ln(y) = a + b ln(x). Residual is the log spread."""
    n = prices.shape[1]
    raw = prices.to_numpy(dtype=float)
    x = np.log(raw)
    beta = [[0.0] * n for _ in range(n)]
    r2 = [[0.0] * n for _ in range(n)]
    corr_m = [[0.0] * n for _ in range(n)]
    pvalue = [[0.0] * n for _ in range(n)]
    adf_p = [[0.0] * n for _ in range(n)]
    dw = [[0.0] * n for _ in range(n)]
    cmat = np.corrcoef(x, rowvar=False)
    for i in range(n):
        yv = x[:, i]
        for j in range(n):
            xv = x[:, j]
            if i == j:
                beta[i][j] = 1.0
                r2[i][j] = 1.0
                corr_m[i][j] = 1.0
                pvalue[i][j] = 0.0
                adf_p[i][j] = 0.0
                dw[i][j] = 2.0
                continue
            res = stats.linregress(xv, yv)
            r = float(res.rvalue)
            beta[i][j] = float(res.slope)
            r2[i][j] = float(r * r)
            corr_m[i][j] = float(cmat[i, j])
            pvalue[i][j] = float(res.pvalue)
            resid = yv - (res.intercept + res.slope * xv)
            adf_p[i][j] = residual_adf_p(resid)
            dw[i][j] = float(durbin_watson(resid))
    return {
        "beta": beta,
        "r2": r2,
        "corr": corr_m,
        "pvalue": pvalue,
        "adfP": adf_p,
        "dw": dw,
    }


def _rank_pairs(present, r2, corr, beta, extra=None) -> list[dict]:
    ranked = []
    n = len(present)
    for i in range(n):
        for j in range(i + 1, n):
            row = {
                "i": i,
                "j": j,
                "y": present[i],
                "x": present[j],
                "r2": float(r2[i][j]),
                "corr": float(corr[i][j]),
                "betaYX": float(beta[i][j]),
                "betaXY": float(beta[j][i]),
            }
            if extra:
                row.update(extra(i, j))
            ranked.append(row)
    ranked.sort(key=lambda r: r["r2"], reverse=True)
    return ranked


def compute_ols(frame: pd.DataFrame) -> dict:
    """Fit both OLS systems on the trailing window of ``frame``.

    ``frame`` is the aligned weekday panel. The return window is the last
    251 closes (250 log returns). Log prices use those same 250 dates.
    """
    if len(frame) < N_RETURNS + 1:
        raise SystemExit(
            f"OLS window needs {N_RETURNS + 1} closes; the panel has {len(frame)}."
        )
    window = frame.iloc[-(N_RETURNS + 1) :]
    log_ret = np.log(window / window.shift(1)).dropna()
    if len(log_ret) != N_RETURNS:
        raise SystemExit(f"Expected {N_RETURNS} log returns, got {len(log_ret)}.")
    prices = window.loc[log_ret.index]
    if len(prices) != N_RETURNS:
        raise SystemExit(f"Expected {N_RETURNS} price rows, got {len(prices)}.")

    present = list(frame.columns)
    ret_mats = ols_return_matrices(log_ret)
    price_mats = ols_price_matrices(prices)

    def price_extra(i: int, j: int) -> dict:
        adf = float(price_mats["adfP"][i][j])
        r2v = float(price_mats["r2"][i][j])
        return {
            "adfP": adf,
            "dw": float(price_mats["dw"][i][j]),
            "spurious": bool(r2v >= SPURIOUS_R2 and adf >= SPURIOUS_ADF_P),
            "cointegrated": bool(adf < SPURIOUS_ADF_P),
        }

    spurious = []
    n = len(present)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if price_mats["r2"][i][j] >= SPURIOUS_R2 and price_mats["adfP"][i][j] >= SPURIOUS_ADF_P:
                spurious.append([i, j])

    return {
        "nReturns": int(len(log_ret)),
        "nPrices": int(len(prices)),
        "nCloses": int(len(window)),
        "returnStart": log_ret.index[0].strftime("%Y-%m-%d"),
        "returnEnd": log_ret.index[-1].strftime("%Y-%m-%d"),
        "priceStart": prices.index[0].strftime("%Y-%m-%d"),
        "priceEnd": prices.index[-1].strftime("%Y-%m-%d"),
        "closeStart": window.index[0].strftime("%Y-%m-%d"),
        "closeEnd": window.index[-1].strftime("%Y-%m-%d"),
        "beta": ret_mats["beta"],
        "r2": ret_mats["r2"],
        "corr": ret_mats["corr"],
        "pvalue": ret_mats["pvalue"],
        "priceBeta": price_mats["beta"],
        "priceR2": price_mats["r2"],
        "priceCorr": price_mats["corr"],
        "pricePvalue": price_mats["pvalue"],
        "priceAdf": price_mats["adfP"],
        "priceDw": price_mats["dw"],
        "spurious": spurious,
        "topReturns": _rank_pairs(present, ret_mats["r2"], ret_mats["corr"], ret_mats["beta"])[:40],
        "topPrices": _rank_pairs(
            present, price_mats["r2"], price_mats["corr"], price_mats["beta"], extra=price_extra
        )[:40],
        "spuriousRule": {"r2": SPURIOUS_R2, "adfP": SPURIOUS_ADF_P},
    }
