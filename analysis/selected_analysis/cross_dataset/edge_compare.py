#!/usr/bin/env python3
"""Is time spent around patch 1's edges different from patch 2's?

Reads ``edge_profiles_by_fly.csv`` (written by edges.py) and draws, for every dataset, the four
edges (patch 1 onset / offset, patch 2 onset / offset) from -5 to +5 units, training and probing
overlaid, mean over flies with a standard error bar:

    edge_compare_plain.png     share of trial time per unit
    edge_compare_baseline.png  the same minus each fly's own baseline at that edge
                               (mean share 15 to 9 units before it), so 0 = usual pace

Also writes ``edge_patch_compare.csv``: per dataset, phase and edge type, each fly's mean over
0 to +5 units at patch 1 and at patch 2 (both measures) and a paired exact sign-flip test of
patch 1 against patch 2. Probing has no reward at either patch, so a difference that is there in
training but not in probing is about reward, not position. Raw p values, not corrected.

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

from .. import config
from ..core.plotstyle import COLORS as PHASE_COLORS, INK, SHADE
from ..core.stats import signflip_p
from .edges import BASE, COLORS as DATASET_ORDER, EDGES, same_y

WINDOW = (-5, 5)
EFFECT = (0, 5)                     # offsets that make up each fly's number in the table
MEASURES = {"plain": "share of trial time per unit (%)", "baseline": "share minus own baseline (percentage points, 0 = usual)"}


def with_baseline(df):
    """Add ``extra``: each fly's share minus its own mean share at BASE offsets (same edge and phase)."""
    key = ["dataset", "fly_id", "phase", "patch", "edge"]
    base = df[(df.offset >= BASE[0]) & (df.offset <= BASE[1])].groupby(key).share.mean().rename("base")
    out = df.join(base, on=key)
    out["extra"] = out.share - out.base
    return out


def draw(df, measure, out):
    col = "share" if measure == "plain" else "extra"
    datasets = [d for d in DATASET_ORDER if d in set(df.dataset)]
    fig, axes = plt.subplots(len(datasets), 4, figsize=(14, 2.25 * len(datasets) + 1.2), sharex=True, squeeze=False)
    w = df[(df.offset >= WINDOW[0]) & (df.offset <= WINDOW[1])]
    for r, name in enumerate(datasets):
        d = w[w.dataset == name]
        for c, (patch, edge, pos) in enumerate(EDGES):
            ax = axes[r, c]
            ax.axvspan(0, WINDOW[1], color=SHADE, alpha=0.4, zorder=0)
            ax.axvline(0, color=INK, lw=1.0)
            if measure == "baseline":
                ax.axhline(0, color="#999999", lw=0.8)
            for k, phase in enumerate(("training", "probing")):
                g = d[(d.phase == phase) & (d.patch == patch) & (d.edge == edge)]
                s = g.groupby("offset")[col].agg(["mean", "sem"])
                if s.empty:
                    continue
                ax.errorbar(s.index + (k - 0.5) * 0.12, s["mean"], yerr=s["sem"], color=PHASE_COLORS[phase], lw=1.6,
                            marker="o", ms=3, capsize=2, label=phase)
            if r == 0:
                ax.set_title(f"{patch.capitalize()} {edge}\n({'entrance' if edge == 'onset' else 'exit'}, position {pos:.0f})",
                             fontsize=10.5, weight="bold")
            if c == 0:
                n = d.fly_id.nunique()
                ax.set_ylabel(f"{name}\n(n={n})", fontsize=9)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("Distance from the edge (corridor units)", fontsize=9)
        ax.set_xticks(range(WINDOW[0], WINDOW[1] + 1, 5))
    axes[0, 0].legend(frameon=False, fontsize=8, loc="upper left")
    same_y(axes)
    fig.suptitle(f"Around the patch edges, -5 to +5 units: {MEASURES[measure]} (mean +/- s.e.m. over flies)",
                 fontsize=12, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)


def patch_table(df):
    """Per fly, mean over EFFECT offsets; paired patch 1 vs patch 2 within dataset, phase and edge type."""
    w = df[(df.offset >= EFFECT[0]) & (df.offset <= EFFECT[1])]
    per_fly = w.groupby(["dataset", "fly_id", "phase", "patch", "edge"])[["share", "extra"]].mean().reset_index()
    rows = []
    for (name, phase, edge), g in per_fly.groupby(["dataset", "phase", "edge"]):
        for measure, col in (("plain", "share"), ("baseline", "extra")):
            p = g.pivot(index="fly_id", columns="patch", values=col).dropna()
            if p.empty or "patch 1" not in p or "patch 2" not in p:
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
    df = with_baseline(pd.read_csv(src))
    for measure in MEASURES:
        draw(df, measure, os.path.join(a.dir, f"edge_compare_{measure}.png"))
    tab = patch_table(df)
    tab.to_csv(os.path.join(a.dir, "edge_patch_compare.csv"), index=False)
    print("wrote edge_compare_plain.png, edge_compare_baseline.png, edge_patch_compare.csv in", a.dir)
    show = tab[(tab.measure == "baseline")].round(2)
    print("patch 2 minus patch 1, mean over 0 to +5 units, share minus own baseline (percentage points):")
    print(show.drop(columns="measure").to_string(index=False))


if __name__ == "__main__":
    main()
