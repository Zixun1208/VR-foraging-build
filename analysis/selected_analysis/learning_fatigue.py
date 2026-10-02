#!/usr/bin/env python3
"""Does patch dwell change over a session, and is it fatigue or learning?

Plan: ../learning_fatigue/README.md. Reads the survival table for per-visit dwell and the
selected trial CSVs for locomotion, then fits one slope per fly against session position.

Per trial (``trials.csv``): dwell in each patch (survival table), mean speed, moving
fraction, longest stall, and speed on the stretch between the patches. Per fly, phase and
patch (``slopes.csv``): OLS slope of each metric against trial index within the phase, plus
a slope relative to the fly's median. ``summary.csv`` tests the slopes across flies with the
exact paired sign-flip test from figures.py (Holm over all rows; ``p_rank`` is the outlier-robust signed-rank version), and tests the
training-minus-probing slope difference. ``baseline_reference.csv`` gives each fly's
baseline / open-loop walking next to its first and last training trials.

Reading the result: a fall equal in training and probing, with speed and moving fraction
falling too, points to fatigue; a fall only in training, or with faster inter-patch
traversal, points to learning about the reward. Output only suggests -- it does not decide.

Run:
    python learning_fatigue.py --raw-root ~/Raw_data_by_task/"split line" \
        --task <task folder> --survival runs/split_line/50_50/survival.csv --out <dir>
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import figures
import selection
import trials
from figures import COLORS, INK, PHASES, signflip_p, stars, style

GRID_DT = 0.25          # s, resampling grid for speed
MOVE_SPEED = 0.5        # corridor units/s; below this the fly counts as stalled
METRICS = ("dwell", "speed", "moving_frac", "longest_stall", "traverse_speed")
LABELS = {"dwell": "Time spent in patch (s)", "speed": "Mean speed (units/s)",
          "moving_frac": "Moving fraction", "longest_stall": "Longest stall (s)",
          "traverse_speed": "Speed between patches (units/s)"}
MIN_TRIALS = 8          # trials with a value before a fly gets a slope


def locomotion(path, corridor, gap=None):
    """Speed summary of one trial CSV, or None if unreadable.

    ``gap`` = (lo, hi) corridor stretch for ``traverse_speed``.
    """
    a = figures.load_cam(path)
    if a is None:
        return None
    t, x = a[:, 0] / 1000.0, a[:, 1]
    keep = np.concatenate(([True], np.diff(t) > 0))
    t, x = t[keep], x[keep]
    if len(t) < 3 or t[-1] - t[0] < 2 * GRID_DT:
        return None
    x = np.unwrap(x, period=corridor)
    g = np.arange(t[0], t[-1], GRID_DT)
    xg = np.interp(g, t, x)
    sp = np.abs(np.diff(xg)) / GRID_DT
    moving = sp >= MOVE_SPEED
    stall = run = 0
    for m in moving:
        run = 0 if m else run + 1
        stall = max(stall, run)
    out = {"duration": float(t[-1] - t[0]), "speed": float(sp.mean()),
           "moving_frac": float(moving.mean()), "longest_stall": stall * GRID_DT,
           "traverse_speed": float("nan")}
    if gap:
        pos = np.mod(xg[:-1], corridor)
        inside = (pos >= gap[0]) & (pos < gap[1])
        if inside.sum() >= 2:
            out["traverse_speed"] = float(sp[inside].mean())
    return out


def trial_table(ctx, surv):
    """One row per selected trial with dwell and locomotion metrics."""
    dwell = surv.assign(dwell=surv.groupby("visit_id").t_bin.transform("max")) \
        .drop_duplicates("visit_id").set_index(["fly_id", "trial_order", "patch"]).dwell
    gap = (ctx.bands[0][1], ctx.bands[1][0])
    rows = []
    for s in ctx.sessions:
        # same ordering build_survival uses: both phases interleaved by timestamp
        files = sorted((trials.parse_fname(p)["ts"], ph, p)
                       for ph in PHASES for p in ctx.paths(s, ph))
        rank = {ph: 0 for ph in PHASES}
        for order, (_, ph, p) in enumerate(files):
            row = {"fly_id": s.fly_id, "phase": ph, "trial_order": order,
                   "phase_index": rank[ph]}
            rank[ph] += 1
            d1, d2 = (dwell.get((s.fly_id, order, k), np.nan) for k in (0, 1))
            row["dwell_p1"], row["dwell_p2"] = d1, d2
            row["dwell"] = np.nan if np.isnan(d1) and np.isnan(d2) else np.nanmean([d1, d2])
            loc = locomotion(p, ctx.corridor, gap)
            row.update(loc or {m: np.nan for m in METRICS[1:]})
            rows.append(row)
    return pd.DataFrame(rows)


def slope(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < MIN_TRIALS or np.ptp(x[ok]) == 0:
        return np.nan, int(ok.sum())
    return float(np.polyfit(x[ok], y[ok], 1)[0]), int(ok.sum())


def slope_table(tt):
    """Per fly x phase x metric(/patch) slope against trial index within the phase."""
    series = [("dwell", "both", "dwell"), ("dwell", "p1", "dwell_p1"),
              ("dwell", "p2", "dwell_p2")] + [(m, "all", m) for m in METRICS[1:]]
    rows = []
    for (fly, ph), g in tt.groupby(["fly_id", "phase"]):
        x = g.phase_index.to_numpy(float)
        for metric, patch, col in series:
            y = g[col].to_numpy(float)
            b, n = slope(x, y)
            med = np.nanmedian(y) if n else np.nan
            rows.append({"fly_id": fly, "phase": ph, "metric": metric, "patch": patch,
                         "slope": b, "rel_slope": b / med if med else np.nan, "n_trials": n})
    return pd.DataFrame(rows)


def signed_ranks(d):
    """sign(d) * rank(|d|): sign-flip on these is the exact signed-rank test, outlier-robust."""
    d = np.asarray(d, float)
    return np.sign(d) * pd.Series(np.abs(d)).rank().to_numpy()


def summarize(sl):
    """Across-fly tests: slope != 0 per phase, and training minus probing."""
    rows = []
    for (metric, patch), g in sl.groupby(["metric", "patch"], sort=False):
        w = g.pivot(index="fly_id", columns="phase", values="slope")
        tests = {ph: w[ph].dropna() for ph in PHASES if ph in w}
        if set(PHASES) <= set(w):
            tests["training-probing"] = (w.training - w.probing).dropna()
        for test, d in tests.items():
            if len(d) >= 3:
                rows.append({"metric": metric, "patch": patch, "test": test,
                             "n_flies": len(d), "mean_slope": d.mean(),
                             "median_slope": d.median(), "n_negative": int((d < 0).sum()),
                             "p": signflip_p(d), "p_rank": signflip_p(signed_ranks(d))})
    s = pd.DataFrame(rows)
    if s.empty:
        return s
    srt = s.p.sort_values(kind="stable")                # Holm step-down over every row
    adj = (srt * (len(s) - np.arange(len(s)))).cummax().clip(upper=1)
    s["p_holm"] = adj.reindex(s.index)
    srt = s.p_rank.sort_values(kind="stable")
    adj = (srt * (len(s) - np.arange(len(s)))).cummax().clip(upper=1)
    s["p_rank_holm"] = adj.reindex(s.index)
    return s


def baseline_table(ctx, tt):
    """Baseline / open-loop walking next to each fly's first and last 10 training trials."""
    gap = (ctx.bands[0][1], ctx.bands[1][0])
    stats = ("speed", "moving_frac", "longest_stall")
    rows = []
    for s in ctx.sessions:
        row = {"fly_id": s.fly_id}
        for sub in ("baseline", "openloop_training"):
            d = os.path.join(s.sub_dir, sub)
            res = [r for r in (locomotion(os.path.join(d, f), ctx.corridor, gap)
                               for f in sorted(os.listdir(d)) if f.endswith(".csv")) if r] \
                if os.path.isdir(d) else []
            for m in stats:
                row[f"{sub}_{m}"] = np.mean([r[m] for r in res]) if res else np.nan
        g = tt[(tt.fly_id == s.fly_id) & (tt.phase == "training")].sort_values("phase_index")
        for lab, part in (("first10", g.head(10)), ("last10", g.tail(10))):
            for m in stats:
                row[f"training_{lab}_{m}"] = part[m].mean()
        rows.append(row)
    return pd.DataFrame(rows)


# ---- figures ------------------------------------------------------------------------------
def fig_over_session(ctx, tt, metrics, name):
    fig, axes = plt.subplots(len(metrics), 2, figsize=(9.4, 2.9 * len(metrics)),
                             sharex=True, squeeze=False)
    for i, m in enumerate(metrics):
        for ax, ph in zip(axes[i], PHASES):
            piv = tt[tt.phase == ph].pivot(index="phase_index", columns="fly_id", values=m)
            sm = piv.rolling(5, center=True, min_periods=2).mean()
            ax.plot(sm.index, sm.to_numpy(), color=COLORS[ph], lw=0.8, alpha=0.35)
            ax.plot(sm.index, sm.mean(axis=1), color=COLORS[ph], lw=3)
            style(ax)
            if i == 0:
                ax.set_title(ph.capitalize(), color=COLORS[ph], weight="bold")
            if ax is axes[i][0]:
                ax.set_ylabel(LABELS[m], fontsize=11)
    for ax in axes[-1]:
        ax.set_xlabel("Trial index within phase", fontsize=12)
    fig.suptitle("thin: fly (5-trial running mean)   bold: mean across flies", fontsize=10,
                 color=INK)
    fig.tight_layout()
    ctx.save(fig, name)


def fig_slope_compare(ctx, sl, summ):
    """Training vs probing slope per fly (paired), one panel per metric."""
    panels = [("dwell", "both"), ("speed", "all"), ("moving_frac", "all"),
              ("longest_stall", "all")]
    fig, axes = plt.subplots(1, len(panels), figsize=(3.0 * len(panels), 3.6))
    for ax, (m, patch) in zip(axes, panels):
        w = sl[(sl.metric == m) & (sl.patch == patch)].pivot(
            index="fly_id", columns="phase", values="slope").dropna()
        for _, r in w.iterrows():
            ax.plot([0, 1], [r.training, r.probing], color="#b8c2c0", lw=0.9, zorder=1)
        for j, ph in enumerate(PHASES):
            ax.scatter(np.full(len(w), j), w[ph], color=COLORS[ph], s=28, zorder=2)
        ax.plot([0, 1], [w.training.mean(), w.probing.mean()], color="k", lw=2.4, zorder=3)
        ax.axhline(0, color=INK, lw=1, ls="--")
        row = summ[(summ.metric == m) & (summ.patch == patch) &
                   (summ.test == "training-probing")]
        if len(row):
            ax.set_title(f"{m}\ndiff p={row.p.iloc[0]:.3f} {stars(row.p.iloc[0])}", fontsize=10)
        ax.set_xticks([0, 1], ["train", "probe"])
        ax.set_xlim(-0.4, 1.4)
        style(ax, 11)
    axes[0].set_ylabel("Slope per trial", fontsize=12)
    fig.tight_layout()
    ctx.save(fig, "slope_training_vs_probing.png")


def fig_baseline(ctx, ref):
    cols = [("baseline_moving_frac", "baseline"), ("training_first10_moving_frac", "first 10"),
            ("training_last10_moving_frac", "last 10")]
    y = ref[[c for c, _ in cols]].to_numpy(float)
    if np.isnan(y).all():
        return
    fig, ax = plt.subplots(figsize=(4.4, 3.8))
    x = np.arange(len(cols))
    for r in y:
        ax.plot(x, r, color="#b8c2c0", lw=0.9, zorder=1)
    ax.scatter(np.tile(x, (len(y), 1)), y, color=COLORS["training"], s=26, zorder=2)
    ax.plot(x, np.nanmean(y, axis=0), color="k", lw=2.4, zorder=3)
    ax.set_xticks(x, [lab for _, lab in cols])
    ax.set_ylabel("Moving fraction", fontsize=12)
    ax.set_title("Walking without reward vs training trials", fontsize=10)
    style(ax, 11)
    ctx.save(fig, "baseline_vs_training.png")


def run(raw_root, task, kind, survival_csv, out):
    """Write tables and figures under ``out``; False if the task has no ATR sessions."""
    ctx = figures.Ctx(raw_root, task, kind, out)
    if not ctx.sessions:
        return False
    tt = trial_table(ctx, pd.read_csv(survival_csv))
    sl = slope_table(tt)
    summ = summarize(sl)
    ref = baseline_table(ctx, tt)
    for name, df in (("trials", tt), ("slopes", sl), ("summary", summ),
                     ("baseline_reference", ref)):
        df.to_csv(os.path.join(out, f"{name}.csv"), index=False)
    fig_over_session(ctx, tt, ["dwell"], "dwell_over_session.png")
    fig_over_session(ctx, tt, ["speed", "moving_frac", "longest_stall"],
                     "locomotion_over_session.png")
    if not summ.empty:
        fig_slope_compare(ctx, sl, summ)
        print(summ[summ.patch.isin(["both", "all"])]
              [["metric", "test", "n_flies", "mean_slope", "n_negative", "p", "p_rank", "p_rank_holm"]]
              .round(4).to_string(index=False))
    fig_baseline(ctx, ref)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-root", default=selection.RAW_ROOT)
    ap.add_argument("--task", required=True)
    ap.add_argument("--selection", choices=("recommended", "applied"), default="recommended")
    ap.add_argument("--survival", required=True, help="csv from build_survival.py")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not run(a.raw_root, a.task, a.selection, a.survival, a.out):
        raise SystemExit("no selected ATR sessions")


if __name__ == "__main__":
    main()
