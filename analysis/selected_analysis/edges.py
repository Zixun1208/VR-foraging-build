#!/usr/bin/env python3
"""Time spent around the four patch edges: patch 1 and 2, onset (entrance) and offset (exit).

For every fly and phase, the share of trial time spent at each 1-unit step of corridor
position, measured from each edge (patch 1 onset 20, offset 40; patch 2 onset 100, offset
120). Written to ``edge_profiles_by_fly.csv`` and drawn as two figures:

    edge_profiles_by_patch.png   time at each distance from the four edges, training / probing
    edge_accumulation.png        extra time (over each edge's own baseline) added up with distance
    edge_cumulative.png          time added up from 15 units before each edge, no baseline (only rises)
    corridor_cumulative.png      share of trial time spent before each corridor position (from the start)

The baseline of an edge is the mean share 15 to 9 units before it. Offsets run from -15 to +9
(+ means into the patch at an onset and past the patch at an offset); +10 and beyond would pass
the corridor end at the last edge. Trials that are unreadable or outside 5-900 s are left out.

Run (the stage folder holds the 1D lines, see stage_lines.py):
    python edges.py --stage <stage dir> --out runs/summary
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

import selection
import trials

T50 = "foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50"
T20_100 = "foraging_non-iti_130_20-40_100-120_2.5v-0.1v_2.5v-0.1v_20_100"
OFFSETS = np.arange(-15, 10)
CORRIDOR = 130                         # corridor length; positions are binned in 1-unit steps from 0
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
    """Per-fly time shares for one dataset: (around the four edges, along the whole corridor)."""
    rows, crow = [], []
    for s in selection.iter_selected(root, kind, task):
        for phase in ("training", "probing"):
            hist = {(p, e): np.zeros(len(OFFSETS)) for p, e, _ in EDGES}
            chist = np.zeros(CORRIDOR)
            total = 0.0
            for fn in s.kept[phase]:
                path = os.path.join(s.sub_dir, phase, fn)
                if not os.path.isfile(path) or not trials.trial_ok(path):
                    continue
                t, X = trials.load_trajectory(path)
                dt = trials.sample_dt(t)
                total += dt.sum()
                chist += np.histogram(np.clip(X, 0, CORRIDOR - 1e-6), bins=np.arange(CORRIDOR + 1), weights=dt)[0]
                for patch, edge, c in EDGES:
                    bins = np.arange(OFFSETS[0] - 0.5, OFFSETS[-1] + 1.5) + c
                    hist[(patch, edge)] += np.histogram(X, bins=bins, weights=dt)[0]
            if total <= 0:
                continue
            for (patch, edge), h in hist.items():
                for o, v in zip(OFFSETS, h / total * 100):
                    rows.append({"dataset": label, "fly_id": s.fly_id, "phase": phase, "patch": patch,
                                 "edge": edge, "offset": int(o), "share": float(v)})
            for pos, v in enumerate(chist / total * 100):
                crow.append({"dataset": label, "fly_id": s.fly_id, "phase": phase, "position": pos, "share": float(v)})
    return pd.DataFrame(rows), pd.DataFrame(crow)


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


def draw_accumulation(sm, out, plain=False):
    """plain=True: running sum of the share itself (no baseline), so every curve only rises."""
    acc = accumulation(sm)
    if plain:
        acc = sm.sort_values("offset").copy()
        acc["extra"] = acc.groupby(["dataset", "phase", "patch", "edge"])["mean"].cumsum()
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
            if not plain:
                ax.axhline(0, color="#999999", lw=0.8)
            ax.axvline(0, color="#12303A", lw=1.1)
            ax.axvspan(-5, 5, color="#f3ded5", alpha=0.45, zorder=0)
            if r == 0:
                ax.set_title(f"{patch.capitalize()} {edge}\n({'entrance' if edge == 'onset' else 'exit'}, position {pos:.0f})", fontsize=11, weight="bold")
            if r == 1:
                ax.set_xlabel("Distance from the edge (corridor units)", fontsize=10)
            if c == 0:
                ax.set_ylabel(f"{phase.capitalize()}\n{'time added up' if plain else 'extra time added up'} (% of trial time)", fontsize=10)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
    axes[0, 0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Time added up from 15 units before each patch edge" if plain else
                 "Extra time added up around the four patch edges (over each edge's baseline 15 to 9 units before it)", fontsize=13, weight="bold")
    same_y(axes)
    fig.tight_layout()
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)
    return acc


def draw_cumulative(cdf, out):
    """Real accumulation: share of trial time spent before each corridor position, mean over flies."""
    cdf = cdf.sort_values("position").copy()
    cdf["cum"] = cdf.groupby(["dataset", "fly_id", "phase"]).share.cumsum()
    sm = cdf.groupby(["dataset", "phase", "position"]).cum.agg(["mean", "sem"]).reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    for ax, phase in zip(axes, ("training", "probing")):
        for lo, hi in ((20, 40), (100, 120)):
            ax.axvspan(lo, hi, color="#f3ded5", alpha=0.45, zorder=0)
        for _, _, pos in EDGES:
            ax.axvline(pos, color="#12303A", lw=0.9)
        ax.plot([0, CORRIDOR], [0, 100], color="#999999", lw=1.0, ls=":", label="even pace (same time per unit)")
        for name in COLORS:
            d = sm[(sm.dataset == name) & (sm.phase == phase)]
            if d.empty:
                continue
            x = d.position + 1                       # bin k covers positions k to k+1; cumulative is at its right edge
            ax.plot(np.r_[0, x], np.r_[0, d["mean"]], color=COLORS[name], lw=2.0 if "no-ATR" not in name else 1.5,
                    ls="-" if "no-ATR" not in name else "--", label=name)
        ax.set_title(phase.capitalize(), fontsize=12, weight="bold")
        ax.set_xlabel("Corridor position (shaded = patches)", fontsize=10)
        ax.set_xlim(0, CORRIDOR)
        ax.set_ylim(0, 100)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("Share of trial time spent before this position (%)", fontsize=10)
    axes[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle("Time added up along the corridor (average over flies)", fontsize=13, weight="bold")
    fig.tight_layout()
    fig.savefig(out, dpi=170, facecolor="white")
    plt.close(fig)
    return sm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.expanduser("~/Raw_data"))
    ap.add_argument("--split", default=os.path.expanduser("~/Raw_data_by_task/split line"))
    ap.add_argument("--stage", required=True, help="folder with OO/, GO/, GG/ staged by stage_lines.py")
    ap.add_argument("--out", default="runs/summary")
    ap.add_argument("--redo", action="store_true", help="recompute even if edge_profiles_by_fly.csv exists")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    csv = os.path.join(a.out, "edge_profiles_by_fly.csv")
    ccsv = os.path.join(a.out, "corridor_profile_by_fly.csv")
    if os.path.isfile(csv) and os.path.isfile(ccsv) and not a.redo:
        df, cdf = pd.read_csv(csv), pd.read_csv(ccsv)
    else:
        parts = [fly_profiles(*s) for s in sources(a.raw, a.split, a.stage)]
        df = pd.concat([p[0] for p in parts], ignore_index=True)
        cdf = pd.concat([p[1] for p in parts], ignore_index=True)
        df.to_csv(csv, index=False)
        cdf.to_csv(ccsv, index=False)
    sm = summarize(df)
    draw_profiles(sm, os.path.join(a.out, "edge_profiles_by_patch.png"))
    acc = draw_accumulation(sm, os.path.join(a.out, "edge_accumulation.png"))
    plain = draw_accumulation(sm, os.path.join(a.out, "edge_cumulative.png"), plain=True)
    t = plain[(plain.phase == "training") & (plain.offset.isin([-1, 5, 9]))].pivot_table(
        index=["dataset", "patch", "edge"], columns="offset", values="extra").round(1)
    print("time (% of trial) added up from -15 to -1, +5, +9, training:")
    print(t.to_string())
    draw_cumulative(cdf, os.path.join(a.out, "corridor_cumulative.png"))
    print("wrote", csv, ccsv)
    # extra time accumulated by +5 and by the end of the window, training
    t = acc[(acc.phase == "training") & (acc.offset.isin([5, 9]))].pivot_table(
        index=["dataset", "patch", "edge"], columns="offset", values="extra").round(1)
    print("extra time (% of trial time) accumulated by +5 and +9 units, training:")
    print(t.to_string())


if __name__ == "__main__":
    main()
