#!/usr/bin/env python3
"""Inside a patch: is the fly walking back and forth, or going straight through?

Each trial is cut into patch visits (contiguous stretches with X inside the patch band). For
every visit: time in the patch, net forward distance, total path length, mean speed
(path length / time), backward share of the path, and the number of direction reversals
(turning points whose swing is at least ``--min-swing`` units, so jitter is ignored).

Written to ``patch_visits.csv`` (one row per visit) and drawn as

    patch_trajectory_examples.png   X against time inside the patch, a few visits per dataset
    patch_trajectory_metrics.png    per-fly means of the visit metrics, by dataset and patch

Run (same folders as edges.py):
    python patch_trajectory.py --stage <stage dir> --out runs/summary [--phase training] [--patch 1]
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import selection
import trials
from edges import COLORS, sources

PATCHES = {"patch 1": (20.0, 40.0), "patch 2": (100.0, 120.0)}
SMOOTH = 5            # samples in the moving average before looking for turning points


def reversals(x, min_swing):
    """Number of direction changes whose swing (turning point to turning point) is >= min_swing."""
    if len(x) < 3:
        return 0
    k = min(SMOOTH, len(x))
    xs = np.convolve(x, np.ones(k) / k, mode="valid")
    # turning points: extrema of the smoothed trace, kept only if the swing since the last one is big enough
    d = np.sign(np.diff(xs))
    d = d[d != 0]
    if d.size < 2:
        return 0
    idx = np.flatnonzero(np.diff(d) != 0)          # positions in the nonzero-diff list; map back to xs
    nz = np.flatnonzero(np.diff(xs) != 0)
    pts = [xs[0]] + [xs[nz[i] + 1] for i in idx] + [xs[-1]]
    n, last = 0, pts[0]
    for p in pts[1:-1]:
        if abs(p - last) >= min_swing:
            n += 1
            last = p
    return max(n, 0)


def visits(t, X, lo, hi, min_swing):
    """Yield one dict per contiguous in-band stretch of a trial, plus its (t, X) for plotting."""
    dt = trials.sample_dt(t)
    inb = (X >= lo) & (X <= hi)
    edges = np.flatnonzero(np.diff(np.r_[0, inb.astype(int), 0]))
    for a, b in zip(edges[::2], edges[1::2]):
        if b - a < 3:
            continue
        x, tt = X[a:b], t[a:b]
        step = np.diff(x)
        dur = float(dt[a:b].sum())
        path = float(np.abs(step).sum())
        back = float(-step[step < 0].sum())
        yield dict(dur=dur, net=float(x[-1] - x[0]), path=path, speed=path / dur if dur > 0 else np.nan,
                   back_share=back / path if path > 0 else 0.0, reversals=reversals(x, min_swing),
                   entered_from=float(X[a - 1]) if a > 0 else np.nan), (tt - tt[0], x)


def collect(a):
    rows, ex = [], {}
    rng = np.random.default_rng(0)
    for label, root, kind, task in sources(a.raw, a.split, a.stage):
        for s in selection.iter_selected(root, kind, task):
            for fn in s.kept[a.phase]:
                path = os.path.join(s.sub_dir, a.phase, fn)
                if not os.path.isfile(path) or not trials.trial_ok(path):
                    continue
                t, X = trials.load_trajectory(path)
                for patch, (lo, hi) in PATCHES.items():
                    for v, tr in visits(t, X, lo, hi, a.min_swing):
                        rows.append({"dataset": label, "fly_id": s.fly_id, "patch": patch, "trial": fn, **v})
                        if patch == a.example_patch:
                            ex.setdefault(label, []).append(tr)
    df = pd.DataFrame(rows)
    ex = {k: [v[i] for i in rng.permutation(len(v))[:a.n_examples]] for k, v in ex.items()}
    return df, ex


def draw_examples(ex, patch, out):
    lo, hi = PATCHES[patch]
    labels = list(ex)
    fig, axes = plt.subplots(1, len(labels), figsize=(2.6 * len(labels), 3.6), sharey=True, squeeze=False)
    for ax, lab in zip(axes[0], labels):
        for tt, x in ex[lab]:
            ax.plot(tt, x, lw=0.9, alpha=0.8, color=COLORS.get(lab, "k"))
        ax.axhline(lo, color="0.6", lw=0.6)
        ax.axhline(hi, color="0.6", lw=0.6)
        ax.set_title(lab, fontsize=8)
        ax.set_xlabel("s since entering")
    axes[0][0].set_ylabel(f"X inside {patch}")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def draw_metrics(df, out):
    cols = [("dur", "time in patch (s)"), ("speed", "path length / time (units/s)"),
            ("path", "path length (units)"), ("back_share", "backward share of path"),
            ("reversals", "reversals per visit")]
    fly = df.groupby(["dataset", "patch", "fly_id"])[[c for c, _ in cols]].mean().reset_index()
    order = [d for d in COLORS if d in set(df.dataset)]
    fig, axes = plt.subplots(2, len(cols), figsize=(3 * len(cols), 6), squeeze=False)
    for r, patch in enumerate(PATCHES):
        for ax, (c, title) in zip(axes[r], cols):
            for i, d in enumerate(order):
                v = fly[(fly.dataset == d) & (fly.patch == patch)][c].dropna()
                ax.scatter(np.full(len(v), i) + np.random.default_rng(i).uniform(-.15, .15, len(v)), v, s=6,
                           color=COLORS[d], alpha=.5)
                ax.plot([i - .3, i + .3], [v.mean()] * 2, color="k", lw=1.5)
            ax.set_xticks(range(len(order)))
            ax.set_xticklabels(order, rotation=60, ha="right", fontsize=6)
            ax.set_title(f"{patch}: {title}", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.expanduser("~/Raw_data"))
    ap.add_argument("--split", default=os.path.expanduser("~/Raw_data_by_task/split line"))
    ap.add_argument("--stage", required=True)
    ap.add_argument("--out", default="runs/summary")
    ap.add_argument("--phase", default="training", choices=["training", "probing"])
    ap.add_argument("--min-swing", type=float, default=2.0, help="smallest back-and-forth swing counted (units)")
    ap.add_argument("--example-patch", default="patch 1", choices=list(PATCHES))
    ap.add_argument("--n-examples", type=int, default=12)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    df, ex = collect(a)
    df.to_csv(os.path.join(a.out, "patch_visits.csv"), index=False)
    draw_examples(ex, a.example_patch, os.path.join(a.out, "patch_trajectory_examples.png"))
    draw_metrics(df, os.path.join(a.out, "patch_trajectory_metrics.png"))
    fly = df.groupby(["dataset", "patch", "fly_id"])[["dur", "speed", "path", "net", "back_share", "reversals"]].mean()
    print(fly.groupby(["dataset", "patch"]).mean().round(2).to_string())


if __name__ == "__main__":
    main()
