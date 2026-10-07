#!/usr/bin/env python3
"""The poster's figures, rebuilt from the *selected* trials of one task.

Same figures as the poster's make_poster_figures.py wherever the data allows. Trial sets come
from the selection json (selection.py); leave-rule panels read the survival table from
build_survival.py. Statistics are computed here (paired exact sign-flip tests, permutation
Spearman) rather than read from precomputed files.

Needs one task with ATR flies. Not made here, because they need other tasks or model fits:
20_100 geometry/dissociation, per-fly timer (20_100), reward effect (non-ATR), GLM comparison.

Run:
    python figures.py --raw-root ~/Raw_data_by_task/"split line" --task <task folder> \
        --survival data/survival_split_line.csv --out results/split_line
"""
from __future__ import annotations

import argparse
import itertools
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

import selection
import trials

TEAL, ORANGE, BLUE, FOREST, GOLD = "#156f76", "#d46638", "#337ab7", "#3f7f5f", "#c4932f"
INK, GRID, SHADE = "#1b2a2f", "#dfe6e4", "#f3ded5"
FLOOR = 0.1
PHASES = ("training", "probing")
COLORS = {"training": TEAL, "probing": ORANGE}


class Ctx:
    """Task geometry, output dir and the selected sessions."""

    def __init__(self, raw_root, task, kind, out):
        info = trials.parse_task(task)
        self.task, self.out = task, out
        self.corridor = info["corridor"]
        self.patches = info["patches"]
        self.bands = [info["patches"][i]["band"] for i in (0, 1)]
        self.sessions = [s for s in selection.iter_selected(raw_root, kind, task)
                         if s.atr is not False]
        os.makedirs(out, exist_ok=True)

    def paths(self, s, phase):
        named = [(trials.parse_fname(n)["ts"], n) for n in s.kept[phase]
                 if trials.parse_fname(n)]
        return [os.path.join(s.sub_dir, phase, n) for _, n in sorted(named)
                if os.path.isfile(os.path.join(s.sub_dir, phase, n))
                and trials.trial_ok(os.path.join(s.sub_dir, phase, n))]

    def save(self, fig, name):
        fig.savefig(os.path.join(self.out, name), dpi=200, bbox_inches="tight",
                    facecolor="white")
        plt.close(fig)
        print("  wrote", name)


def style(ax, size=13):
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#8fa09d")
    ax.tick_params(labelsize=size, colors=INK)
    ax.grid(True, axis="y", color=GRID, linewidth=1.0)
    ax.set_axisbelow(True)


def shade(ax, ctx):
    for lo, hi in ctx.bands:
        ax.axvspan(lo, hi, color=SHADE, alpha=0.58, zorder=0)


# ---- statistics --------------------------------------------------------------------------
def signflip_p(d, max_exact=16, n_rand=20000, seed=0):
    """Two-sided paired sign-flip test on within-fly differences."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    obs = abs(d.sum())
    if len(d) <= max_exact:
        signs = np.array(list(itertools.product((-1, 1), repeat=len(d))))
    else:
        signs = np.random.default_rng(seed).choice((-1, 1), size=(n_rand, len(d)))
    return float(np.mean(np.abs(signs @ d) >= obs - 1e-12))


def fmt_p(p):
    return "<0.001" if p < 0.001 else f"={p:.3f}"


def stars(p):
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


# ---- per-trial readers --------------------------------------------------------------------
def load_cam(path):
    try:
        a = np.genfromtxt(path, delimiter=",", skip_header=1, usecols=(0, 1), invalid_raise=False)
    except (OSError, ValueError):
        return None
    if a.ndim != 2 or len(a) < 3:
        return None
    return a[np.isfinite(a).all(axis=1)]


def occupancy(ctx, paths, n_bins=100):
    bins = np.linspace(0, ctx.corridor, n_bins + 1)
    mat = np.full((len(paths), n_bins), np.nan)
    for i, p in enumerate(paths):
        a = load_cam(p)
        if a is not None and len(a) > 1:
            mat[i], _ = np.histogram(np.mod(a[:, 1], ctx.corridor), bins=bins)
    return 0.5 * (bins[:-1] + bins[1:]), mat


def frac_profile(mat):
    tot = np.nansum(mat, axis=1, keepdims=True)
    return np.nanmean(mat / np.where(tot == 0, np.nan, tot), axis=0)


def occupancy_profiles(ctx):
    centers, prof, mats = None, {}, {}
    for s in ctx.sessions:
        for ph in PHASES:
            centers, m = occupancy(ctx, ctx.paths(s, ph))
            mats[(s.fly_id, ph)] = m
            prof.setdefault(s.fly_id, {})[ph] = frac_profile(m)
    return centers, prof, mats


def camera_speed(ctx, path, n_bins=100):
    a = load_cam(path)
    if a is None:
        return None
    t, x = a[:, 0] / 1000.0, a[:, 1]
    dx = np.diff(x)
    half = ctx.corridor / 2
    dx = np.where(dx > half, dx - ctx.corridor, np.where(dx < -half, dx + ctx.corridor, dx))
    dt = np.diff(t)
    sp = np.divide(np.abs(dx), dt, out=np.full_like(dx, np.nan), where=dt >= 0.005)
    fin = np.isfinite(sp)
    k = np.ones(5)
    num, den = np.convolve(np.where(fin, sp, 0), k, "same"), np.convolve(fin.astype(float), k, "same")
    sp = np.divide(num, den, out=np.full_like(sp, np.nan), where=den > 0)
    bins = np.linspace(0, ctx.corridor, n_bins + 1)
    idx = np.clip(np.digitize(np.mod(x[:-1], ctx.corridor), bins) - 1, 0, n_bins - 1)
    out = np.full(n_bins, np.nan)
    for b in range(n_bins):
        v = sp[idx == b]
        v = v[np.isfinite(v)]
        if v.size:
            out[b] = v.mean()
    return 0.5 * (bins[:-1] + bins[1:]), out


def speed_profiles(ctx):
    centers, prof = None, {}
    for s in ctx.sessions:
        for ph in PHASES:
            rows = [r for r in (camera_speed(ctx, p) for p in ctx.paths(s, ph)) if r]
            if rows:
                centers = rows[0][0]
                prof.setdefault(s.fly_id, {})[ph] = np.nanmean(np.stack([r[1] for r in rows]), 0)
    return centers, {k: v for k, v in prof.items() if set(v) == set(PHASES)}


# ---- figures ------------------------------------------------------------------------------
def fig_occupancy_lines(ctx, centers, prof):
    fig, axes = plt.subplots(2, 1, figsize=(9.4, 6.8), sharex=True, gridspec_kw={"hspace": 0.18})
    for ax, ph in zip(axes, PHASES):
        shade(ax, ctx)
        lines = np.vstack([p[ph] for p in prof.values()]) * 100
        for y in lines:
            ax.plot(centers, y, color=COLORS[ph], alpha=0.24, lw=1.25)
        ax.plot(centers, np.nanmean(lines, 0), color=INK, lw=3.0)
        ax.set_ylabel("Time at position (% of trial)", fontsize=16)
        ax.set_title(ph, loc="left", weight="bold", color=COLORS[ph], fontsize=17)
        ax.set_xlim(0, ctx.corridor)
        style(ax)
    axes[-1].set_xlabel("Corridor position", fontsize=16)
    axes[0].text(0.99, 0.88, f"n={len(prof)} flies", transform=axes[0].transAxes,
                 ha="right", va="top", fontsize=15, color=INK)
    fig.suptitle("Where flies spend their time along the corridor", fontsize=20,
                 weight="bold", y=0.98)
    ctx.save(fig, "occupancy_per_fly_lines.png")


def patch_bias(ctx, centers, p):
    m = np.zeros_like(centers, bool)
    for lo, hi in ctx.bands:
        m |= (centers >= lo) & (centers <= hi)
    return float(np.nanmean(p[m])) / max(float(np.nanmean(p[~m])), 1e-9)


def example_flies(ctx, centers, prof):
    """(learning-biased fly, most representative fly) as in the poster."""
    learner = max(prof, key=lambda f: patch_bias(ctx, centers, prof[f]["probing"]))
    group = {ph: np.nanmean(np.vstack([p[ph] for p in prof.values()]), 0) for ph in PHASES}
    rep = min(prof, key=lambda f: sum(float(np.nanmean((prof[f][ph] - group[ph]) ** 2))
                                      for ph in PHASES))
    return learner, rep


def fig_occupancy_heatmaps(ctx, centers, prof, mats):
    learner, rep = example_flies(ctx, centers, prof)
    ex = [("Example 1: fly that spent the most time in the patches during probing", learner),
          ("Example 2: fly closest to the group average", rep)]
    data = {}
    for _, f in ex:
        for ph in PHASES:
            m = mats[(f, ph)]
            data[(f, ph)] = 100 * m / np.where(np.nansum(m, 1, keepdims=True) == 0, np.nan,
                                               np.nansum(m, 1, keepdims=True))
    vmax = max(2.0, max(float(np.nanpercentile(v, 99)) for v in data.values()))

    fig = plt.figure(figsize=(11.8, 12.2))
    gs = fig.add_gridspec(5, 3, width_ratios=[1, 1, 0.045],
                          height_ratios=[0.1, 0.72, 0.1, 0.72, 0.9], hspace=0.55, wspace=0.24,
                          left=0.065, right=0.955, top=0.97, bottom=0.05)
    for r, (title, f) in zip((0, 2), ex):
        t = fig.add_subplot(gs[r, :2]); t.axis("off")
        t.text(0.5, 0.2, f"{title}  ({f})", ha="center", fontsize=15, weight="bold", color=INK)
        for c, ph in enumerate(PHASES):
            ax = fig.add_subplot(gs[r + 1, c])
            d = np.nan_to_num(data[(f, ph)])
            img = ax.imshow(d, aspect="auto", interpolation="nearest", cmap="YlGnBu", vmin=0,
                            vmax=vmax, extent=[0, ctx.corridor, len(d), 0])
            for lo, hi in ctx.bands:
                ax.axvline(lo, color="white", lw=1.6, alpha=.9)
                ax.axvline(hi, color="white", lw=1.6, alpha=.9)
            ax.set_title(ph.capitalize(), weight="bold", color=TEAL, fontsize=15)
            ax.tick_params(labelsize=12)
            if c == 0:
                ax.set_ylabel("trial", fontsize=13)
            if r == 2:
                ax.set_xlabel("Corridor position", fontsize=13)
    fig.colorbar(img, cax=fig.add_subplot(gs[1:4, 2]), label="time at position per trial (%)")
    ax = fig.add_subplot(gs[4, :])
    shade(ax, ctx)
    for ph in PHASES:
        lines = np.vstack([p[ph] for p in prof.values()]) * 100
        for y in lines:
            ax.plot(centers, y, color=COLORS[ph], alpha=0.18, lw=1.2)
        ax.plot(centers, np.nanmean(lines, 0), color=COLORS[ph], lw=2.8, label=f"{ph} mean")
    ax.set_xlim(0, ctx.corridor)
    ax.set_xlabel("Corridor position", fontsize=15)
    ax.set_ylabel("time at position (% of trial)", fontsize=15)
    ax.set_title(f"Where flies spend their time (n = {len(prof)} flies)", fontsize=16, weight="bold", pad=14)
    ax.legend(frameon=False, fontsize=13, loc="upper right")
    style(ax)
    ctx.save(fig, "occupancy_training_probing.png")

    # log-scaled heatmaps of the learning-biased fly, as in the poster's example figure
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.8))
    raw = {ph: mats[(learner, ph)] for ph in PHASES}
    vmax = max(2.0, max(float(np.nanpercentile(m, 99)) for m in raw.values()))
    for ax, ph in zip(axes, PHASES):
        d = np.nan_to_num(raw[ph])
        d = np.where(d <= 0, 1.0, d)
        img = ax.imshow(d, aspect="auto", interpolation="nearest", cmap="viridis",
                        norm=LogNorm(vmin=1, vmax=vmax), extent=[0, ctx.corridor, len(d), 0])
        for lo, hi in ctx.bands:
            ax.axvline(lo, color="white", lw=1.2, alpha=.82)
            ax.axvline(hi, color="white", lw=1.2, alpha=.82)
        ax.set_title(ph, weight="bold")
        ax.set_xlabel("Corridor position")
    axes[0].set_ylabel("Trial")
    fig.colorbar(img, ax=axes, label="Frames per bin (log)", shrink=0.82, pad=0.02)
    fig.suptitle(f"Example fly: time at each position, trial by trial ({learner})", fontsize=18, weight="bold", y=1.02)
    ctx.save(fig, "occupancy_example_heatmaps.png")


def fig_speed(ctx):
    centers, prof = speed_profiles(ctx)
    if not prof:
        print("  [skip] no speed profiles")
        return None
    fig, ax = plt.subplots(figsize=(11.8, 4.2))
    shade(ax, ctx)
    for ph in PHASES:
        lines = np.vstack([p[ph] for p in prof.values()])
        for y in lines:
            ax.plot(centers, y, color=COLORS[ph], alpha=0.16, lw=1.1)
        ax.plot(centers, np.nanmean(lines, 0), color=COLORS[ph], lw=3.0, label=f"{ph} mean")
    ax.set_xlim(0, ctx.corridor)
    ax.set_title("Walking speed along the corridor", fontsize=20, weight="bold")
    ax.set_xlabel("Corridor position", fontsize=15)
    ax.set_ylabel("Speed\n(corridor units/s)", fontsize=14)
    ax.legend(frameon=False, fontsize=13, loc="upper right")
    style(ax)
    ctx.save(fig, "speed_by_position.png")

    # approach to patch 2: mean +- bootstrap CI over flies, slope tested across flies
    lo, hi = ctx.bands[0][1], ctx.bands[1][0]
    m = (centers >= lo) & (centers < hi)
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(11.8, 4.6))
    for ph in PHASES:
        L = np.vstack([p[ph][m] for p in prof.values()])
        mean = np.nanmean(L, 0)
        boots = np.array([np.nanmean(L[rng.integers(0, len(L), len(L))], 0) for _ in range(2000)])
        ax.fill_between(centers[m], *np.nanpercentile(boots, [2.5, 97.5], axis=0),
                        color=COLORS[ph], alpha=0.16, lw=0)
        slopes = [np.polyfit(centers[m][np.isfinite(r)], r[np.isfinite(r)], 1)[0] for r in L]
        p = signflip_p(slopes)
        ax.plot(centers[m], mean, color=COLORS[ph], lw=3, label=f"{ph}  slope p{fmt_p(p)}")
    ax.axvline(hi, color=INK, lw=1.5, ls="--")
    ax.set_xlim(lo, hi)
    ax.set_xlabel("Corridor position during approach to patch 2", fontsize=14)
    ax.set_ylabel("Speed\n(corridor units/s)", fontsize=14)
    ax.set_title("Speed during the approach to patch 2", fontsize=20, weight="bold")
    ax.legend(frameon=False, fontsize=12.5, loc="upper left")
    style(ax)
    ctx.save(fig, "speed_approach_patch2.png")
    return prof


def fig_fictrac(ctx):
    out = {}
    for s in ctx.sessions:
        dat = sorted(f for f in os.listdir(s.sub_dir)
                     if f.startswith("fictrac-") and f.endswith(".dat"))
        if not dat:
            continue
        try:
            raw = pd.read_csv(os.path.join(s.sub_dir, dat[0]), header=None,
                              usecols=[5, 6, 7, 24]).to_numpy(float)
        except (OSError, ValueError):
            continue
        tm = raw[:, 3]
        dt = np.diff(tm) / 1000.0
        with np.errstate(divide="ignore", invalid="ignore"):
            v = raw[1:, :3] / dt[:, None]
        vt = 0.5 * (tm[1:] + tm[:-1])
        ok = (dt > 0) & np.isfinite(v).all(1) & np.isfinite(vt)
        vt, v = vt[ok], v[ok]
        bins = np.linspace(0, ctx.corridor, 101)
        for ph in PHASES:
            tr = []
            for p in ctx.paths(s, ph):
                a = load_cam(p)
                if a is None:
                    continue
                cov = (a[:, 0] >= vt[0]) & (a[:, 0] <= vt[-1])
                if not cov.any():
                    continue
                vals = np.column_stack([np.interp(a[:, 0], vt, v[:, k]) for k in range(3)])
                vals[~cov] = np.nan
                idx = np.clip(np.digitize(np.mod(a[:, 1], ctx.corridor), bins) - 1, 0, 99)
                prof = np.full((3, 100), np.nan)
                for b in range(100):
                    sel = idx == b
                    if sel.any():
                        prof[:, b] = np.nanmean(vals[sel], 0)
                tr.append(prof)
            if tr:
                out.setdefault(s.fly_id, {})[ph] = np.nanmean(np.stack(tr), 0)
    out = {k: v for k, v in out.items() if set(v) == set(PHASES)}
    if not out:
        print("  [skip] fictrac: no session has FicTrac frames overlapping the camera log")
        return
    centers = 0.5 * (np.linspace(0, ctx.corridor, 101)[:-1] + np.linspace(0, ctx.corridor, 101)[1:])
    labels = ("lab x: roll-like", "lab y: pitch-like", "lab z: yaw-like")
    fig, axes = plt.subplots(3, 1, figsize=(11.8, 7.8), sharex=True, gridspec_kw={"hspace": 0.18})
    for k, ax in enumerate(axes):
        shade(ax, ctx)
        for ph in PHASES:
            L = np.vstack([p[ph][k] for p in out.values()])
            for y in L:
                ax.plot(centers, y, color=COLORS[ph], alpha=0.18, lw=1.1)
            ax.plot(centers, np.nanmean(L, 0), color=COLORS[ph], lw=2.8,
                    label=f"{ph} mean" if k == 0 else None)
        ax.axhline(0, color="#8fa09d", lw=1, ls="--")
        ax.set_ylabel(f"{labels[k]}\n(rad/s)", fontsize=14)
        ax.set_xlim(0, ctx.corridor)
        style(ax)
    axes[0].set_title(f"Walking velocity measured from the ball along the corridor (n={len(out)} flies)",
                      fontsize=19, weight="bold")
    axes[0].legend(frameon=False, fontsize=12, loc="upper right")
    axes[-1].set_xlabel("corridor position", fontsize=15)
    ctx.save(fig, "fictrac_velocity.png")


def value_curve(start, decay_s, t):
    return np.maximum(start - (start - FLOOR) / decay_s * t, FLOOR)


def fig_geometry(ctx):
    fig, ax = plt.subplots(figsize=(4.4, 3.9))
    t = np.linspace(0, 55, 300)
    for patch, ls in ((0, "-"), (1, "--")):
        sp = ctx.patches[patch]
        ax.plot(t, value_curve(sp["start_volt"], sp["decay_s"], t), color=BLUE, ls=ls, lw=3, alpha=.82)
    ax.set_xlim(0, 55)
    ax.set_ylim(0, 2.78)
    ax.set_xlabel("Time in patch (s)", fontsize=14)
    ax.set_ylabel("LED reward (V)", fontsize=14)
    p0, p1 = ctx.patches[0], ctx.patches[1]
    ax.set_title(f"Reward starts at {p0['start_volt']}/{p1['start_volt']} V, runs out in {p0['decay_s']:.0f}/{p1['decay_s']:.0f} s",
                 weight="bold", color=BLUE, fontsize=14)
    ax.legend(handles=[plt.Line2D([0], [0], color=BLUE, lw=3, label="Patch 1"),
                       plt.Line2D([0], [0], color=BLUE, lw=3, ls="--", label="Patch 2")],
              frameon=False, fontsize=11, loc="upper right")
    style(ax)
    ctx.save(fig, "leave_geometry.png")


def fig_dissociation(ctx, surv):
    left = surv[(surv.phase == "training") & (surv.left == 1)]
    p0, p1 = ctx.patches[0], ctx.patches[1]
    labels = [f"patch 1\n{p0['start_volt']} V", f"patch 2\n{p1['start_volt']} V"]
    specs = [("t_bin", "Time spent in patch (s)"), ("value_volts", "Reward left on leaving (V)"),
             ("value_frac", "Fraction of start reward left")]
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 4.2), gridspec_kw={"wspace": 0.34})
    for ax, (col, ylab) in zip(axes, specs):
        tab = left.groupby(["fly_id", "patch"])[col].median().unstack().dropna()
        ax.bar([0, 1], tab[[0, 1]].mean().to_numpy(), color=[FOREST, GOLD], width=.62, alpha=.78)
        for _, r in tab.iterrows():
            ax.plot([0, 1], [r[0], r[1]], color=INK, lw=.8, alpha=.25)
        jit = np.linspace(-.1, .1, len(tab))
        for i in (0, 1):
            ax.scatter(np.full(len(tab), i) + jit, tab[i], s=28, color=INK, alpha=.58, zorder=3)
        p = signflip_p(tab[0] - tab[1])
        top = float(tab.to_numpy().max())
        ax.plot([0, 0, 1, 1], [top * 1.05, top * 1.08, top * 1.08, top * 1.05], color=INK, lw=1.3)
        ax.text(.5, top * 1.09, f"Paired p{fmt_p(p)}  {stars(p)}", ha="center", fontsize=12)
        ax.set_ylim(0, top * 1.22)
        ax.set_xticks([0, 1], labels, fontsize=12)
        ax.set_ylabel(ylab, fontsize=14)
        style(ax, 12)
    fig.suptitle(f"When flies leave each patch (n={left.fly_id.nunique()} flies)", fontsize=19,
                 weight="bold", color=BLUE)
    ctx.save(fig, "dissociation.png")


def spearman(x, y):
    return float(pd.Series(x).rank().corr(pd.Series(y).rank()))


def fig_repeatability(ctx, surv):
    """Early- vs late-session median dwell per fly (first vs second half of trials)."""
    d = surv.copy()
    d["time_in_patch"] = d.groupby("visit_id").t_bin.transform("max")
    d = d.drop_duplicates("visit_id")
    rng = np.random.default_rng(0)
    res = {}
    for ph in PHASES:
        rows = []
        for fly, g in d[d.phase == ph].groupby("fly_id"):
            cut = g.trial_order.median()
            e, l = g[g.trial_order <= cut].time_in_patch, g[g.trial_order > cut].time_in_patch
            if len(e) >= 3 and len(l) >= 3:
                rows.append((fly, e.median(), l.median()))
        res[ph] = pd.DataFrame(rows, columns=["fly_id", "early", "late"])
    ps = {}
    for ph, t in res.items():
        rho = spearman(t.early, t.late)
        perm = [spearman(t.early, rng.permutation(t.late.to_numpy())) for _ in range(5000)]
        ps[ph] = (rho, float(np.mean(np.abs(perm) >= abs(rho))))
    holm = {ph: min(1.0, p * (2 - i)) for i, (ph, (_, p)) in
            enumerate(sorted(ps.items(), key=lambda kv: kv[1][1]))}
    lim = float(pd.concat(res.values())[["early", "late"]].to_numpy().max()) * 1.07
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.65), sharex=True, sharey=True)
    for ax, ph in zip(axes, PHASES):
        t = res[ph]
        ax.scatter(t.early, t.late, s=68, color=COLORS[ph], edgecolor="white", zorder=3)
        c = np.polyfit(t.early, t.late, 1)
        xs = np.linspace(t.early.min(), t.early.max(), 100)
        ax.plot(xs, np.polyval(c, xs), color=COLORS[ph], lw=2.6)
        ax.plot([0, lim], [0, lim], color=INK, lw=1.2, ls="--")
        ax.text(.04, .95, f"rank correlation = {ps[ph][0]:.2f}\ncorrected p{fmt_p(holm[ph])}  {stars(holm[ph])}",
                transform=ax.transAxes, va="top", fontsize=12, weight="bold")
        ax.set_title(ph.capitalize(), color=COLORS[ph], weight="bold")
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        style(ax)
    fig.supxlabel("Median time in patch, first half of session (s)", fontsize=14, y=0.015)
    fig.supylabel("Median time in patch, second half of session (s)", fontsize=14, x=0.012)
    fig.subplots_adjust(left=.10, right=.98, top=.88, bottom=.22, wspace=.18)
    ctx.save(fig, "time_in_patch_repeatability.png")
    pd.concat({ph: t for ph, t in res.items()}, names=["phase"]).reset_index(0).to_csv(
        os.path.join(ctx.out, "time_in_patch_repeatability_by_fly.csv"), index=False)


def run(raw_root, task, kind, survival_csv, out):
    """Make every figure; returns False if the task has no ATR sessions to plot."""
    ctx = Ctx(raw_root, task, kind, out)
    if not ctx.sessions:
        return False
    surv = pd.read_csv(survival_csv)
    print(f"{len(ctx.sessions)} sessions -> {out}")
    centers, prof, mats = occupancy_profiles(ctx)
    fig_occupancy_lines(ctx, centers, prof)
    fig_occupancy_heatmaps(ctx, centers, prof, mats)
    fig_speed(ctx)
    fig_fictrac(ctx)
    fig_geometry(ctx)
    fig_dissociation(ctx, surv)
    fig_repeatability(ctx, surv)
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
