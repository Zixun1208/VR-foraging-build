#!/usr/bin/env python3
"""The poster's reward-vs-control figure: time spent in each patch, reward-active flies
against flies fed no ATR (the optogenetic reward cannot switch on).

Only the earlier 50/50 task has a no-ATR control of the same genotype, so that is the one
comparison made (``figures/reward_vs_control.png``, two bars per patch). Bars are the geometric mean over flies of each fly's median time in the patch
(training, completed visits), with a bootstrap 95% interval; points are single flies. The p
value is a permutation test on the group label, using each fly's average log time over the
two patches.

Run (after pipeline.py has made survival.csv for every dataset):
    python -m selected_analysis.cross_dataset.reward_effect --runs runs
"""
from __future__ import annotations

import argparse
import itertools
import os
import re

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .. import config
from ..core.plotstyle import INK, TEAL, style
from ..core.stats import stars
from .summary_stats import DATASETS

GREEN, PURPLE = "#3f9f6f", "#8a63b8"
MIN_LEFT = 3        # completed visits per patch for a fly to count
# Only this pair is like for like: the earlier 50/50 task and the no-ATR flies run with it. The
# split-line and 1D-line datasets are other genotypes (or unrecorded), so they are not compared.
ACTIVE_KEY = "past_50_50"
CONTROL_KEYS = ["past_50_50_nonatr", "past_50_50_nonatr_b"]


def per_fly(survival_csv):
    """DataFrame fly_id x patch (0/1): median time in the patch over completed training visits."""
    s = pd.read_csv(survival_csv)
    left = s[(s.phase == "training") & (s.left == 1) & (s.qc_ok == 1)]
    n = left.groupby(["fly_id", "patch"]).size().unstack()
    med = left.groupby(["fly_id", "patch"]).t_bin.median().unstack()
    ok = (n[[0, 1]] >= MIN_LEFT).all(axis=1)
    return med.loc[ok, [0, 1]]


def perm_p(a, b, n_perm=20000, seed=0):
    """Two-sided permutation p of the difference in mean log time (per-fly patch average)."""
    a, b = np.log(np.asarray(a, float)), np.log(np.asarray(b, float))
    obs = abs(a.mean() - b.mean())
    allv = np.concatenate([a, b])
    na = len(a)
    if len(allv) <= 16:
        combos = list(itertools.combinations(range(len(allv)), na))
        diffs = [abs(allv[list(c)].mean() - np.delete(allv, list(c)).mean()) for c in combos]
        return float(np.mean(np.asarray(diffs) >= obs - 1e-12))
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(n_perm):
        rng.shuffle(allv)
        cnt += abs(allv[:na].mean() - allv[na:].mean()) >= obs - 1e-12
    return float((cnt + 1) / (n_perm + 1))


def gmean_ci(x, n_boot=5000, seed=1):
    x = np.log(np.asarray(x, float))
    rng = np.random.default_rng(seed)
    boots = np.exp(np.array([rng.choice(x, len(x)).mean() for _ in range(n_boot)]))
    return float(np.exp(x.mean())), np.percentile(boots, [2.5, 97.5])


def draw(groups, out, title):
    """groups: list of (label, colour, DataFrame fly x patch). One bar per group, per patch."""
    fig, axes = plt.subplots(1, 2, figsize=(max(6.4, 1.5 * len(groups) + 3.2), 4.4), sharey=True)
    for ax, patch in zip(axes, (0, 1)):
        for i, (label, col, tab) in enumerate(groups):
            vals = tab[patch].to_numpy()
            gm, ci = gmean_ci(vals)
            ax.bar(i, gm, color=col, alpha=0.86, width=0.62, yerr=[[gm - ci[0]], [ci[1] - gm]], capsize=5,
                   error_kw={"elinewidth": 1.8, "capthick": 1.8, "ecolor": INK})
            ax.scatter(np.full(len(vals), i) + np.linspace(-0.12, 0.12, len(vals)), vals, s=22,
                       color=INK, alpha=0.55, zorder=3)
            ax.text(i, ci[1] + 0.5, f"{gm:.0f} s", ha="center", va="bottom", fontsize=10, weight="bold")
        ax.set_xticks(range(len(groups)), [f"{g[0]}\n(n={len(g[2])})" for g in groups], fontsize=9)
        ax.set_title(f"Patch {patch + 1}", fontsize=13, weight="bold", color=TEAL)
        style(ax, 11)
    axes[0].set_ylabel("Time spent in patch (s)\naverage over flies", fontsize=12)
    ctrl = groups[0][2]
    y = max(float(t[[0, 1]].to_numpy().max()) for _, _, t in groups)
    for i, (label, col, tab) in enumerate(groups[1:], start=1):
        both_a = np.exp(np.log(tab[[0, 1]]).mean(axis=1))
        both_c = np.exp(np.log(ctrl[[0, 1]]).mean(axis=1))
        p = perm_p(both_a, both_c)
        axes[1].text(i, y * 1.12, f"p = {p:.3f} {stars(p)}", ha="center", fontsize=9, color=INK)
    axes[0].set_ylim(0, y * 1.3)
    fig.suptitle(title, fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=config.RUNS)
    a = ap.parse_args()
    by = {k: (rel, label) for k, rel, label, grp, atr in DATASETS}
    ctrl = pd.concat([per_fly(os.path.join(a.runs, by[k][0], "survival.csv")).rename(index=lambda i, k=k: f"{k}:{i}")
                      for k in CONTROL_KEYS])
    tab = per_fly(os.path.join(a.runs, by[ACTIVE_KEY][0], "survival.csv"))
    out = os.path.join(a.runs, by[ACTIVE_KEY][0], "figures", "reward_vs_control.png")
    draw([("no-ATR\ncontrol", PURPLE, ctrl), ("reward\nactive", GREEN, tab)], out,
         "Reward-active flies against the no-ATR control (50/50 task)")
    print(f"control flies: {len(ctrl)}, reward-active flies: {len(tab)} -> {out}")


if __name__ == "__main__":
    main()
