#!/usr/bin/env python3
"""Detailed look at the fast ball bursts: both genetic lines, training and probing.

Re-reads the raw FicTrac .dat with fictrac_speed_profile's own functions (same clock, same
corridor rebuild, same 45 units/s frame threshold and episode merging) and adds what bursts.csv
does not hold: trial order, zone entries, time since zone entry, speed before and after each
burst, and where the burst ends.

Burst classes (one row per episode in burst_detail/bursts_detail.csv):
  spike        1-2 frames
  behavioural  3-30 frames, net forward, FicTrac error below its bad-frame cutoff (15000)
  bad          3+ frames that fail any of those (long backward runs, error at the cutoff)
Only "behavioural" bursts are analysed further; the other two are counted and reported.

Outputs in burst_detail/:
  bursts_detail.csv      every episode with class, zone, trial order, pre/post speed, entry timing,
                         and the reward-light state at onset for training bursts in a zone
  trials_detail.csv      per trial: order, time and entries per zone, behavioural bursts per zone
  session_rates.csv      per cohort/session/phase/region: minutes, bursts, bursts per minute
  tests.csv              session-level tests (exact sign-flip for paired, Mann-Whitney for lines)
  triggered.npz          burst-triggered speed, per session mean (cohort/phase), -1 s .. +2 s
  summary.json           the numbers quoted on the slides

Cohorts: Gr64f 50/50, split line 50/50, split line 50/50 reversed V (split_type3), split line 20/100.

Run (about 5 min):  python3 burst_detail.py
"""
from __future__ import annotations

import itertools
import json
import os
import re

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

import fictrac_speed_profile as FT

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "burst_detail")
COHORTS = ["past_50_50", "split_line", "split_type3", "split_type2"]   # Gr64f 20/100 has no FicTrac .dat
# trial list: trial_list.csv next to this script (trial_list.py, includes newly added sessions) if present,
# else the deck's speed_trajectory_review/trial_audit.csv
AUDIT = os.path.join(HERE, "trial_list.csv") if os.path.isfile(os.path.join(HERE, "trial_list.csv")) else FT.AUDIT
PHASES = ["training", "probing"]
BURST = 45.0
ERR_CUT = 15000.0
MAX_FRAMES = 30
ZONE = {1: (20.0, 40.0), 2: (100.0, 120.0)}
PRE, POST = 96, 193                 # frames (10.375 ms): about -1 s .. +2 s
FRAME_S = 0.010375
STAMP = re.compile(r"_(\d{8})_(\d{6})_(\d{3})\.csv$")


def trial_time(name):
    m = STAMP.search(name)
    return int(m.group(1) + m.group(2) + m.group(3)) if m else -1


def region(x):
    for k, (lo, hi) in ZONE.items():
        if lo <= x < hi:
            return k
    return 0


def classify(frames, disp, max_err):
    if frames < 3:
        return "spike"
    if frames <= MAX_FRAMES and disp > 0 and max_err < ERR_CUT:
        return "behavioural"
    return "bad"


def sign_flip(d):
    """Exact two-sided sign-flip test on the mean of paired differences (zeros kept)."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n == 0 or not np.any(d):
        return np.nan
    obs = abs(d.mean())
    if n <= 20:
        signs = np.array(list(itertools.product([1, -1], repeat=n)))
        null = np.abs((signs * d).mean(1))
    else:
        rng = np.random.default_rng(0)
        null = np.abs((rng.choice([1, -1], (200000, n)) * d).mean(1))
    return float((null >= obs - 1e-12).mean())


def collect():
    a = pd.read_csv(AUDIT)
    a = a[a.cohort.isin(COHORTS)]
    bursts, trials, trig = [], [], []
    sessions = list(a.groupby(["cohort", "session_id"], sort=False))
    for n, ((cohort, sid), g) in enumerate(sessions, 1):
        f = FT.load_dat(os.path.dirname(os.path.dirname(g.path.iloc[0])))
        if f is None:
            print(f"  [skip] {sid}: no FicTrac .dat")
            continue
        g = g.assign(stamp=g.trial.map(trial_time)).sort_values("stamp")
        g["order_session"] = np.arange(1, len(g) + 1)
        g["order_phase"] = g.groupby("phase").cumcount() + 1
        g["phase_trials"] = g.groupby("phase").trial.transform("size")
        for r in g.itertuples():
            res = FT.trial(f, r.path, BURST)
            if res is None:
                continue
            _, rows, _, tr = res
            t, x, v, err, flag = tr["t"], tr["x"], tr["v"], tr["err"], tr["flag"]
            dt = np.diff(t, prepend=t[0] - FRAME_S)
            dt = np.where((dt > 0) & (dt < FT.MAX_GAP_S), dt, 0)
            xb = np.r_[x[0], x[:-1]]                     # position before each step
            reg = np.select([(xb >= 20) & (xb < 40), (xb >= 100) & (xb < 120)], [1, 2], 0)
            entry = {k: np.flatnonzero((reg[1:] == k) & (reg[:-1] != k)) + 1 for k in ZONE}
            base = dict(cohort=cohort, session_id=sid, phase=r.phase, trial=r.trial,
                        order_session=r.order_session, order_phase=r.order_phase, phase_trials=r.phase_trials)
            count = {0: 0, 1: 0, 2: 0}
            for (i0, i1), row in zip(FT.burst_episodes(flag), rows):
                kind = classify(row["frames"], row["displacement"], row["max_err"])
                z = region(xb[i0])
                d = {**base, **row, 'kind': kind, 'zone': z, 'onset_s': float(t[i0] - t[0]), 'end_zone': region(x[i1])}
                if z:
                    lo, hi = ZONE[z]
                    e = entry[z][entry[z] <= i0]
                    j = e[-1] if len(e) else 0
                    d.update(into_zone=float(xb[i0] - lo), to_exit=float(hi - xb[i0]),
                             since_entry_s=float(t[i0] - t[j]), left_zone=bool(x[i1] >= hi))
                pre = slice(max(i0 - PRE, 0), max(i0 - 10, 0))
                post = slice(i1 + 10, i1 + 1 + PRE)
                d.update(pre_speed=float(np.nanmean(np.abs(v[pre]))) if pre.stop > pre.start else np.nan,
                         post_speed=float(np.nanmean(np.abs(v[post]))) if len(v[post]) else np.nan)
                bursts.append(d)
                if kind == "behavioural":
                    count[z] += 1
                    w = np.full(PRE + POST + 1, np.nan)
                    lo_i, hi_i = max(i0 - PRE, 0), min(i0 + POST + 1, len(v))
                    w[lo_i - (i0 - PRE):hi_i - (i0 - PRE)] = v[lo_i:hi_i]
                    trig.append((cohort, sid, r.phase, z, w))
            trials.append(dict(base, duration_s=float(dt.sum()),
                               **{f"time_z{k}": float(dt[reg == k].sum()) for k in (0, 1, 2)},
                               **{f"entries_z{k}": int(len(entry[k])) for k in ZONE},
                               **{f"bursts_z{k}": count[k] for k in (0, 1, 2)}))
        print(f"  {n}/{len(sessions)} {sid}", flush=True)
    return pd.DataFrame(bursts), pd.DataFrame(trials), trig


def light_at_bursts(b):
    """Reward-light state at the onset of each training burst that starts in a zone.

    flash_events/<trial>.csv has one row per 20 ms while the light flashes (wall clock, volts).
    The burst's system time is ms since local midnight, the same clock as the trial CSV.
    """
    import datetime
    paths = pd.read_csv(AUDIT).set_index(["session_id", "trial"]).path
    b = b.copy()
    for col in ["light_on", "light_volts", "light_start_volts", "light_elapsed_s"]:
        b[col] = np.nan
    sel = b[(b.phase == "training") & (b.zone > 0)]
    for (sid, trial), g in sel.groupby(["session_id", "trial"]):
        p = paths.get((sid, trial))
        fp = os.path.join(os.path.dirname(os.path.dirname(p)), "flash_events", trial)
        if not os.path.isfile(fp):
            continue
        fl = pd.read_csv(fp)
        if not len(fl):
            b.loc[g.index, "light_on"] = 0.0
            continue
        w = fl.wall_timestamp.to_numpy()
        d0 = datetime.datetime.fromtimestamp(w[0])
        sec = w - d0.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for i, r in g.iterrows():
            ts = r.t_sys_ms / 1000.0
            ts += 86400 * round((sec[0] - ts) / 86400)          # sessions that pass midnight
            j = np.searchsorted(sec, ts) - 1
            if j < 0:
                b.loc[i, "light_on"] = 0.0
                continue
            on = (ts - sec[j]) < 0.1 and fl.zone.iloc[j] == r.zone - 1
            b.loc[i, ["light_on", "light_volts", "light_elapsed_s"]] = [float(on), fl.amplitude_volts.iloc[j], fl.elapsed_time_sec.iloc[j]]
            b.loc[i, "light_start_volts"] = fl.amplitude_volts[fl.zone == fl.zone.iloc[j]].max()
    return b


def session_rates(tr):
    rows = []
    for (c, s, ph), g in tr.groupby(["cohort", "session_id", "phase"]):
        for name, ks in [("zone", (1, 2)), ("zone1", (1,)), ("zone2", (2,)), ("outside", (0,))]:
            mins = sum(g[f"time_z{k}"].sum() for k in ks) / 60
            nb = sum(g[f"bursts_z{k}"].sum() for k in ks)
            rows.append(dict(cohort=c, session_id=s, phase=ph, region=name, minutes=mins, bursts=int(nb),
                             rate=nb / mins if mins > 0 else np.nan))
        zb = g.bursts_z1 + g.bursts_z2
        rows.append(dict(cohort=c, session_id=s, phase=ph, region="trials_with_zone_burst", minutes=np.nan,
                         bursts=int((zb > 0).sum()), rate=float((zb > 0).mean())))
        half = g.order_phase <= g.phase_trials / 2
        for name, m in [("zone_first_half", half), ("zone_second_half", ~half)]:
            mins = (g.time_z1 + g.time_z2)[m].sum() / 60
            rows.append(dict(cohort=c, session_id=s, phase=ph, region=name, minutes=mins, bursts=int(zb[m].sum()),
                             rate=zb[m].sum() / mins if mins > 0 else np.nan))
    return pd.DataFrame(rows)


def tests(sr):
    w = sr.pivot_table(index=["cohort", "session_id"], columns=["phase", "region"], values="rate")
    rows = []

    def paired(c, label, x, y):
        d = (x - y).dropna()
        rows.append(dict(cohort=c, test=label, kind="exact sign-flip, paired sessions", sessions=len(d),
                         a_median=float(x.loc[d.index].median()), b_median=float(y.loc[d.index].median()),
                         a_higher=int((d > 0).sum()), b_higher=int((d < 0).sum()), p=sign_flip(d)))

    for c in COHORTS:
        q = w.loc[c]
        for ph in PHASES:
            paired(c, f"{ph}: zones vs outside", q[(ph, "zone")], q[(ph, "outside")])
            paired(c, f"{ph}: zone 1 vs zone 2", q[(ph, "zone1")], q[(ph, "zone2")])
            paired(c, f"{ph}: second vs first half of trials", q[(ph, "zone_second_half")], q[(ph, "zone_first_half")])
        paired(c, "zones: probing vs training", q[("probing", "zone")], q[("training", "zone")])
        paired(c, "outside: probing vs training", q[("probing", "outside")], q[("training", "outside")])
        paired(c, "trials with a zone burst: probing vs training",
               q[("probing", "trials_with_zone_burst")], q[("training", "trials_with_zone_burst")])
    for ph in PHASES:                                   # the two lines on the matched 50/50 task
        for reg in ["zone", "outside", "trials_with_zone_burst"]:
            x, y = w.loc["split_line"][(ph, reg)].dropna(), w.loc["past_50_50"][(ph, reg)].dropna()
            rows.append(dict(cohort="split_line vs past_50_50", test=f"{ph}: {reg}, split line vs Gr64f (50/50)",
                             kind="Mann-Whitney, sessions", sessions=len(x) + len(y), a_median=float(x.median()),
                             b_median=float(y.median()), a_higher=np.nan, b_higher=np.nan,
                             p=float(mannwhitneyu(x, y, alternative="two-sided").pvalue)))
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    b, tr, trig = collect()
    b = light_at_bursts(b)
    b.to_csv(os.path.join(OUT, "bursts_detail.csv"), index=False)
    tr.to_csv(os.path.join(OUT, "trials_detail.csv"), index=False)
    sr = session_rates(tr)
    sr.to_csv(os.path.join(OUT, "session_rates.csv"), index=False)
    ts = tests(sr)
    ts.to_csv(os.path.join(OUT, "tests.csv"), index=False)

    # burst-triggered speed: mean within session first, sessions with at least 3 zone bursts
    T = pd.DataFrame(trig, columns=["cohort", "session_id", "phase", "zone", "v"])
    T = T[T.zone > 0]
    keys, means, counts = [], [], []
    for (c, s, ph), g in T.groupby(["cohort", "session_id", "phase"]):
        if len(g) >= 3:
            keys.append((c, s, ph))
            means.append(np.nanmean(np.vstack(g.v.values), 0))
            counts.append(len(g))
    np.savez(os.path.join(OUT, "triggered.npz"), keys=np.array(keys), mean=np.array(means), n=np.array(counts),
             t=(np.arange(-PRE, POST + 1) * FRAME_S))

    beh = b[b.kind == "behavioural"]
    summary = dict(threshold=BURST, err_cut=ERR_CUT, max_frames=MAX_FRAMES, classes={}, behavioural={})
    for (c, ph), g in b.groupby(["cohort", "phase"]):
        summary["classes"][f"{c}_{ph}"] = {k: int(v) for k, v in g.kind.value_counts().items()}
    for (c, ph), g in beh.groupby(["cohort", "phase"]):
        z = g[g.zone > 0]
        summary["behavioural"][f"{c}_{ph}"] = dict(
            n=int(len(g)), sessions=int(g.session_id.nunique()), in_zone=float((g.zone > 0).mean()),
            zone1=int((g.zone == 1).sum()), zone2=int((g.zone == 2).sum()),
            frames_median=float(g.frames.median()), duration_ms_median=float(g.duration_s.median() * 1000),
            peak_median=float(g.peak_speed.median()), peak_q90=float(g.peak_speed.quantile(.9)),
            displacement_median=float(g.displacement.median()),
            ball_rad_median=float(g.displacement.median() / FT.GAIN),
            pre_speed_median=float(g.pre_speed.median()), post_speed_median=float(g.post_speed.median()),
            since_entry_median_s=float(z.since_entry_s.median()) if len(z) else None,
            into_zone_median=float(z.into_zone.median()) if len(z) else None,
            left_zone=float(z.left_zone.astype(float).mean()) if len(z) else None,
            max_err_median=float(g.max_err.median()), err_before_median=float(g.err_before.median()))
    lt = beh[(beh.phase == "training") & (beh.zone > 0) & beh.light_on.notna()]
    summary["training_light"] = {
        c: dict(bursts=int(len(g)), light_on=int(g.light_on.sum()),
                volts_fraction_of_start_median=float((g.light_volts / g.light_start_volts)[g.light_on == 1].median()),
                elapsed_s_median=float(g.light_elapsed_s[g.light_on == 1].median()))
        for c, g in lt.groupby("cohort")}
    summary["sessions"] = {c: int(tr[tr.cohort == c].session_id.nunique()) for c in COHORTS}
    with open(os.path.join(OUT, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)

    with pd.option_context("display.width", 220, "display.max_rows", 200, "display.max_colwidth", 60):
        print(pd.DataFrame(summary["classes"]).T.fillna(0).astype(int).to_string())
        print(pd.DataFrame(summary["behavioural"]).T.round(2).to_string())
        print(ts.round(4).to_string())


if __name__ == "__main__":
    main()
