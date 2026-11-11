#!/usr/bin/env python3
"""Speed along the corridor measured from the raw FicTrac ball, not from the Unity log.

Why: the Unity trial CSV stamps each position when Unity's main thread drains its UDP queue
(``DateTime.Now`` in Closed_loop_client.cs), so several FicTrac frames can share almost the same
timestamp and speed = dX/dt from that log is distorted. FicTrac's own camera clock (column 22,
nanoseconds on this rig) is regular, so speed is taken from it here.

Corridor position is rebuilt exactly as calc_path.py builds it: X += 4 * (column 7, delta
rotation about lab y, rad), clamped at 0 and wrapped at the corridor length; it is anchored to
the first Unity sample of each trial. Frames are matched to a trial through the system clock
(column 25, ms), which is the same clock as the trial CSV ``Timestamp(ms)``.

Burst frames: per-frame ball speed above ``--burst`` corridor units/s. The per-frame distribution
has a walking mode that ends near 30-40 units/s and a separate cluster at 60-160 units/s; the
default 45 sits in the gap. Runs of burst frames up to 3 frames apart form one episode, and the
episode is padded by 2 frames on each side when it is excluded from the "no bursts" profile.

Outputs (in ``--out``):
  session_profiles.csv   per cohort/session/phase/bin: time, path, forward, backward for
                         FicTrac (all frames and without bursts) and Unity (start-bin, same bins);
                         fictrac_eq / fictrac_eq_noburst = equal-trial mean of each trial's own
                         bin speed (the older deck's weighting), the rest are time-weighted
  bursts.csv             one row per burst episode: position, zone, speed, displacement, error
  trial_checks.csv       per trial: frames, coverage, end position from FicTrac vs Unity
  zone_contrasts.csv     zone minus flank speed per session/phase/metric (deck definition)
  fig_profiles_*.png, fig_burst_rate.png, fig_burst_edges.png, fig_example.png

Run (about 5 min):
    python3 fictrac_speed_profile.py [--out .] [--burst 45]
"""
from __future__ import annotations

import argparse
import glob
import os
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPORT = "/home/kazama/Experiment_builds/VR-foraging-build/analysis/reports/2026-11-09-gr64f-split-only"
AUDIT = os.path.join(REPORT, "speed_trajectory_review", "trial_audit.csv")
LEGACY = os.path.join(REPORT, "bump_mechanism_20261110", "session_counterfactual_profiles.csv")
COHORTS = {  # cohort id in the deck -> label, protocol
    "split_line": ("Split line 50/50", "50/50"),
    "split_type2": ("Split line 20/100", "20/100"),
    "past_50_50": ("Gr64f 50/50", "50/50"),
    "past_20_100": ("Gr64f 20/100", "20/100"),
    "split_type3": ("Split line 50/50 reversed V", "50/50"),
}
FICTRAC_LOGS = os.path.expanduser("~/fictrac/foraging")   # FicTrac's own run folders, <YYYYMMDD>_<HHMMSS>/
CORRIDOR = 130.0
GAIN = 4.0                       # calc_path.py gain_dz: corridor units per radian of ball roll
BINS = np.linspace(0, CORRIDOR, 101)
POS = (BINS[:-1] + BINS[1:]) / 2
ZONES = {1: ((20, 40), [(10, 20), (40, 50)]), 2: ((100, 120), [(90, 100), (120, 130)])}
EDGES = [20, 40, 100, 120]
MAX_GAP_S = 2.0
MERGE, PAD = 3, 2
METRICS = ["unity", "fictrac", "fictrac_noburst", "fictrac_fwd", "fictrac_noburst_fwd", "fictrac_eq", "fictrac_eq_noburst"]
COLORS = {"unity": "#8a8a8a", "fictrac": "#1f6fb4", "fictrac_noburst": "#d1495b", "legacy": "#b8860b"}
NAMES = {"unity": "Unity log (time-weighted)", "fictrac": "FicTrac, all frames",
         "fictrac_noburst": "FicTrac, bursts removed", "legacy": "older deck curve (Unity, equal trials)"}


def find_dats(sub_dir, date, t_range):
    """The session's own .dat files; if there are none, FicTrac run logs from the same date whose
    system-clock span overlaps the session's trials (older sessions kept the .dat only there)."""
    own = sorted(glob.glob(os.path.join(sub_dir, "fictrac-*.dat")))
    if own:
        return own, "session folder"
    hits = []
    for p in sorted(glob.glob(os.path.join(FICTRAC_LOGS, date.replace("-", "") + "_*", "fictrac-*.dat"))):
        try:
            first = float(open(p).readline().split(",")[24])
            last = float(pd.read_csv(p, header=None, usecols=[24]).iloc[-1, 0])
        except (OSError, ValueError, IndexError):
            continue
        if first <= t_range[1] and last >= t_range[0]:
            hits.append(p)
    return hits, "~/fictrac/foraging"


def load_dat(paths):
    """frame, err, dy, cam_ns, sys_ms for the given FicTrac .dat files, sorted by sys_ms.
    A session folder (str) is also accepted: its own fictrac-*.dat files are used."""
    if isinstance(paths, (str, os.PathLike)):
        paths = sorted(glob.glob(os.path.join(paths, "fictrac-*.dat")))
    parts = []
    for p in paths:
        try:
            parts.append(pd.read_csv(p, header=None, usecols=[0, 4, 6, 21, 24]).to_numpy(float))
        except (OSError, ValueError):
            continue
    if not parts:
        return None
    f = np.vstack(parts)
    f = f[np.isfinite(f).all(1)]
    return f[np.argsort(f[:, 4], kind="stable")]


def load_unity(path):
    d = pd.read_csv(path, usecols=["Timestamp(ms)", "X"]).to_numpy(float)
    return d[np.isfinite(d).all(1)]


def burst_episodes(flag):
    """[(i0, i1)] index runs (inclusive) of flagged frames, runs <= MERGE frames apart merged."""
    idx = np.flatnonzero(flag)
    if not len(idx):
        return []
    cuts = np.flatnonzero(np.diff(idx) > MERGE + 1)
    starts = np.r_[idx[0], idx[cuts + 1]]
    ends = np.r_[idx[cuts], idx[-1]]
    return list(zip(starts, ends))


def rebuild_x(x0, dX):
    """Position after each step, as calc_path.py integrates it (clamp at 0, wrap at corridor end)."""
    # Clamping at 0 is a running-minimum correction of the cumulative sum; wraps at the far end
    # are rare, so restart the vectorised segment after each one.
    out = np.empty(len(dX))
    i, z = 0, x0
    while i < len(dX):
        s = z + np.cumsum(dX[i:])
        seg = s - np.minimum(np.minimum.accumulate(s), 0)
        hit = np.flatnonzero(seg >= CORRIDOR)
        if not len(hit):
            out[i:] = seg
            break
        k = hit[0]
        out[i:i + k] = seg[:k]
        z = seg[k] % CORRIDOR
        out[i + k] = z
        i += k + 1
    return out


def zone_of(x):
    for k, ((lo, hi), _) in ZONES.items():
        if lo <= x < hi:
            return k
    return 0


def trial(f, upath, burst):
    u = load_unity(upath)
    if len(u) < 3:
        return None
    t0, t1 = u[0, 0], u[-1, 0]
    lo, hi = np.searchsorted(f[:, 4], [t0, t1])
    w = f[max(lo - 1, 0):hi]          # include the frame just before, to get the first interval
    if len(w) < 10:
        return None
    dt = np.diff(w[:, 3]) * 1e-9
    dX = GAIN * w[1:, 2]
    err = w[1:, 1]
    ok = (dt > 0) & (dt < MAX_GAP_S)
    x_after = rebuild_x(u[0, 1], np.where(ok, dX, 0))
    x_before = np.r_[u[0, 1], x_after[:-1]]
    v = np.abs(dX) / np.where(ok, dt, np.inf)
    flag = ok & (v > burst)
    eps = burst_episodes(flag)
    excl = np.zeros(len(dX), bool)
    rows = []
    for a, b in eps:
        excl[max(a - PAD, 0):b + PAD + 1] = True
        seg = slice(a, b + 1)
        rows.append(dict(start_x=x_before[a], end_x=x_after[b], zone=zone_of(x_before[a]),
                         frames=b - a + 1, duration_s=dt[seg].sum(), peak_speed=v[seg].max(),
                         displacement=dX[seg].sum(), max_err=err[seg].max(),
                         err_before=np.median(err[max(a - 20, 0):a]) if a > 0 else np.nan,
                         t_sys_ms=w[a + 1, 4]))
    # Unity start-bin profile on the same bins, using its own (logged) clock
    ut, ux = u[:, 0] / 1000.0, u[:, 1]
    udt, udx = np.diff(ut), np.diff(ux)
    udx = np.where(udx < -CORRIDOR / 2, udx + CORRIDOR, udx)
    uok = (udt > 0) & (udt < MAX_GAP_S)
    ub = np.clip(np.digitize(ux[:-1], BINS) - 1, 0, 99)
    fb = np.clip(np.digitize(x_before, BINS) - 1, 0, 99)

    def h(b, m, wts):
        return np.bincount(b[m], weights=wts[m], minlength=100)

    keep = ok & ~excl
    prof = dict(
        unity_time=h(ub, uok, udt), unity_path=h(ub, uok, np.abs(udx)),
        unity_fwd=h(ub, uok, np.clip(udx, 0, None)),
        fic_time=h(fb, ok, dt), fic_path=h(fb, ok, np.abs(dX)), fic_fwd=h(fb, ok, np.clip(dX, 0, None)),
        nb_time=h(fb, keep, dt), nb_path=h(fb, keep, np.abs(dX)), nb_fwd=h(fb, keep, np.clip(dX, 0, None)),
    )
    unity_end = ux[-1]
    check = dict(frames=len(dX), fictrac_s=dt[ok].sum(), unity_s=t1 / 1000 - t0 / 1000,
                 end_x_fictrac=x_after[-1], end_x_unity=unity_end, bursts=len(eps),
                 burst_time_s=dt[flag].sum(), excluded_time_s=dt[keep != ok].sum())
    trace = dict(t=(w[1:, 4] - t0) / 1000, x=x_after, v=np.where(ok, dX / np.where(ok, dt, 1), np.nan),
                 err=err, flag=flag, ut=ut - ut[0], ux=ux)
    return prof, rows, check, trace


def collect(audit, burst, cohorts):
    a = pd.read_csv(audit)
    a = a[a.cohort.isin(cohorts)]
    prof_rows, bursts, checks, traces = [], [], [], {}
    sessions = list(a.groupby(["cohort", "session_id"], sort=False))
    for n, ((cohort, sid), g) in enumerate(sessions, 1):
        sub = os.path.dirname(os.path.dirname(g.path.iloc[0]))
        starts = [pd.read_csv(p, usecols=[0], nrows=1).iloc[0, 0] for p in g.path]
        date = sid.split(":")[1][:10]
        dats, where = find_dats(sub, date, (min(starts), max(starts) + 900e3))
        f = load_dat(dats)
        if f is None:
            print(f"  [skip] {sid}: no FicTrac .dat in the session folder or {FICTRAC_LOGS}")
            continue
        if where != "session folder":
            print(f"  {sid}: FicTrac log from {where}: {[os.path.basename(d) for d in dats]}")
        for phase, gp in g.groupby("phase"):
            acc = None
            for r in gp.itertuples():
                res = trial(f, r.path, burst)
                if res is None:
                    checks.append(dict(cohort=cohort, session_id=sid, phase=phase, trial=r.trial, status="no frames"))
                    continue
                prof, rows, check, trace = res
                # equal-trial terms: each trial's own bin speed counts once (the older deck recipe)
                for pre, path_k, time_k in (("eq", "fic_path", "fic_time"), ("eqnb", "nb_path", "nb_time")):
                    has = prof[time_k] > 0
                    prof[pre + "_sum"] = np.divide(prof[path_k], prof[time_k], out=np.zeros(100), where=has)
                    prof[pre + "_n"] = has.astype(float)
                acc = prof if acc is None else {k: acc[k] + prof[k] for k in acc}
                for b in rows:
                    bursts.append(dict(cohort=cohort, session_id=sid, phase=phase, trial=r.trial, **b))
                checks.append(dict(cohort=cohort, session_id=sid, phase=phase, trial=r.trial, status="ok", **check))
                if r.trial == "probing_iter_49_trial_1_20260903_160247_022.csv":
                    traces["example"] = trace
            if acc is None:
                continue
            for j in range(100):
                prof_rows.append(dict(cohort=cohort, session_id=sid, phase=phase, bin=j, position=POS[j],
                                      **{k: v[j] for k, v in acc.items()}))
        print(f"  {n}/{len(sessions)} {sid}", flush=True)
    return pd.DataFrame(prof_rows), pd.DataFrame(bursts), pd.DataFrame(checks), traces


def speeds(p):
    r = lambda n, d: np.where(p[d] > 0, p[n] / p[d].where(p[d] > 0), np.nan)
    p = p.copy()
    p["unity"] = r("unity_path", "unity_time")
    p["fictrac"] = r("fic_path", "fic_time")
    p["fictrac_noburst"] = r("nb_path", "nb_time")
    p["fictrac_fwd"] = r("fic_fwd", "fic_time")
    p["fictrac_noburst_fwd"] = r("nb_fwd", "nb_time")
    p["fictrac_eq"] = r("eq_sum", "eq_n")
    p["fictrac_eq_noburst"] = r("eqnb_sum", "eqnb_n")
    return p


def contrasts(p):
    rows = []
    for (c, s, ph), g in p.groupby(["cohort", "session_id", "phase"]):
        g = g.set_index("bin")
        cols = METRICS + (["legacy"] if "legacy" in g else [])
        for z, ((lo, hi), flanks) in ZONES.items():
            inz = (g.position >= lo) & (g.position < hi)
            fl = [(g.position >= a) & (g.position < b) for a, b in flanks]
            for m in cols:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    val = np.nanmean(g.loc[inz, m]) - np.nanmean([np.nanmean(g.loc[f, m]) for f in fl])
                rows.append(dict(cohort=c, session_id=s, phase=ph, zone=z, metric=m, contrast=val))
    return pd.DataFrame(rows)


def shade(ax):
    for lo, hi in [(20, 40), (100, 120)]:
        ax.axvspan(lo, hi, color="#2e8b57", alpha=0.08, lw=0)
    ax.set_xlim(0, CORRIDOR)
    ax.spines[["top", "right"]].set_visible(False)


def band(ax, d, m, **kw):
    g = d.groupby("bin")[m]
    mu, se = g.mean(), g.sem()
    x = POS[mu.index]
    ax.plot(x, mu.values, lw=1.6, color=COLORS.get(m.replace("_fwd", ""), "k"), label=NAMES.get(m, m), **kw)
    ax.fill_between(x, (mu - se).values, (mu + se).values, color=COLORS.get(m.replace("_fwd", ""), "k"),
                    alpha=0.15, lw=0)


def fig_profiles(p, cohorts, out, tag, metrics):
    fig, axes = plt.subplots(len(cohorts), 2, figsize=(13, 3.4 * len(cohorts)), squeeze=False, sharex=True)
    for i, c in enumerate(cohorts):
        for j, ph in enumerate(["training", "probing"]):
            ax = axes[i, j]
            d = p[(p.cohort == c) & (p.phase == ph)]
            for m in metrics:
                if m in d and d[m].notna().any():
                    band(ax, d, m)
            shade(ax)
            ax.set_title(f"{COHORTS[c][0]} · {ph} · {d.session_id.nunique()} sessions", fontsize=10)
            ax.set_ylabel("speed (corridor units/s)")
    axes[-1, 0].set_xlabel("corridor position")
    axes[-1, 1].set_xlabel("corridor position")
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.suptitle("Speed along the corridor: Unity log vs raw FicTrac ball (mean ± SEM over sessions; zones shaded)",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(out, f"fig_profiles_{tag}.png"), dpi=140)
    plt.close(fig)


def fig_burst_rate(p, b, cohorts, out):
    fig, axes = plt.subplots(len(cohorts), 2, figsize=(13, 2.9 * len(cohorts)), squeeze=False, sharex=True)
    for i, c in enumerate(cohorts):
        for j, ph in enumerate(["training", "probing"]):
            ax = axes[i, j]
            d = p[(p.cohort == c) & (p.phase == ph)].groupby("bin").fic_time.sum()
            e = b[(b.cohort == c) & (b.phase == ph)]
            cnt = np.bincount(np.clip(np.digitize(e.start_x, BINS) - 1, 0, 99), minlength=100)
            mins = d.reindex(range(100)).fillna(0).values / 60
            rate = np.divide(cnt, mins, out=np.zeros(100), where=mins > 0)
            ax.bar(POS, np.where(np.isfinite(rate), rate, 0), width=1.3, color="#d1495b")
            shade(ax)
            ax.set_title(f"{COHORTS[c][0]} · {ph} · {len(e)} bursts", fontsize=10)
            ax.set_ylabel("bursts per minute\nspent in bin")
    for ax in axes[-1]:
        ax.set_xlabel("corridor position at burst onset")
    fig.suptitle("Where FicTrac bursts start (all sessions pooled; zones shaded)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_burst_rate.png"), dpi=140)
    plt.close(fig)


def fig_burst_edges(b, out):
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.4), sharey=True)
    off = np.arange(-10, 10.5, 1.0)
    for ax, e in zip(axes, EDGES):
        for ph, col in [("training", "#1f6fb4"), ("probing", "#d1495b")]:
            s = b[b.phase == ph]
            ax.hist(s.start_x - e, bins=off, histtype="step", lw=1.6, color=col, label=ph)
        ax.axvline(0, color="k", lw=0.8)
        ax.set_title(f"edge at X = {e}", fontsize=10)
        ax.set_xlabel("onset position − edge")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("bursts (all cohorts)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_burst_edges.png"), dpi=140)
    plt.close(fig)


def fig_example(tr, out):
    if not tr:
        return
    fig, axes = plt.subplots(3, 1, figsize=(12, 7.5), sharex=True)
    i = np.flatnonzero(tr["flag"])
    tc = tr["t"][i[0]] if len(i) else tr["t"][len(tr["t"]) // 2]
    m = (tr["t"] > tc - 1.5) & (tr["t"] < tc + 1.5)
    um = (tr["ut"] > tc - 1.5) & (tr["ut"] < tc + 1.5)
    axes[0].plot(tr["ut"][um], tr["ux"][um], ".", ms=3, color=COLORS["unity"], label="Unity log X")
    axes[0].plot(tr["t"][m], tr["x"][m], lw=1.2, color=COLORS["fictrac"], label="X rebuilt from FicTrac")
    axes[0].axhspan(100, 120, color="#2e8b57", alpha=0.08)
    axes[0].set_ylabel("X")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].plot(tr["t"][m], tr["v"][m], lw=1, color=COLORS["fictrac"])
    axes[1].plot(tr["t"][m & tr["flag"]], tr["v"][m & tr["flag"]], ".", color=COLORS["fictrac_noburst"], label="burst frames")
    udt = np.diff(tr["ut"]); uv = np.diff(tr["ux"]) / np.where(udt >= 0.005, udt, np.nan)
    axes[1].plot(tr["ut"][1:][um[1:]], uv[um[1:]], "x", ms=4, color=COLORS["unity"], label="Unity dX/dt (dt ≥ 5 ms)")
    axes[1].set_ylabel("forward speed (units/s)")
    axes[1].legend(frameon=False, fontsize=8)
    axes[2].plot(tr["t"][m], tr["err"][m], lw=1, color="#555")
    axes[2].axhline(15000, ls="--", color="k", lw=0.8)
    axes[2].text(tr["t"][m][0], 15200, "opt_max_err 15000", fontsize=8)
    axes[2].set_ylabel("FicTrac error score")
    axes[2].set_xlabel("time in trial (s)")
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Deck example trial (split line 2026-09-03 sub-2, probing iter 49): the burst is in the ball data", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_example.png"), dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--audit", default=AUDIT)
    ap.add_argument("--burst", type=float, default=45.0, help="burst threshold, corridor units/s per frame")
    ap.add_argument("--cohorts", default=",".join(COHORTS))
    a = ap.parse_args()
    cohorts = a.cohorts.split(",")
    os.makedirs(a.out, exist_ok=True)
    prof, bursts, checks, traces = collect(a.audit, a.burst, cohorts)
    prof = speeds(prof)
    if os.path.isfile(LEGACY):  # older deck curve, probing split-line only
        leg = pd.read_csv(LEGACY)[["session_id", "bin", "legacy_equal_trial"]].rename(columns={"legacy_equal_trial": "legacy"})
        leg["phase"] = "probing"
        prof = prof.merge(leg, on=["session_id", "phase", "bin"], how="left")
    prof.to_csv(os.path.join(a.out, "session_profiles.csv"), index=False)
    bursts.to_csv(os.path.join(a.out, "bursts.csv"), index=False)
    checks.to_csv(os.path.join(a.out, "trial_checks.csv"), index=False)
    con = contrasts(prof)
    con.to_csv(os.path.join(a.out, "zone_contrasts.csv"), index=False)

    split = [c for c in cohorts if c.startswith("split")]
    past = [c for c in cohorts if c.startswith("past") and c in set(prof.cohort)]
    if split:
        fig_profiles(prof, split, a.out, "split", ["legacy", "unity", "fictrac", "fictrac_noburst"])
        fig_profiles(prof, split, a.out, "split_forward", ["fictrac_fwd", "fictrac_noburst_fwd"])
    if past:
        fig_profiles(prof, past, a.out, "gr64f", ["unity", "fictrac", "fictrac_noburst"])
    present = [c for c in cohorts if c in set(prof.cohort)]
    missing = sorted(set(cohorts) - set(present))
    if missing:
        print(f"no FicTrac .dat for any session of: {', '.join(missing)}")
    fig_burst_rate(prof, bursts, present, a.out)
    fig_burst_edges(bursts, a.out)
    fig_example(traces.get("example"), a.out)

    ok = checks[checks.status == "ok"]
    print(f"\ntrials ok {len(ok)}/{len(checks)}; median |end X FicTrac - Unity| = "
          f"{np.median(np.minimum(np.abs(ok.end_x_fictrac - ok.end_x_unity), CORRIDOR - np.abs(ok.end_x_fictrac - ok.end_x_unity))):.2f} units (circular); "
          f"FicTrac/Unity duration median {np.median(ok.fictrac_s / ok.unity_s):.4f}")
    print(f"bursts: {len(bursts)} episodes, {ok.bursts.gt(0).mean():.1%} of trials have one, "
          f"{ok.burst_time_s.sum() / ok.fictrac_s.sum():.3%} of time, "
          f"{ok.excluded_time_s.sum() / ok.fictrac_s.sum():.3%} excluded with padding")
    s = con.groupby(["cohort", "phase", "zone", "metric"]).contrast.agg(
        mean="mean", sem="sem", n="count", positive=lambda x: f"{(x > 0).sum()}/{x.notna().sum()}")
    s.reset_index().to_csv(os.path.join(a.out, "zone_contrast_summary.csv"), index=False)
    with pd.option_context("display.width", 200, "display.max_rows", 500):
        print(s.round(3).to_string())


if __name__ == "__main__":
    main()
