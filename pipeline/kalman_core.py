"""Kalman random-walk hedge and Shumway-Stoffer EM.

``_kalman_filter``, ``_rts_smooth``, ``shumway_stoffer_em`` and
``kalman_forward`` are copied verbatim from the research pipeline
(``hedge_methods.py``) so a refit on the same log prices matches that
code. ``ols_fit`` is the ordinary least squares used to seed EM:
intercept, slope, and residual sample standard deviation (ddof=1).
"""

from __future__ import annotations

import math

import numpy as np
from statsmodels.regression.linear_model import OLS


def ols_fit(y, x) -> dict:
    """OLS seed for EM. Matches hedge_methods.ols_fit given the same residual."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    design = np.column_stack([np.ones(len(y)), x])
    fit = OLS(y, design).fit()
    resid = np.asarray(fit.resid, float)
    if np.all(np.isfinite(resid)):
        sd = float(np.std(resid, ddof=1))
    else:
        sd = float("nan")
    return {"a": float(fit.params[0]), "b": float(fit.params[1]), "sd": sd}


# ---------------------------------------------------------------------------
# Kalman filter (dynamic hedge) — Shumway-Stoffer EM
# ---------------------------------------------------------------------------

def _kalman_filter(y, x, ve, Q, x0, P0):
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    T = len(y)
    xp = np.zeros((T, 2))
    Pp = np.zeros((T, 2, 2))
    xf = np.zeros((T, 2))
    Pf = np.zeros((T, 2, 2))
    innov = np.zeros(T)
    F = np.zeros(T)
    Ks = np.zeros((T, 2))
    xt, Pt = np.array(x0, float).copy(), np.array(P0, float).copy()
    I = np.eye(2)
    for t in range(T):
        if t == 0:
            x_pr, P_pr = xt, Pt
        else:
            x_pr = xf[t - 1]
            P_pr = Pf[t - 1] + Q
        xp[t] = x_pr
        Pp[t] = P_pr
        H = np.array([1.0, x[t]])
        Ft = float(H @ P_pr @ H + ve)
        if not np.isfinite(Ft) or Ft < 1e-18:
            Ft = 1e-18
        vt = float(y[t] - H @ x_pr)
        K = (P_pr @ H) / Ft
        innov[t] = vt
        F[t] = Ft
        Ks[t] = K
        xf[t] = x_pr + K * vt
        IKH = I - np.outer(K, H)
        Pf[t] = IKH @ P_pr @ IKH.T + np.outer(K, K) * ve
        Pf[t] = 0.5 * (Pf[t] + Pf[t].T)
    loglik = float(-0.5 * np.sum(np.log(2 * np.pi * F) + innov ** 2 / F))
    return xp, Pp, xf, Pf, innov, F, Ks, loglik


def _rts_smooth(xp, Pp, xf, Pf):
    """Rauch-Tung-Striebel smoother, Φ = I. Also returns lag-1 cov P_{t,t-1}^n."""
    T = len(xf)
    xs = np.zeros_like(xf)
    Ps = np.zeros_like(Pf)
    J = np.zeros((T, 2, 2))
    xs[-1] = xf[-1]
    Ps[-1] = Pf[-1]
    for t in range(T - 2, -1, -1):
        try:
            Jt = Pf[t] @ np.linalg.inv(Pp[t + 1])
        except np.linalg.LinAlgError:
            Jt = Pf[t] @ np.linalg.pinv(Pp[t + 1])
        J[t] = Jt
        xs[t] = xf[t] + Jt @ (xs[t + 1] - xp[t + 1])
        Ps[t] = Pf[t] + Jt @ (Ps[t + 1] - Pp[t + 1]) @ Jt.T
        Ps[t] = 0.5 * (Ps[t] + Ps[t].T)
    # Lag-1 smoothed covariances, Shumway-Stoffer appendix recursion.
    Pcs = np.zeros((T, 2, 2))
    # P_{T,T-1}^n = (I - K_T H_T) P_{T-1}^{T-1}  is recovered from:
    # P_{T,T-1}^n = P_T^T J_{T-1}'   with the last-step identity for Φ=I
    # Use: Pcs[t] = P_{t,t-1}^n  (t starts at 1)
    if T >= 2:
        Pcs[-1] = Ps[-1] @ J[-2].T  # will overwrite properly below
        # Standard backward recursion starting from t = T-1:
        # P_{t,t-1}^n = P_t^{t} J_{t-1}' + J_t (P_{t+1,t}^n - Φ P_t^{t}) J_{t-1}'
        # For t = T-1, J_T is not defined; use P_{T,T-1}^n = (I-KH) P_{T-1}^{T-1}
        # We compute Pcs[t] = Cov(x_t, x_{t-1} | y_{1:T}) for t=1..T-1 as Pcs[t]
        Pcs[-1] = Pf[-1] @ J[-2].T if T >= 2 else np.zeros((2, 2))
        # More stable: start with
        # P_{n,n-1}^n = J_{n-1} wait. Following Shumway & Stoffer (time series analysis):
        # P_{T, T-1}^n = (I - K_T A_T) Φ P_{T-1}^{T-1}
        # We don't have K,H here; equivalent for Φ=I: P_{T,T-1}^n = Ps[T-1] @ J[T-2].T
        # is an approximation used after the last update. Use de Jong:
        Pcs[-1] = Ps[-1] @ J[-2].T
        for t in range(T - 2, 0, -1):
            Pcs[t] = Pf[t] @ J[t - 1].T + J[t] @ (Pcs[t + 1] - xf[t] * 0 - Pf[t]) @ J[t - 1].T
            # The term (P_{t+1,t}^n - Φ P_t^t): Φ=I, P_t^t = Pf[t]
            Pcs[t] = Pf[t] @ J[t - 1].T + J[t] @ (Pcs[t + 1] - Pf[t]) @ J[t - 1].T
    return xs, Ps, Pcs, J


def shumway_stoffer_em(y, x, maxiter=80, tol=1e-6):
    """Estimate Ve and diagonal Q for the random-walk-beta Kalman model on the training window."""
    ols = ols_fit(y, x)
    ve = max(float(ols["sd"] ** 2), 1e-12)
    # Diffuse but finite initial state.
    x0 = np.array([ols["a"], ols["b"]], float)
    P0 = np.diag([max(ve, 1e-6), max(ve / max(np.var(x), 1e-8), 1e-8)])
    # Small state noise seed (Chan-style fraction of Ve).
    q_a = 1e-6 * ve
    q_b = 1e-6 * ve / max(np.var(x), 1e-8)
    Q = np.diag([q_a, q_b])
    history = []
    prev = -np.inf
    for it in range(maxiter):
        xp, Pp, xf, Pf, innov, F, Ks, loglik = _kalman_filter(y, x, ve, Q, x0, P0)
        xs, Ps, Pcs, J = _rts_smooth(xp, Pp, xf, Pf)
        T = len(y)
        # Initial state
        x0 = xs[0].copy()
        P0 = Ps[0].copy()
        P0 = 0.5 * (P0 + P0.T)
        # Q update, Φ = I, diagonal constraint.
        acc = np.zeros((2, 2))
        for t in range(1, T):
            da = xs[t] - xs[t - 1]
            acc += np.outer(da, da) + Ps[t] + Ps[t - 1] - Pcs[t] - Pcs[t].T
        Qn = acc / T
        Qn = 0.5 * (Qn + Qn.T)
        # Keep Q diagonal and positive.
        q = np.clip(np.diag(Qn), 1e-16, 1.0)
        Q = np.diag(q)
        # R / Ve update
        acc_r = 0.0
        for t in range(T):
            H = np.array([1.0, x[t]])
            acc_r += (y[t] - H @ xs[t]) ** 2 + float(H @ Ps[t] @ H)
        ve = max(acc_r / T, 1e-16)
        history.append({"iter": it, "loglik": loglik, "ve": ve, "q": [float(q[0]), float(q[1])]})
        if it > 2 and abs(loglik - prev) < tol * (1 + abs(prev)):
            break
        if it > 2 and loglik < prev - 1e-3:
            # Likelihood drop: stop at previous (can happen with the diagonal constraint).
            break
        prev = loglik
    xp, Pp, xf, Pf, innov, F, Ks, loglik = _kalman_filter(y, x, ve, Q, x0, P0)
    return {
        "ve": float(ve),
        "Q": Q,
        "x0": x0,
        "P0": P0,
        "loglik": float(loglik),
        "iters": len(history),
        "history": history[-3:],
        "train_ols_a": ols["a"],
        "train_ols_b": ols["b"],
        "delta_a": float(Q[0, 0] / ve) if ve > 0 else np.nan,
        "delta_b": float(Q[1, 1] / ve) if ve > 0 else np.nan,
    }


def kalman_forward(y, x, params):
    """Run the filter over the full sample with training-window parameters frozen."""
    xp, Pp, xf, Pf, innov, F, Ks, loglik = _kalman_filter(
        y, x, params["ve"], params["Q"], params["x0"], params["P0"]
    )
    return {
        "a_pred": xp[:, 0],
        "b_pred": xp[:, 1],
        "a_filt": xf[:, 0],
        "b_filt": xf[:, 1],
        "innov": innov,
        "F": F,
        "loglik": loglik,
    }
