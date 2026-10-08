#!/usr/bin/env python3
"""Time spent around the four patch edges: patch 1 and 2, onset (entrance) and offset (exit).

For every fly and phase, the share of trial time spent at each 1-unit step of corridor
position, measured from each edge (patch 1 onset 20, offset 40; patch 2 onset 100, offset
120). Written to ``edge_profiles_by_fly.csv`` and drawn as two figures:

    edge_profiles_by_patch.png   time at each distance from the four edges, training / probing
    edge_accumulation.png        extra time (over each edge's own baseline) added up with distance

The baseline of an edge is the mean share 15 to 9 units before it. Offsets run from -15 to +9
(+ means into the patch at an onset and past the patch at an offset); +10 and beyond would pass
the corridor end at the last edge. Trials that are unreadable or outside 5-900 s are left out.

Run (the stage folder holds the 1D lines, see tools/stage_lines.py):
    python -m selected_analysis.cross_dataset.edges --stage <stage dir> --out runs/summary
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
from ..core import selection
from ..core import trials
T50 = config.T50
T20_100 = config.T20_100
OFFSETS = np.arange(-15, 10)
BASE = (-15, -9)                       # offsets that define each edge's baseline
EDGES = [("patch 1", "onset", 20.0), ("patch 1", "offset", 40.0), ("patch 2", "onset", 100.0), ("patch 2", "offset", 120.0)]
COLORS = {"50/50 (Gr64f)": "#156F76", "20/100 (Gr64f)": "#337AB7", "split line": "#3f7f5f", "OO": "#D46638",
          "GO": "#8A63B8", "GG": "#C4932F", "50/50 no-ATR control": "#8a8a8a"}


def sources(raw, split, stage):
    return [("50/50 (Gr64f)", raw, "applied", T50), ("20/100 (Gr64f)", raw, "applied", T20_100),
            ("split line", split, "recommended", T50), ("OO", f"{stage}/OO", "recommended", T50),
            ("GO", f"{stage}/GO", "recommended", T50), ("GG", f"{stage}/GG", "recommended", T50),
            ("50/50 no-ATR control", raw, "applied", T50 + "_non-atr")]


def fly_profiles(label, root, kind, task):
    """Long table of per-fly time shares for one dataset."""
    rows = []
    for s in selection.iter_selected(root, kind, task):
        for phase in ("training", "probing"):
            hist = {(p, e): np.zeros(len(OFFSETS)) for p, e, _ in EDGES}
            total = 0.0
            for fn in s.kept[phase]:
                path = os.path.join(s.sub_dir, phase, fn)
                if not os.path.isfile(path) or not trials.trial_ok(path):
                    continue
                t, X = trials.load_trajectory(path)
                dt = trials.sample_dt(t)
                total += dt.sum()
                for patch, edge, c in EDGES:
                    bins = np.arange(OFFSETS[0] - 0.5, OFFSETS[-1] + 1.5) + c
                    hist[(patch, edge)] += np.histogram(X, bins=bins, weights=dt)[0]
            if total <= 0:
                continue
            for (patch, edge), h in hist.items():
                for o, v in zip(OFFSETS, h / total * 100):
                    rows.append({"dataset": label, "fly_id": s.fly_id, "phase": phase, "patch": patch,
                                 "edge": edge, "offset": int(o), "share": float(v)})
    return pd.DataFrame(rows)


def summarize(df):
    """Mean and s.e.m. over flies for every dataset x phase x edge x offset."""
    g = df.groupby(["dataset", "phase", "patch", "edge", "offset"]).share
    out = g.agg(["mean", "sem", "count"]).reset_index()
    return out


def same_y(axes, pad=0.04):
    """One y range and one tick step on every panel, so panels can be compared by eye."""
    lo = min(l.get_ydata().min() for ax in axes.flat for l in ax.get_lines() if len(l.get_xdata()) > 2)
    hi = max(l.get_ydata().max() for ax in axes.flat for l in ax.get_lines() if len(l.get_xdata()) > 2)
    step = next(st for st in (1, 2, 5, 10, 20) if (hi - lo) / st <= 8)
    lo0 = 0 if lo >= 0 else np.floor((lo - pad * (hi - lo)) / step) * step
    lo, hi = lo0, np.ceil((hi + pad * (hi - lo)) / step) * step
    for ax in axes.flat:
        ax.set_ylim(lo, hi)
        ax.yaxis.set_major_locator(MultipleLocator(step))


def draw_profiles(sm, out):
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.4), sharex="col")
    for r, phase in enumerate(("training", "probing")):
        for c, (patch, edge, pos) in enumerate(EDGES):
            ax = axes[r, c]
            for name in COLORS:
                d = sm[(sm.dataset == name) & (sm.phase == phase) & (sm.patch == patch) & (sm.edge == edge)]
                if d.empty:
                    continue
                ax.plot(d.offset, d["mean"], color=COLORS[name], lw=2.0 if "no-ATR" not in name else 1.5,
                        ls="-" if "no-ATR" not in name else "--", label=name)
            ax.axvline(0, color="#12303A", lw=1.1)
            ax.axvspan(-5, 5, color="#f3ded5", alpha=0.45, zorder=0)
            if r == 0:
                ax.set_title(f"{patch.capitalize()} {edge}\n({'entrance' if edge == 'onset' else 'exit'}, position {pos:.0f})", fontsize=11, weight="bold")
            if r == 1:
                ax.set_xlabel("Distance from the edge (corridor units)", fontsize=10)
            if c == 0:
                ax.set_ylabel(f"{phase.capitalize()}\nshare of trial time per unit (%)", fontsize=10)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
    axes[0, 0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle("Time spent around the four patch edges (average over flies; shaded = +/-5 units)", fontsize=13, weight="bold")
    same_y(axes)
    fig.tight_layout()
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)


def accumulation(sm):
    """Extra time added up from -15: cumulative sum of (share - the edge's own baseline)."""
    rows = []
    for (name, phase, patch, edge), d in sm.groupby(["dataset", "phase", "patch", "edge"]):
        d = d.sort_values("offset")
        base = d[(d.offset >= BASE[0]) & (d.offset <= BASE[1])]["mean"].mean()
        rows.append(d.assign(extra=np.cumsum(d["mean"].to_numpy() - base)))
    return pd.concat(rows)


def draw_accumulation(sm, out):
    acc = accumulation(sm)
    fig, axes = plt.subplots(2, 4, figsize=(15, 6.4), sharex="col")
    for r, phase in enumerate(("training", "probing")):
        for c, (patch, edge, pos) in enumerate(EDGES):
            ax = axes[r, c]
            for name in COLORS:
                d = acc[(acc.dataset == name) & (acc.phase == phase) & (acc.patch == patch) & (acc.edge == edge)]
                if d.empty:
                    continue
                ax.plot(d.offset, d.extra, color=COLORS[name], lw=2.0 if "no-ATR" not in name else 1.5,
                        ls="-" if "no-ATR" not in name else "--", label=name)
            ax.axhline(0, color="#999999", lw=0.8)
            ax.axvline(0, color="#12303A", lw=1.1)
            ax.axvspan(-5, 5, color="#f3ded5", alpha=0.45, zorder=0)
            if r == 0:
                ax.set_title(f"{patch.capitalize()} {edge}\n({'entrance' if edge == 'onset' else 'exit'}, position {pos:.0f})", fontsize=11, weight="bold")
            if r == 1:
                ax.set_xlabel("Distance from the edge (corridor units)", fontsize=10)
            if c == 0:
                ax.set_ylabel(f"{phase.capitalize()}\nextra time added up (% of trial time)", fontsize=10)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
    axes[0, 0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Extra time added up around the four patch edges (over each edge's baseline 15 to 9 units before it)", fontsize=13, weight="bold")
    same_y(axes)
    fig.tight_layout()
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=config.RAW_ROOT)
    ap.add_argument("--split", default=config.SPLIT_LINE_ROOT)
    ap.add_argument("--stage", default=config.STAGE, help="folder with OO/, GO/, GG/ staged by tools/stage_lines.py")
    ap.add_argument("--out", default=config.SUMMARY)
    ap.add_argument("--redo", action="store_true", help="recompute even if edge_profiles_by_fly.csv exists")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    csv = os.path.join(a.out, "edge_profiles_by_fly.csv")
    if os.path.isfile(csv) and not a.redo:
        df = pd.read_csv(csv)
    else:
        df = pd.concat([fly_profiles(*s) for s in sources(a.raw, a.split, a.stage)], ignore_index=True)
        df.to_csv(csv, index=False)
    sm = summarize(df)
    draw_profiles(sm, os.path.join(a.out, "edge_profiles_by_patch.png"))
    acc = draw_accumulation(sm, os.path.join(a.out, "edge_accumulation.png"))
    print("wrote", csv)
    # extra time accumulated by +5 and by the end of the window, training
    t = acc[(acc.phase == "training") & (acc.offset.isin([5, 9]))].pivot_table(
        index=["dataset", "patch", "edge"], columns="offset", values="extra").round(1)
    print("extra time (% of trial time) accumulated by +5 and +9 units, training:")
    print(t.to_string())


if __name__ == "__main__":
    main()
