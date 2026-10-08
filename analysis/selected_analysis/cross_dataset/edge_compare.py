#!/usr/bin/env python3
"""Is time around patch 1's edges different from patch 2's?

Reads ``edge_profiles_by_fly.csv`` (written by edges.py). For every fly, phase and edge it adds up
the occupancy (share of trial time) over -5 to +5 units around the edge: one number per fly. The
figure has one panel per dataset (task or line), all on the same y axis, with the four edges
side by side for training and then for probing (patch 1 onset, patch 1 offset, patch 2 onset,
patch 2 offset): bar = mean over flies, error bar = s.e.m., dots = single flies, a star = the
patch 1 / patch 2 pair differs (paired exact sign-flip, p < 0.05, uncorrected).

    edge_window_plain.png      occupancy accumulated over -5..+5 (% of trial time)
    edge_window_baseline.png   the same minus the fly's own baseline over those 11 units
                               (its mean share 15 to 9 units before the edge), so 0 = usual pace

``edge_patch_compare.csv`` holds the numbers behind both: per dataset, phase and edge type, the
mean for patch 1 and patch 2, their difference, how many flies are higher at patch 2, and p.
Probing has no reward at either patch, so a difference that is there in training but not in probing
is about reward, not position.

Run (after edges.py):
    python -m selected_analysis.cross_dataset.edge_compare
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from .. import config
from ..core.plotstyle import COLORS as PHASE_COLORS, INK
from ..core.stats import signflip_p
from .edges import BASE, COLORS as DATASET_ORDER, EDGES

WINDOW = (-5, 5)
MEASURES = {"plain": ("share", "Occupancy accumulated over -5 to +5 units (% of trial time)"),
            "baseline": ("extra", "Occupancy over -5 to +5 units minus own baseline (percentage points)")}
LABELS = ["P1 on", "P1 off", "P2 on", "P2 off"]


def per_fly_window(df):
    """One row per dataset, fly, phase, patch, edge: occupancy summed over WINDOW, and the same minus baseline."""
    key = ["dataset", "fly_id", "phase", "patch", "edge"]
    base = df[(df.offset >= BASE[0]) & (df.offset <= BASE[1])].groupby(key).share.mean().rename("base")
    w = df[(df.offset >= WINDOW[0]) & (df.offset <= WINDOW[1])]
    out = w.groupby(key).share.sum().rename("share").reset_index().join(base, on=key)
    out["extra"] = out.share - out.base * (WINDOW[1] - WINDOW[0] + 1)
    return out


def pair_tests(pf, col):
    """{(dataset, phase, edge): (p, n)} for patch 2 against patch 1, paired by fly."""
    res = {}
    for (name, phase, edge), g in pf.groupby(["dataset", "phase", "edge"]):
        p = g.pivot(index="fly_id", columns="patch", values=col).dropna()
        if len(p) >= 3 and {"patch 1", "patch 2"} <= set(p):
            res[(name, phase, edge)] = signflip_p(p["patch 2"] - p["patch 1"])
    return res


def draw(pf, measure, out):
    col, ylabel = MEASURES[measure]
    datasets = [d for d in DATASET_ORDER if d in set(pf.dataset)]
    ncol = 4
    nrow = -(-len(datasets) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(16, 3.2 * nrow + 1.0), sharey=True, squeeze=False)
    tests = pair_tests(pf, col)
    rng = np.random.default_rng(0)
    top, bottom = 0.0, 0.0
    stats = {}
    for ax, name in zip(axes.flat, datasets):
        d = pf[pf.dataset == name]
        xs, ticks = [], []
        for k, phase in enumerate(("training", "probing")):
            for j, (patch, edge, _) in enumerate(EDGES):
                x = k * 5 + j
                v = d[(d.phase == phase) & (d.patch == patch) & (d.edge == edge)][col].to_numpy()
                if len(v) == 0:
                    continue
                m, se = v.mean(), (v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0)
                ax.bar(x, m, width=0.72, color=PHASE_COLORS[phase], alpha=0.85 if patch == "patch 1" else 0.5,
                       hatch="" if patch == "patch 1" else "//", edgecolor=PHASE_COLORS[phase], lw=0.8, zorder=2)
                ax.errorbar(x, m, yerr=se, color=INK, capsize=3, lw=1.2, zorder=4)
                ax.scatter(x + rng.uniform(-0.2, 0.2, len(v)), v, s=7, color=INK, alpha=0.45, zorder=3, linewidths=0)
                top, bottom = max(top, m + se, v.max()), min(bottom, m - se, v.min())
                stats[(name, phase, edge, patch)] = (m, se)
        ax.set_title(f"{name}  (n={d.fly_id.nunique()})", fontsize=11, weight="bold", pad=20)
        ax.set_xticks([k * 5 + j for k in (0, 1) for j in range(4)])
        ax.set_xticklabels(LABELS * 2, rotation=60, ha="right", fontsize=8)
        ax.axhline(0, color="#999999", lw=0.8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.text(1.5, 1.01, "training", transform=ax.get_xaxis_transform(), ha="center", color=PHASE_COLORS["training"], fontsize=9, weight="bold")
        ax.text(6.5, 1.01, "probing", transform=ax.get_xaxis_transform(), ha="center", color=PHASE_COLORS["probing"], fontsize=9, weight="bold")
        ax.set_xlim(-0.8, 9.8)
    # stars over pairs with p < 0.05 (patch 1 vs patch 2, same edge type, same phase)
    span = max(top - bottom, 1e-9)
    step = next(st for st in (1, 2, 5, 10, 20, 25, 50) if span / st <= 10)
    hi = np.ceil((top + 0.08 * span) / step) * step
    lo = 0 if bottom >= 0 else np.floor((bottom - 0.04 * span) / step) * step
    for ax, name in zip(axes.flat, datasets):
        for k, phase in enumerate(("training", "probing")):
            for e, (ia, ib) in (("onset", (0, 2)), ("offset", (1, 3))):
                p = tests.get((name, phase, e))
                if p is not None and p < 0.05:
                    xa, xb = k * 5 + ia, k * 5 + ib
                    y = hi - 0.06 * (hi - lo) if e == "onset" else hi - 0.12 * (hi - lo)
                    ax.plot([xa, xa, xb, xb], [y - 0.01 * (hi - lo), y, y, y - 0.01 * (hi - lo)], color=INK, lw=0.9)
                    ax.text((xa + xb) / 2, y, "*" if p >= 0.01 else "**", ha="center", va="bottom", fontsize=11)
    for ax in axes.flat:
        ax.set_ylim(lo, hi)
        ax.yaxis.set_major_locator(MultipleLocator(step))
    for ax in axes.flat[len(datasets):]:
        ax.set_visible(False)
    for r in range(nrow):
        axes[r, 0].set_ylabel(ylabel if nrow == 1 else "", fontsize=9)
    fig.supylabel(ylabel, fontsize=10)
    fig.suptitle("Time around the patch edges: plain bars = patch 1, hatched = patch 2; mean +/- s.e.m. over flies, dots = single flies, "
                 "* = patch 1 vs 2 differ (paired, p<0.05)", fontsize=11, weight="bold")
    fig.tight_layout(rect=(0.01, 0, 1, 0.95))
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)


def patch_table(pf):
    rows = []
    for measure, (col, _) in MEASURES.items():
        for (name, phase, edge), g in pf.groupby(["dataset", "phase", "edge"]):
            p = g.pivot(index="fly_id", columns="patch", values=col).dropna()
            if p.empty or not {"patch 1", "patch 2"} <= set(p):
                continue
            diff = p["patch 2"] - p["patch 1"]
            rows.append({"dataset": name, "phase": phase, "edge": edge, "measure": measure, "n_flies": len(p),
                         "patch1_mean": p["patch 1"].mean(), "patch2_mean": p["patch 2"].mean(),
                         "patch2_minus_patch1": diff.mean(), "flies_patch2_higher": int((diff > 0).sum()),
                         "p_signflip": signflip_p(diff) if len(p) >= 3 else np.nan})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=config.SUMMARY, help="folder with edge_profiles_by_fly.csv; figures go here too")
    a = ap.parse_args()
    src = os.path.join(a.dir, "edge_profiles_by_fly.csv")
    if not os.path.isfile(src):
        print(f"{src} missing; run cross_dataset/edges.py first")
        return
    pf = per_fly_window(pd.read_csv(src))
    for measure in MEASURES:
        draw(pf, measure, os.path.join(a.dir, f"edge_window_{measure}.png"))
    tab = patch_table(pf)
    tab.to_csv(os.path.join(a.dir, "edge_patch_compare.csv"), index=False)
    print("wrote edge_window_plain.png, edge_window_baseline.png, edge_patch_compare.csv in", a.dir)


if __name__ == "__main__":
    main()
