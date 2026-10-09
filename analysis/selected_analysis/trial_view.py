#!/usr/bin/env python3
"""Look at whole trials: corridor position X against time, patches shaded, in-patch time in colour.

One panel per trial (a grid), taken from one dataset and one fly, so the walking pattern can be
read directly: straight runs, stops, turns back. The corner note gives trial length.

Run:
    python trial_view.py --stage <stage dir> --dataset "split line" [--fly <id>] [--n 12] [--phase training]
    python trial_view.py --stage <stage dir> --list      # datasets and flies with trial counts
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import selection
import trials
from edges import COLORS, sources
from patch_trajectory import PATCHES


def find(a):
    """{(dataset, fly_id): [paths]} for the chosen phase."""
    out = {}
    for label, root, kind, task in sources(a.raw, a.split, a.stage):
        for s in selection.iter_selected(root, kind, task):
            for fn in sorted(s.kept[a.phase]):
                p = os.path.join(s.sub_dir, a.phase, fn)
                if os.path.isfile(p):
                    out.setdefault((label, s.fly_id), []).append(p)
    return out


def draw(paths, title, out, cols=3):
    rows = int(np.ceil(len(paths) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5.2 * cols, 3.0 * rows), squeeze=False)
    for ax in axes.ravel():
        ax.axis("off")
    for ax, p in zip(axes.ravel(), paths):
        ax.axis("on")
        t, X = trials.load_trajectory(p)
        for lo, hi in PATCHES.values():
            ax.axhspan(lo, hi, color="#f2d98c", alpha=0.35, lw=0)
        ax.plot(t, X, color="0.55", lw=0.8)
        inb = np.zeros(len(X), bool)
        for lo, hi in PATCHES.values():
            inb |= (X >= lo) & (X <= hi)
        ax.plot(t, np.where(inb, X, np.nan), color="#3f7f5f", lw=1.3)
        ax.set_ylim(0, 130)
        ax.set_title(os.path.basename(p).replace(".csv", "")[:48], fontsize=6)
        ax.set_xlabel("s", fontsize=7)
        ax.set_ylabel("X", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.text(0.99, 0.03, f"{t[-1]:.0f}s", transform=ax.transAxes,
                ha="right", fontsize=6, color="0.3")
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.expanduser("~/Raw_data"))
    ap.add_argument("--split", default=os.path.expanduser("~/Raw_data_by_task/split line"))
    ap.add_argument("--stage", required=True)
    ap.add_argument("--out", default="runs/summary")
    ap.add_argument("--phase", default="training", choices=["training", "probing"])
    ap.add_argument("--dataset", default="split line", choices=list(COLORS))
    ap.add_argument("--fly", default=None)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--png", default=None, help="output file name (default trial_view_<dataset>_<fly>.png)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    found = find(a)
    if a.list:
        for (d, f), ps in sorted(found.items()):
            print(f"{d:24s} {f:20s} {len(ps)} trials")
        return
    cand = {k: v for k, v in found.items() if k[0] == a.dataset and (a.fly is None or str(k[1]) == a.fly)}
    if not cand:
        raise SystemExit("no trials for that dataset/fly; try --list")
    (d, f), ps = max(cand.items(), key=lambda kv: len(kv[1]))
    ps = [p for p in ps if trials.trial_ok(p)]
    idx = np.linspace(0, len(ps) - 1, min(a.n, len(ps))).astype(int)      # spread over the session
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, a.png or f"trial_view_{d.replace(' ', '_').replace('/', '-')}_{f}.png")
    draw([ps[i] for i in idx], f"{d}, fly {f}, {a.phase} ({len(idx)} of {len(ps)} trials; shaded = patches)", out)
    print("wrote", out)


if __name__ == "__main__":
    main()
