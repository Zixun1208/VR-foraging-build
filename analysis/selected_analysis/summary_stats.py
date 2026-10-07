#!/usr/bin/env python3
"""Cross-dataset numbers for the summary: one json from every ``runs/<set>/<tag>/`` folder.

Reads survival.csv, leave_rule.csv, figures/time_in_patch_repeatability_by_fly.csv and
learning_fatigue/{slopes,summary}.csv, so run the pipeline first. Also pools the per-fly
slopes (relative to each fly's median) over groups of datasets, with an exact/randomised
signed-rank sign-flip test. Used by summary_md.py and the slide builder.

Run:
    python summary_stats.py --runs runs --out runs/summary/summary.json
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from figures import signflip_p
from learning_fatigue import signed_ranks

# key, run folder, label, group, ATR-fed
DATASETS = [
    ("past_50_50", "past/50_50", "50/50 task", "Earlier experiments", True),
    ("past_50_50_nonatr", "past/50_50_non-atr", "50/50 task, no-ATR control", "Earlier experiments", False),
    ("past_50_50_nonatr_b", "past_nonatr_b/50_50_non-atr", "50/50 task, no-ATR control (second folder)", "Earlier experiments", False),
    ("past_20_20", "past/20_20", "20/20 task", "Earlier experiments", True),
    ("past_20_100", "past/20_100", "20/100 task", "Earlier experiments", True),
    ("past_60_100", "past/60_100", "60/100 task", "Earlier experiments", True),
    ("split_line", "split_line/50_50", "split line, 50/50 task", "Split line", True),
    ("OO", "OO/50_50", "OO line (Orco x Orco)", "1D lines", True),
    ("GO", "GO/50_50", "GO line (Orco x Gr64)", "1D lines", True),
    ("GG", "GG/50_50", "GG line (Gr64 x Gr64)", "1D lines", True),
]
POOLS = {
    "earlier_atr": ["past_50_50", "past_20_20", "past_20_100", "split_line"],
    "lines_1d": ["OO", "GO", "GG"],
}
SERIES = (("dwell", "both"), ("speed", "all"), ("moving_frac", "all"), ("longest_stall", "all"))
MIN_FLIES = 3


def one(runs, key, rel, label, group, atr):
    d = os.path.join(runs, rel)
    s = pd.read_csv(os.path.join(d, "survival.csv"))
    v = s.drop_duplicates("visit_id").copy()
    v["dwell"] = s.groupby("visit_id").t_bin.max().reindex(v.visit_id).to_numpy()
    med = v.groupby(["fly_id", "phase", "patch"]).dwell.median().groupby(["phase", "patch"]).median()
    lr = pd.read_csv(os.path.join(d, "leave_rule.csv"))
    out = {"key": key, "label": label, "group": group, "atr": atr, "path": rel,
           "flies": int(s.fly_id.nunique()), "episodes": int(v.visit_id.nunique()),
           "dwell": {f"{ph}_p{p + 1}": float(med[(ph, p)]) for ph in ("training", "probing")
                     for p in (0, 1) if (ph, p) in med.index},
           "leave_best": {k: int((lr.best == k).sum()) for k in ("time", "fraction", "value")},
           "leave_spread": {k: float(lr[f"{k}_spread"].median()) for k in ("time", "fraction", "value")},
           "leave_n": int(len(lr)), "rho": {}, "slopes": {}}
    rp = os.path.join(d, "figures", "time_in_patch_repeatability_by_fly.csv")
    if os.path.isfile(rp) and os.path.getsize(rp) > 5:
        for ph, g in pd.read_csv(rp).groupby("phase"):
            if len(g) >= MIN_FLIES:
                out["rho"][ph] = {"rho": float(g.early.corr(g.late, method="spearman")),
                                  "n": int(len(g))}
    mc = os.path.join(d, "figures", "model_comparison.csv")
    if os.path.isfile(mc):
        t = pd.read_csv(mc, index_col=0)
        out["models"] = {m: {"mean": float(t.loc[m, "mean"]), "sem": float(t.loc[m, "sem"])}
                         for m in ("shared", "switching", "fixed", "changing")}
        out["models"]["p_holm"] = {k: float(t.loc[k, "p_holm"]) for k in
                                   ("switching - shared", "fixed - switching", "changing - fixed")}
    sp, mp = (os.path.join(d, "learning_fatigue", f) for f in ("slopes.csv", "summary.csv"))
    if os.path.isfile(mp) and os.path.getsize(mp) > 5:
        sm = pd.read_csv(mp)
        for metric, patch in SERIES:
            for ph in ("training", "probing"):
                r = sm[(sm.metric == metric) & (sm.patch == patch) & (sm.test == ph)]
                if len(r):
                    r = r.iloc[0]
                    out["slopes"][f"{metric}_{ph}"] = {
                        "n": int(r.n_flies), "n_negative": int(r.n_negative),
                        "median": float(r.median_slope), "p_rank": float(r.p_rank),
                        "p_rank_holm": float(r.p_rank_holm)}
    return out


def pooled(runs, keys, atr_sets):
    res = {}
    parts = []
    for k in keys:
        rel = next(r for kk, r, *_ in atr_sets if kk == k)
        parts.append(pd.read_csv(os.path.join(runs, rel, "learning_fatigue", "slopes.csv")).assign(ds=k))
    sl = pd.concat(parts)
    for metric, patch in SERIES:
        for ph in ("training", "probing"):
            g = sl[(sl.metric == metric) & (sl.patch == patch) & (sl.phase == ph)].rel_slope.dropna()
            if len(g) >= MIN_FLIES:
                res[f"{metric}_{ph}"] = {"n": int(len(g)), "n_negative": int((g < 0).sum()),
                                         "median_rel": float(g.median()),
                                         "p": signflip_p(signed_ranks(g))}
    return res


def reward_results(runs, task_tag="50_50"):
    """Reward-active 50/50 datasets against the no-ATR control (see reward_effect.py)."""
    import reward_effect as rw
    by = {k: rel for k, rel, _, _, atr in DATASETS}
    ctrl = pd.concat([rw.per_fly(os.path.join(runs, by[k], "survival.csv")).rename(index=lambda i, k=k: f"{k}:{i}")
                      for k in rw.CONTROL_KEYS])
    res = {"control": {"n": int(len(ctrl)), "gmean": [rw.gmean_ci(ctrl[p])[0] for p in (0, 1)]}}
    tab = rw.per_fly(os.path.join(runs, by[rw.ACTIVE_KEY], "survival.csv"))
    a = np.exp(np.log(tab[[0, 1]]).mean(axis=1))
    c = np.exp(np.log(ctrl[[0, 1]]).mean(axis=1))
    res[rw.ACTIVE_KEY] = {"n": int(len(tab)), "gmean": [rw.gmean_ci(tab[p])[0] for p in (0, 1)], "p": rw.perm_p(a, c)}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/summary/summary.json")
    a = ap.parse_args()
    sets = [one(a.runs, *d) for d in DATASETS]
    out = {"datasets": sets,
           "pools": {name: pooled(a.runs, keys, DATASETS) for name, keys in POOLS.items()},
           "reward": reward_results(a.runs)}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
