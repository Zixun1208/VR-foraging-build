#!/usr/bin/env python3
"""The poster's model comparison ("Predicting a new fly") for any dataset.

Each patch visit gives one observation, y = log(time spent in the patch). Four ways of
predicting a fly that the model has never seen are compared, each scored by how much better
it predicts than a single average (bits per visit; higher is better):

    shared rule        one regression for all flies           (poster: "pooled GLM")
    strategy switching a few hidden strategies, 3 states      (poster: "GLM-HMM")
    fixed differences  stable per-fly offsets in bias, phase  (poster: "hierarchical GLM")
    slowly changing    weights that drift over the session    (poster: "drifting GLM")

Inputs per visit: constant, which patch, time spent in that patch last trial, training vs
probing, and position in the session. Flies are split into folds; each held-out fly is
predicted visit by visit from its own past only. Every held-out fly gets its own score, and
the models are compared with a paired sign-flip test across flies (Holm over the three
poster comparisons). The GLM-HMM and drifting code is vendored from
perceptual-decision-making/scripts (glmhmm.py, drift.py).

Needs at least MIN_FLIES flies. Run:
    python -m selected_analysis.per_dataset.models --raw-root ~/Raw_data --task <task folder> --selection applied --out <dir>
"""
from __future__ import annotations

import argparse
import itertools
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.linalg import cho_factor, cho_solve

from ..vendored import drift
from ..core import selection
from ..core import trials
from ..core.plotstyle import BLUE, INK, ORANGE, TEAL, style
from ..core.stats import signflip_p, stars
from ..vendored.glmhmm import GaussianGLMHMM

PURPLE = "#8a63b8"
LN2 = np.log(2.0)
LOG2PI = np.log(2.0 * np.pi)
COVARIATES = ["bias", "patch", "prev_dwell", "phase", "session_pos"]
RANDOM_EFFECTS = ["bias", "phase"]
DWELL_EPS = 0.1                 # s, floor before the log
MIN_TRAVERSAL_SEC, MAX_TRAVERSAL_SEC = 5.0, 900.0
MIN_FLIES = 5
MODELS = ("shared", "switching", "fixed", "changing")
LABELS = {"shared": "One shared\nrule", "switching": "Switching\nstrategies",
          "fixed": "Fixed fly\ndifferences", "changing": "Slowly\nchanging"}
COLORS = {"shared": BLUE, "switching": PURPLE, "fixed": TEAL, "changing": ORANGE}


# ---- data -------------------------------------------------------------------------------
def build_design(raw_root, task, kind="recommended", dates=None) -> pd.DataFrame:
    """One row per patch visit of every selected trial (also visits shorter than 1 s)."""
    patches = trials.parse_task(task)["patches"]
    rows = []
    for s in selection.iter_selected(raw_root, kind, task, dates):
        files = []
        for phase in ("training", "probing"):
            for name in s.kept[phase]:
                path = os.path.join(s.sub_dir, phase, name)
                meta = trials.parse_fname(path)
                if meta and os.path.isfile(path) and trials.trial_ok(path):
                    files.append((meta["ts"], phase, path))
        files.sort()
        prev = {0: np.nan, 1: np.nan}
        enc = 0
        for order, (_, phase, path) in enumerate(files):
            traj = trials.load_trajectory(path)
            if traj is None:
                continue
            t, X = traj
            dt = trials.sample_dt(t)
            trav = float(dt.sum())
            reached = bool((X >= trials.REACHED_END_X).any())
            qc = int(reached and MIN_TRAVERSAL_SEC <= trav <= MAX_TRAVERSAL_SEC)
            for patch, spec in patches.items():
                dwell = trials.band_dwell(dt, X, spec["band"])
                rows.append({"fly_id": s.fly_id, "phase": phase, "encounter_order": enc,
                             "trial_order": order, "patch": patch, "dwell_sec": dwell,
                             "prev_dwell": prev[patch], "qc_ok": qc})
                prev[patch] = dwell
                enc += 1
    return pd.DataFrame(rows)


def build_sequences(df):
    """{fly: (y, X)} with y = log time in patch and X the covariates (z-scored history)."""
    df = df[df.qc_ok == 1].sort_values(["fly_id", "encounter_order"]).copy()
    df["y"] = np.log(np.clip(df.dwell_sec.to_numpy(float), DWELL_EPS, None))
    pv = np.log(np.clip(df.prev_dwell.to_numpy(float), DWELL_EPS, None))
    pv = np.where(np.isfinite(df.prev_dwell.to_numpy(float)), pv, np.nan)
    mu, sd = np.nanmean(pv), np.nanstd(pv)
    df["prev_dwell"] = np.where(np.isfinite(pv), (pv - mu) / (sd or 1.0), 0.0)
    df["bias"] = 1.0
    df["patch"] = np.where(df.patch.to_numpy() == 1, 1.0, -1.0)
    df["phase"] = np.where(df.phase.to_numpy() == "training", 1.0, -1.0)
    seqs = {}
    for fly, g in df.groupby("fly_id", sort=True):
        n = len(g)
        g = g.assign(session_pos=2.0 * np.arange(n) / max(n - 1, 1) - 1.0)
        seqs[fly] = (g.y.to_numpy(float), g[COVARIATES].to_numpy(float))
    return seqs


# ---- shared and fixed-difference models (after perceptual-decision-making hierarchical.py) -
def ridge_glm(datas, inputs, ridge=1e-3):
    X, y = np.concatenate(inputs), np.concatenate(datas)
    beta = np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)
    return beta, max(float((y - X @ beta).var()), 1e-3)


def normal_ll(y, mean, R):
    r = y - mean
    return float(np.sum(-0.5 * (LOG2PI + np.log(R) + r * r / R)))


def _cov(Z, tau2, R):
    return R * np.eye(Z.shape[0]) + (Z * tau2[None, :]) @ Z.T


def _beta_gls(datas, inputs, re_idx, tau2, R, ridge=1e-6):
    M = inputs[0].shape[1]
    A, b = ridge * np.eye(M), np.zeros(M)
    for y, X in zip(datas, inputs):
        cf = cho_factor(_cov(X[:, re_idx], tau2, R), lower=True, check_finite=False)
        A += X.T @ cho_solve(cf, X, check_finite=False)
        b += X.T @ cho_solve(cf, y, check_finite=False)
    return np.linalg.solve(A, b)


def _marginal_ll(datas, inputs, re_idx, tau2, R, beta):
    total = 0.0
    for y, X in zip(datas, inputs):
        cf = cho_factor(_cov(X[:, re_idx], tau2, R), lower=True, check_finite=False)
        r = y - X @ beta
        total += -0.5 * (len(y) * LOG2PI + 2.0 * float(np.log(np.diag(cf[0])).sum())
                         + float(r @ cho_solve(cf, r, check_finite=False)))
    return total


def fit_fixed_differences(datas, inputs, re_idx, tau_grid=(0.0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.2),
                          R_grid=(0.1, 0.2, 0.4, 0.6, 0.8, 1.0)):
    """Empirical Bayes: grid search of the per-fly offset SDs and the noise variance."""
    best = None
    for taus in itertools.product(tau_grid, repeat=len(re_idx)):
        tau2 = np.square(np.asarray(taus, float))
        for R in R_grid:
            try:
                beta = _beta_gls(datas, inputs, re_idx, tau2, R)
                ll = _marginal_ll(datas, inputs, re_idx, tau2, R, beta)
            except np.linalg.LinAlgError:
                continue
            if best is None or ll > best["ll"]:
                best = {"ll": ll, "beta": beta, "tau": np.asarray(taus, float), "R": float(R)}
    if best is None:
        raise RuntimeError("fixed-difference model: grid search failed")
    return best


def causal_ll_fixed(y, X, beta, tau, R, re_idx):
    """Visit-by-visit log-likelihood, updating only this fly's offset estimate."""
    tau2 = np.square(np.asarray(tau, float))
    Z = X[:, re_idx]
    mu, P = np.zeros(len(re_idx)), np.diag(tau2)
    total = 0.0
    for yi, x, z in zip(y, X, Z):
        mean = float(x @ beta + z @ mu)
        var = max(float(z @ P @ z + R), 1e-9)
        r = yi - mean
        total += -0.5 * (LOG2PI + np.log(var) + r * r / var)
        if np.any(P):
            gain = (P @ z) / var
            mu = mu + gain * r
            P = P - np.outer(gain, z) @ P
            P = 0.5 * (P + P.T)
    return total


# ---- cross-validation -----------------------------------------------------------------------
def cross_validate(seqs, n_folds=5, seed=0, n_states=3, restarts=4, max_iter=100):
    """Per-fly bits per visit for each model, leaving flies out fold by fold."""
    flies = list(seqs)
    order = flies.copy()
    np.random.default_rng(seed).shuffle(order)
    nf = min(n_folds, len(flies))
    fold_of = {fly: i % nf for i, fly in enumerate(order)}
    re_idx = [COVARIATES.index(n) for n in RANDOM_EFFECTS]
    M = len(COVARIATES)
    bits = {m: {} for m in MODELS}
    for f in range(nf):
        train = [x for x in flies if fold_of[x] != f]
        test = [x for x in flies if fold_of[x] == f]
        tr_d, tr_i = [seqs[x][0] for x in train], [seqs[x][1] for x in train]
        ytr = np.concatenate(tr_d)
        mu, var = float(ytr.mean()), max(float(ytr.var()), 1e-3)
        beta, R = ridge_glm(tr_d, tr_i)
        hmm = GaussianGLMHMM(n_states, M, sigma_w=2.0, alpha=2.0, seed=seed + f)
        hmm.fit(tr_d, tr_i, n_restarts=restarts, max_iter=max_iter)
        fixed = fit_fixed_differences(tr_d, tr_i, re_idx)
        w0 = drift.pooled_weights(tr_d, tr_i)
        q, dR = drift.fit_hyperparams(tr_d, tr_i, [np.ones(len(y)) for y in tr_d], w0=w0)
        for fly in test:
            y, X = seqs[fly]
            n = len(y)
            base = normal_ll(y, mu, var)
            lls = {"shared": normal_ll(y, X @ beta, R),
                   "switching": hmm.causal_ll_and_pred(y, X)[0],
                   "fixed": causal_ll_fixed(y, X, fixed["beta"], fixed["tau"], fixed["R"], re_idx),
                   "changing": drift.causal_score([y], [X], q, dR, w0=w0)[0]}
            for m, ll in lls.items():
                bits[m][fly] = (ll - base) / (n * LN2)
    return pd.DataFrame(bits)


def compare(per_fly):
    """Paired sign-flip p (Holm over the three poster comparisons) across flies."""
    pairs = {"switching - shared": ("switching", "shared"), "fixed - switching": ("fixed", "switching"),
             "changing - fixed": ("changing", "fixed")}
    raw = {k: signflip_p((per_fly[a] - per_fly[b]).to_numpy()) for k, (a, b) in pairs.items()}
    order = sorted(raw, key=raw.get)
    holm, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, raw[k] * (len(order) - i)))
        holm[k] = run
    return {k: {"p": raw[k], "p_holm": holm[k]} for k in pairs}


def switching_summary(seqs, n_states=3, restarts=4, max_iter=100, seed=0):
    """Fit once on all flies: transition matrix, expected stay, switches per fly."""
    datas, inputs = [v[0] for v in seqs.values()], [v[1] for v in seqs.values()]
    m = GaussianGLMHMM(n_states, len(COVARIATES), sigma_w=2.0, alpha=2.0, seed=seed)
    m.fit(datas, inputs, n_restarts=restarts, max_iter=max_iter)
    o = np.argsort(m.W[:, 0])
    A = m.transition_matrix[np.ix_(o, o)]
    stay = m.expected_dwell()[o]
    sw = [int(np.sum(np.diff(m.most_likely_states(y, X)) != 0)) for y, X in zip(datas, inputs)]
    return A, stay, float(np.median(sw))


# ---- figure -------------------------------------------------------------------------------------
def bracket(ax, x1, x2, y, h, text):
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], color=INK, lw=1.4)
    ax.text((x1 + x2) / 2, y + h * 1.2, text, ha="center", va="bottom", fontsize=13, color=INK)


def plot(per_fly, stats, A, stay, switches, out, n_flies):
    vals = np.array([per_fly[m].mean() for m in MODELS])
    sems = np.array([per_fly[m].std(ddof=1) / np.sqrt(len(per_fly)) for m in MODELS])
    fig, (ax, sx) = plt.subplots(1, 2, figsize=(9.5, 4.4), gridspec_kw={"width_ratios": [1.6, 1.0], "wspace": 0.32})
    x = np.arange(len(MODELS))
    ax.bar(x, vals, yerr=sems, color=[COLORS[m] for m in MODELS], alpha=0.88, capsize=7,
           error_kw={"elinewidth": 2, "capthick": 2, "ecolor": INK})
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(x, [LABELS[m] for m in MODELS], fontsize=11)
    ax.set_ylabel("Prediction of a new fly's time in patch\n(bits per visit, higher is better)", fontsize=12)
    ax.set_title(f"Predicting a new fly (n = {n_flies} flies)", weight="bold", fontsize=15, pad=12)
    top = float(np.max(vals + sems))
    span = max(top, 0.05)
    k = ["switching - shared", "fixed - switching", "changing - fixed"]
    heights = [0.06, 0.20, 0.06]
    for (a, b), key, hgt in zip([(0, 1), (1, 2), (2, 3)], k, heights):
        p = stats[key]["p_holm"]
        bracket(ax, a, b, top + hgt * span, 0.04 * span, stars(p))
    ax.set_ylim(min(0, float(np.min(vals - sems)) * 1.2), top + 0.42 * span)
    style(ax, 11)
    sx.imshow(A, vmin=0, vmax=1, cmap="YlGnBu")
    for i in range(A.shape[0]):
        for j in range(A.shape[1]):
            sx.text(j, i, f"{A[i, j]:.2f}", ha="center", va="center", fontsize=12, weight="bold",
                    color="white" if A[i, j] > 0.55 else INK)
    names = [f"S{i + 1}" for i in range(A.shape[0])]
    sx.set_xticks(range(len(names)), names)
    sx.set_yticks(range(len(names)), names)
    sx.set_xlabel("Next strategy", fontsize=12)
    sx.set_ylabel("Current strategy", fontsize=12)
    sx.set_title("How the switching model\nmoves between strategies", fontsize=12, weight="bold", pad=10)
    stay_pct = 100 * float(np.mean(np.diag(A)))
    sx.text(0.5, -0.30, f"On average {stay_pct:.0f}% of visits stay in the same strategy\n"
            f"Stay length: {stay.min():.0f}-{stay.max():.0f} visits\nMedian fly switches {switches:.0f} times per session",
            transform=sx.transAxes, ha="center", va="top", fontsize=10.5, color=INK, linespacing=1.3)
    fig.subplots_adjust(left=0.1, right=0.98, top=0.86, bottom=0.30)
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run(raw_root, task, kind, out, dates=None, **kw):
    """Write model_comparison.png/.csv under ``out``; None if there are too few flies."""
    seqs = build_sequences(build_design(raw_root, task, kind, dates))
    if len(seqs) < MIN_FLIES:
        return None
    os.makedirs(out, exist_ok=True)
    per_fly = cross_validate(seqs, **kw)
    stats = compare(per_fly)
    A, stay, sw = switching_summary(seqs, **{k: v for k, v in kw.items() if k in ("restarts", "max_iter", "n_states", "seed")})
    per_fly.rename_axis("fly_id").to_csv(os.path.join(out, "model_comparison_by_fly.csv"))
    plot(per_fly, stats, A, stay, sw, os.path.join(out, "model_comparison.png"), len(seqs))
    summ = per_fly.agg(["mean", "sem"]).T
    for k, v in stats.items():
        summ.loc[k, ["mean", "sem"]] = [np.nan, np.nan]
        summ.loc[k, "p"], summ.loc[k, "p_holm"] = v["p"], v["p_holm"]
    summ.to_csv(os.path.join(out, "model_comparison.csv"))
    return summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-root", default=selection.RAW_ROOT)
    ap.add_argument("--task", required=True)
    ap.add_argument("--selection", choices=("recommended", "applied"), default="recommended")
    ap.add_argument("--out", required=True)
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()
    res = run(a.raw_root, a.task, a.selection, a.out, n_folds=a.folds)
    if res is None:
        raise SystemExit(f"needs at least {MIN_FLIES} flies")
    print(res.round(3).to_string())


if __name__ == "__main__":
    main()
