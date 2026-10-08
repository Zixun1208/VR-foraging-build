#!/usr/bin/env python3
"""Per-fly leave-rule test on any survival table: which variable is invariant across patches?

For each fly, take the median giving-up point (elapsed time, LED value, fraction of start)
in each patch, then the across-patch spread |p1-p2| / mean of each. The variable with the
smallest spread is the one the fly leaves by. Works on the output of
build_survival_selected.py or the original data/survival*.csv.

Writes ``<out>/leave_rule_<tag>.csv`` (one row per fly) and ``leave_rule_<tag>.png``.

Run:
    python selected_analysis/leave_rule.py selected_analysis/data/survival_50_50.csv
    python selected_analysis/leave_rule.py data/survival_20_100.csv --min-leaves 3
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

VARS = {"elapsed_sec": "time", "value_frac": "fraction", "value_volts": "value"}
COLORS = {"time": "#156f76", "fraction": "#d46638", "value": "#8a63b8"}


def giving_up(df: pd.DataFrame) -> pd.DataFrame:
    """One row per completed training visit: the variables at the leave bin."""
    d = df[(df.phase == "training") & (df.qc_ok == 1) & (df.left == 1)]
    return d.dropna(subset=list(VARS))


def per_fly(df: pd.DataFrame, min_leaves: int = 3) -> pd.DataFrame:
    g = giving_up(df)
    med = g.groupby(["fly_id", "patch"])[list(VARS)].median()
    n = g.groupby(["fly_id", "patch"]).size().unstack()
    rows = []
    for fly, sub in med.groupby(level=0):
        sub = sub.droplevel(0)
        if not {0, 1} <= set(sub.index):
            continue
        if n.loc[fly, 0] < min_leaves or n.loc[fly, 1] < min_leaves:
            continue
        row = {"fly_id": fly, "n_p1": int(n.loc[fly, 0]), "n_p2": int(n.loc[fly, 1])}
        for col, name in VARS.items():
            a, b = sub.loc[0, col], sub.loc[1, col]
            row[f"{name}_p1"], row[f"{name}_p2"] = a, b
            row[f"{name}_spread"] = abs(a - b) / ((a + b) / 2)
        spreads = {nm: row[f"{nm}_spread"] for nm in VARS.values()}
        row["best"] = min(spreads, key=spreads.get)
        rows.append(row)
    return pd.DataFrame(rows)


def plot(res: pd.DataFrame, out: str, title: str) -> None:
    fig, ax = plt.subplots(figsize=(5.2, 4))
    names = list(VARS.values())
    for _, r in res.iterrows():
        ax.plot(range(3), [r[f"{n}_spread"] for n in names], color="#b8c2c0", lw=0.8, zorder=1)
    for i, n in enumerate(names):
        ax.scatter(np.full(len(res), i), res[f"{n}_spread"], color=COLORS[n], s=22, zorder=2)
    ax.plot(range(3), [res[f"{n}_spread"].median() for n in names], color="k", lw=2, zorder=3)
    ax.set_xticks(range(3), ["time in\npatch", "fraction of\nstart reward", "reward\nvalue"])
    ax.set_ylabel("difference between the two patches\n|patch 1 - patch 2| / average")
    ax.set_title(f"{(res.best == 'time').sum()}/{len(res)} flies most similar in time between patches",
                 fontsize=10)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_boxes(df: pd.DataFrame, out: str, min_leaves: int = 5) -> bool:
    """The poster's per-fly view: spread of each quantity across the two patches, as box plots."""
    res = per_fly(df, min_leaves)
    if len(res) < 3:
        return False
    names = list(VARS.values())
    data = [res[f"{n}_spread"].to_numpy() for n in names]
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    box = ax.boxplot(data, patch_artist=True, showfliers=False, widths=0.58)
    for patch, n in zip(box["boxes"], names):
        patch.set_facecolor(COLORS[n])
        patch.set_alpha(0.32)
        patch.set_edgecolor("#1b2a2f")
        patch.set_linewidth(1.5)
    for med in box["medians"]:
        med.set_color("#1b2a2f")
        med.set_linewidth(2.2)
    for i, vals in enumerate(data, start=1):
        ax.scatter(np.full(len(vals), i) + np.linspace(-0.14, 0.14, len(vals)), vals, s=40,
                   color="#1b2a2f", alpha=0.68, zorder=3)
    ax.set_xticks([1, 2, 3], ["time in\npatch", "fraction of\nstart reward", "reward\nvalue"])
    ax.set_ylabel("difference between the two patches\n|patch 1 - patch 2| / average")
    ax.set_ylim(0, max(max(d) for d in data) * 1.18)
    ax.set_title(f"Within each fly, which quantity matches across the two patches? (n = {len(res)} flies)",
                 fontsize=10, weight="bold", pad=12)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return True


def run(csv_path: str, out: str, min_leaves: int = 3, name: str | None = None):
    """Write ``<name>.csv`` / ``<name>.png`` under ``out``; return the per-fly table or None.

    ``name`` defaults to ``leave_rule_<csv stem without 'survival_'>``.
    """
    res = per_fly(pd.read_csv(csv_path), min_leaves)
    if res.empty:
        return None
    tag = os.path.splitext(os.path.basename(csv_path))[0].replace("survival_", "")
    name = name or f"leave_rule_{tag}"
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, f"{name}.csv"), index=False)
    plot(res, os.path.join(out, f"{name}.png"), tag)
    plot_boxes(pd.read_csv(csv_path), os.path.join(out, f"{name}_boxes.png"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--min-leaves", type=int, default=3,
                    help="min completed visits per patch for a fly to count (default 3)")
    ap.add_argument("--out", default=os.path.join(config.RUNS, "leave_rule"))
    a = ap.parse_args()

    res = run(a.csv, a.out, a.min_leaves)
    if res is None:
        raise SystemExit("no fly has enough completed visits in both patches")
    print(f"{len(res)} flies; median spread " + ", ".join(
        f"{n} {res[f'{n}_spread'].median():.2f}" for n in VARS.values()))
    print("most consistent variable per fly:", res.best.value_counts().to_dict())


if __name__ == "__main__":
    main()
