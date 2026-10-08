# Vendored unchanged from perceptual-decision-making/scripts/ so this directory stands alone.
"""Continuous drifting-weights GLM baseline (PsyTrack / AR(1) analog, Gaussian version).

The paper argues the latent states are *discrete* by showing the GLM-HMM beats a model
with smoothly *drifting* weights (PsyTrack). PsyTrack is Bernoulli-only, so for our
continuous log-dwell observable we use the equivalent linear-Gaussian dynamic regression:

    y_t = x_t . w_t + N(0, R)
    w_t = w_{t-1} + N(0, Q),   Q = q * I   (isotropic random walk)

Inference is a Kalman filter with the (time-varying) observation vector x_t. The two
hyperparameters (q, R) are fit by grid search maximizing the training marginal
likelihood.

Held-out scoring is made directly comparable to the GLM-HMM's masked forward-backward:
  * held-out LL = logp(all observed) - logp(train only), both from the Kalman marginal
    likelihood (so held-out points are conditioned on *all* other observed points, past
    and future -- i.e. smoothing, matching the GLM-HMM).
  * held-out predictions for R^2 come from an RTS smoother run with the held-out points
    masked (not used to update), so they are predicted from their neighbours -- the
    continuous analog of the GLM-HMM's smoothed state posterior.
"""
from __future__ import annotations

import numpy as np

_LOG2PI = np.log(2.0 * np.pi)


def pooled_weights(datas, inputs, masks=None, ridge=1e-3):
    """Pooled ridge-regression weights over a set of sequences.

    Used as the prior mean w_0 for the filter. Must be computed from *training* data
    only -- it is the drift model's counterpart to the GLM-HMM's fitted state weights,
    which likewise carry the population's dwell level onto a new animal.
    """
    Xs, ys = [], []
    for i, (d, X) in enumerate(zip(datas, inputs)):
        X = np.asarray(X, float); y = np.asarray(d, float)
        if masks is not None:
            keep = np.asarray(masks[i], float) == 1
            X, y = X[keep], y[keep]
        Xs.append(X); ys.append(y)
    X = np.concatenate(Xs); y = np.concatenate(ys)
    M = X.shape[1]
    return np.linalg.solve(X.T @ X + ridge * np.eye(M), X.T @ y)


def _filter(y, X, mask, q, R, w0=None, w0_var=10.0):
    """Kalman filter over one sequence with observation vectors X[t].

    `w0` is the prior mean for the weights (zeros if None). A zero prior mean makes the
    filter predict log-dwell = 0 (i.e. 1 s) on the first encounters of every sequence,
    which is harmless for the marginal likelihood -- the prior variance is diffuse, so
    those predictions are honestly uncertain -- but badly distorts point-prediction R^2.

    Returns train_ll (summed one-step predictive log-lik of updated points) and the
    stored arrays needed for RTS smoothing.
    """
    T, M = X.shape
    w = np.zeros(M) if w0 is None else np.asarray(w0, float).copy()
    P = np.eye(M) * w0_var
    Q = q * np.eye(M)
    train_ll = 0.0
    w_pred = np.zeros((T, M)); P_pred = np.zeros((T, M, M))
    w_filt = np.zeros((T, M)); P_filt = np.zeros((T, M, M))
    for t in range(T):
        if t > 0:
            P = P + Q
        w_pred[t] = w; P_pred[t] = P
        h = X[t]
        yp = float(h @ w)
        s = float(h @ P @ h) + R
        resid = y[t] - yp
        if mask[t] == 1:
            train_ll += -0.5 * (_LOG2PI + np.log(s) + resid * resid / s)
            K = (P @ h) / s
            w = w + K * resid
            P = P - np.outer(K, h) @ P
        w_filt[t] = w; P_filt[t] = P
    return train_ll, w_pred, P_pred, w_filt, P_filt, Q


def _rts_smooth(w_pred, P_pred, w_filt, P_filt):
    """Rauch-Tung-Striebel smoother -> smoothed weight means per t."""
    T, M = w_filt.shape
    w_s = w_filt.copy(); P_s = P_filt.copy()
    for t in range(T - 2, -1, -1):
        A = P_filt[t] @ np.linalg.pinv(P_pred[t + 1])
        w_s[t] = w_filt[t] + A @ (w_s[t + 1] - w_pred[t + 1])
        P_s[t] = P_filt[t] + A @ (P_s[t + 1] - P_pred[t + 1]) @ A.T
    return w_s


def _train_ll_total(datas, inputs, masks, q, R, w0=None):
    return sum(_filter(y, X, m, q, R, w0=w0)[0]
               for y, X, m in zip(datas, inputs, masks))


def fit_hyperparams(datas, inputs, masks, w0=None,
                    q_grid=(1e-4, 1e-3, 1e-2, 5e-2, 1e-1, 5e-1),
                    R_grid=(0.2, 0.4, 0.6, 0.8, 1.0)):
    """Grid-search (q, R) maximizing training marginal likelihood."""
    best = None
    for q in q_grid:
        for R in R_grid:
            ll = _train_ll_total(datas, inputs, masks, q, R, w0=w0)
            if best is None or ll > best[0]:
                best = (ll, q, R)
    return best[1], best[2]


def causal_score(datas, inputs, q, R, w0=None):
    """Causal (filter-only) held-out LL and one-step-ahead predictions.

    For each sequence, runs the Kalman filter over ALL points and returns the summed
    one-step predictive log-likelihood plus the predicted means x_t . w_pred_t (from the
    pre-update prior). No RTS smoother -> no future leakage. Use for leave-flies-out CV.
    `w0` must come from training sequences only.
    """
    total = 0.0
    yt, yp = [], []
    for y, X in zip(datas, inputs):
        y = np.asarray(y, float); X = np.asarray(X, float)
        ll, w_pred, _, _, _, _ = _filter(y, X, np.ones(len(y)), q, R, w0=w0)
        total += ll
        yt.append(y); yp.append(np.einsum("tm,tm->t", X, w_pred))
    return total, np.concatenate(yt), np.concatenate(yp)


def score(datas, inputs, masks, q, R, w0=None):
    """Held-out LL (smoothing-consistent) and smoothed predictions for R^2.

    test_ll = logp(all observed) - logp(train only), matching the GLM-HMM's masked
    forward-backward. Predictions at held-out points come from the RTS smoother run
    with those points masked.
    """
    total = 0.0
    yt, yp = [], []
    for y, X, m in zip(datas, inputs, masks):
        m = np.asarray(m, float)
        ll_train, w_pred, P_pred, w_filt, P_filt, _ = _filter(y, X, m, q, R, w0=w0)
        ll_all, *_ = _filter(y, X, np.ones_like(m), q, R, w0=w0)
        total += (ll_all - ll_train)
        test_idx = np.where(m == 0)[0]
        if test_idx.size:
            w_s = _rts_smooth(w_pred, P_pred, w_filt, P_filt)
            preds = np.einsum("tm,tm->t", X[test_idx], w_s[test_idx])
            yp.append(preds); yt.append(np.asarray(y)[test_idx])
    return total, (np.concatenate(yt) if yt else np.array([])), \
        (np.concatenate(yp) if yp else np.array([]))
