#!/usr/bin/env python3
"""Walking speed from the FicTrac ball, checked against the speed from the logged Unity X.

Why: the Unity camera log can have timing/teleport problems; the ball is measured on its own
clock. FicTrac gives the ball's rotation per video frame (lab frame, rad): x and y are the
rolling directions (forward / sideways), z is yaw. Translational speed is therefore
sqrt(dx^2 + dy^2) / dt, in rad/s (x ball radius for mm/s). The same ms clock (column 24 of the
.dat) is used by the trial CSVs, so a trial's window is cut straight from the FicTrac time axis.

For noise, rotations are summed in ``--bin`` second bins before the speed is taken; otherwise
per-frame jitter inflates the mean.

Written to ``fictrac_speed_trials.csv`` (one row per trial: FicTrac speed, camera speed,
coverage) and drawn as ``fictrac_speed_vs_camera.png`` (per-trial scatter, per-fly means) plus a
printed table: correlation, rad/s per corridor unit, and flies whose speed rises from the first
to the last third of training by each measure.

Run:
    python -m selected_analysis.cross_dataset.fictrac_speed --out runs/summary [--bin 0.1]
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
from ..core import selection
from ..core import trials
from .edges import COLORS, sources

COVERAGE_MIN = 0.9      # share of the trial window that must have FicTrac frames


def load_ball(sub_dir):
    """(time_ms, d_roll_x, d_roll_y) per FicTrac frame, sorted by time, or None."""
    dats = sorted(f for f in os.listdir(sub_dir) if f.startswith("fictrac-") and f.endswith(".dat"))
    if not dats:
        return None
    try:
        raw = pd.read_csv(os.path.join(sub_dir, dats[0]), header=None, usecols=[5, 6, 24]).to_numpy(float)
    except (OSError, ValueError):
        return None
    raw = raw[np.isfinite(raw).all(1)]
    order = np.argsort(raw[:, 2], kind="stable")
    raw = raw[order]
    return raw[:, 2], raw[:, 0], raw[:, 1]


def ball_speed(ball, t0, t1, bin_s):
    """Mean translational ball speed (rad/s) between t0 and t1 (ms) and the share of the window covered."""
    tm, dx, dy = ball
    lo, hi = np.searchsorted(tm, [t0, t1])
    if hi - lo < 3:
        return np.nan, 0.0
    t, x, y = tm[lo:hi], dx[lo:hi], dy[lo:hi]
    edges = np.arange(t[0], t[-1] + bin_s * 1000, bin_s * 1000)
    idx = np.digitize(t, edges) - 1
    n = idx.max() + 1
    sx, sy = np.bincount(idx, x, n), np.bincount(idx, y, n)
    cnt = np.bincount(idx, minlength=n)
    full = cnt > 0
    speed = np.hypot(sx, sy)[full] / bin_s
    covered = (t[-1] - t[0]) / max(t1 - t0, 1e-9)
    return float(speed.mean()), float(covered)


def camera_speed(path):
    """Mean |dX|/dt over a trial (units/s), skipping gaps and wrap-arounds, or None."""
    traj = trials.load_trajectory(path)
    if traj is None:
        return None
    t, X = traj
    dt, dX = np.diff(t), np.abs(np.diff(X))
    ok = (dt > 0) & (dt < trials.MAX_GAP_SEC) & (dX < 65)
    return float(dX[ok].sum() / dt[ok].sum()) if ok.any() and dt[ok].sum() > 0 else None


def collect(args):
    rows = []
    for label, root, kind, task in sources(args.raw, args.split, args.stage):
        for s in selection.iter_selected(root, kind, task):
            ball = load_ball(s.sub_dir)
            if ball is None:
                print(f"  [skip] {label} {s.fly_id}: no FicTrac .dat")
                continue
            for phase in ("training", "probing"):
                for k, fn in enumerate(s.kept[phase]):
                    path = os.path.join(s.sub_dir, phase, fn)
                    if not os.path.isfile(path) or not trials.trial_ok(path):
                        continue
                    a = np.genfromtxt(path, delimiter=",", skip_header=1, usecols=(0,), invalid_raise=False)
                    a = np.atleast_1d(a)
                    a = a[np.isfinite(a)]
                    if len(a) < 3:
                        continue
                    fic, cov = ball_speed(ball, a[0], a[-1], args.bin)
                    rows.append(dict(dataset=label, fly=s.fly_id, phase=phase, trial=k, fictrac=fic,
                                     coverage=cov, camera=camera_speed(path)))
            print(f"  {label} {s.fly_id}: done")
    return pd.DataFrame(rows)


def third_change(g, col):
    """Last-third minus first-third mean of ``col`` over a fly's training trials, or nan."""
    g = g.sort_values("trial")
    n = len(g) // 3
    return g[col].iloc[-n:].mean() - g[col].iloc[:n].mean() if n >= 3 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=config.RAW_ROOT)
    ap.add_argument("--split", default=config.SPLIT_LINE_ROOT)
    ap.add_argument("--stage", default=config.STAGE)
    ap.add_argument("--out", default=config.SUMMARY)
    ap.add_argument("--bin", type=float, default=0.1, help="seconds per bin before taking ball speed")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    df = collect(a)
    df.to_csv(os.path.join(a.out, "fictrac_speed_trials.csv"), index=False)
    ok = df[(df.coverage >= COVERAGE_MIN) & df.camera.notna() & df.fictrac.notna()].copy()
    print(f"\n{len(ok)} of {len(df)} trials with FicTrac coverage >= {COVERAGE_MIN:.0%}")

    lines = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    for lab, g in ok.groupby("dataset"):
        c = COLORS.get(lab, "#555")
        axes[0].scatter(g.camera, g.fictrac, s=5, alpha=0.25, color=c, label=lab)
        fly = g.groupby("fly")[["camera", "fictrac"]].mean()
        axes[1].scatter(fly.camera, fly.fictrac, s=22, color=c, label=lab)
        tr = g[g.phase == "training"]
        ch = tr.groupby("fly").apply(lambda x: pd.Series(
            {"cam": third_change(x, "camera"), "fic": third_change(x, "fictrac")}), include_groups=False).dropna()
        lines.append(dict(dataset=lab, trials=len(g), flies=g.fly.nunique(),
                          r_trial=np.corrcoef(g.camera, g.fictrac)[0, 1],
                          r_fly=np.corrcoef(fly.camera, fly.fictrac)[0, 1] if len(fly) > 2 else np.nan,
                          rad_per_unit=float(np.median(g.fictrac / g.camera)),
                          cam_median=g.camera.median(), fictrac_median=g.fictrac.median(),
                          flies_faster_camera=f"{int((ch['cam'] > 0).sum())}/{len(ch)}",
                          flies_faster_fictrac=f"{int((ch['fic'] > 0).sum())}/{len(ch)}"))
    for ax, t in zip(axes, ("each trial", "fly mean")):
        ax.set_xlabel("camera speed (corridor units/s)")
        ax.set_ylabel("FicTrac ball speed (rad/s)")
        ax.set_title(t)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, markerscale=2)
    fig.tight_layout()
    fig.savefig(os.path.join(a.out, "fictrac_speed_vs_camera.png"), dpi=150)
    tab = pd.DataFrame(lines)
    tab.to_csv(os.path.join(a.out, "fictrac_speed_summary.csv"), index=False)
    print(tab.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
