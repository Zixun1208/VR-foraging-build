#!/usr/bin/env python3
"""Write ``foraging_summary.md`` (+ ``figs/``) from summary.json and the run folders.

Tables are generated from the json; the prose in ``PROSE`` is written by hand against those
numbers, so re-read it after re-running on new data.

Run:
    python summary_stats.py --runs runs --out runs/summary/summary.json
    python summary_md.py --runs runs --summary runs/summary/summary.json --out runs/summary
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image

MAX_W = 1300
FIGS = [("occupancy", "figures/occupancy_training_probing.png", "Occupancy by corridor position"),
        ("leave_point", "figures/dissociation.png", "Leave point by patch"),
        ("leave_rule", "leave_rule.png", "Leave rule (across-patch spread)"),
        ("dwell_session", "learning_fatigue/dwell_over_session.png", "Dwell over the session"),
        ("locomotion", "learning_fatigue/locomotion_over_session.png", "Locomotion over the session")]

PROSE = {
    "intro": """Patch-leaving analysis of every foraging dataset on disk, run through one pipeline
(`analysis/selected_analysis`): kept trials -> per-visit survival table -> leave rule ->
poster figures -> per-fly drift over the session. Ten datasets, 76 flies. Trial selection is
the `foraging_preprocess` recommendation where it existed (split line) or the applied
selection in the session folder (earlier cohorts); for the three 1D lines no selection existed,
so the recommendation was generated for them.""",
    "takeaways": [
        "**Training builds patch-specific occupancy; probing mostly does not.** Every ATR-fed dataset "
        "with enough flies shows occupancy peaks at the patch entries (x about 20 and 100) in training; "
        "the exception is OO, whose peaks sit at the patch exits (x about 40 and 122). Probing is "
        "close to flat, with a little residual occupancy in some datasets (20/100, earlier 50/50). "
        "The non-ATR control (3 flies) has no peaks and dips inside the patches.",
        "**Flies leave by elapsed time, where the task can tell.** On the 20/100 task, the one task "
        "where time, value and fraction come apart, 9/9 flies are most consistent in time "
        "(across-patch spread 0.24, against 1.66 for fraction and for value). On the 50/50 tasks "
        "time and fraction are confounded by design, so 'fraction' winning there says little.",
        "**Dwell shortens and walking speeds up over a session, across datasets.** Pooling the four "
        "earlier ATR cohorts (44 flies), dwell falls in 33/44 flies in training and 33/42 in probing, "
        "and speed rises in 35/44 and 37/42 (signed-rank, p < 0.001 for speed and probing dwell, "
        "p = 0.005 for training dwell). The 1D lines show the same (speed rises in 23/26 flies).",
        "**The fall in dwell is not reward-specific.** It is at least as large in probing, where no LED "
        "reward is delivered, as in training. That fits a general change of state over the session "
        "better than learning the reward schedule.",
        "**Fatigue, learning and hyperactivity are not separated by these data.** The flies die soon "
        "after a session, so faster walking and earlier leaving can be a declining or hyperactive "
        "state. Lifespan or time-of-death per fly, and the empty open-loop trials, are what would "
        "separate them.",
        "**Cohorts differ a lot in scale.** Median training dwell runs from about 7 s (OO) to "
        "20-29 s (earlier 50/50 and 20/100 cohorts), so absolute dwell should not be compared "
        "across cohorts without care.",
    ],
    "caveats": [
        "n is small: 1-15 flies per dataset, and the exact test floors at p = 0.002 for 10 flies. "
        "The 60/100 task has one fly; the second non-ATR folder has two (no slope tests).",
        "Pooling across tasks treats flies as independent and uses slopes relative to each fly's "
        "median; it ignores differences between tasks and cohorts. Treat it as a consistency check.",
        "Time and fraction of start value cannot be separated on the 50/50 and 20/20 tasks.",
        "Probing has 20-30 trials against 60 in training depending on the dataset, so slopes are "
        "expressed as change across the phase.",
        "Earlier cohorts use the applied selection json in each session; there is no recommendation "
        "block, so the ATR flag defaults to ATR-fed, and the non-ATR tasks are flagged only by name.",
        "Three trial files in the earlier 50/50 cohort could not be read (input/output error) and "
        "were skipped. If that disk is flaky, those sessions may be incomplete.",
        "FicTrac figures were skipped for most datasets: no FicTrac frames overlap the camera log.",
        "The 1D lines are labelled as in the info file (GG = Gr64 x Gr64, OO = Orco x Orco, "
        "GO = Orco x Gr64). Whether each is a mutant or a control is not in the data, and nothing "
        "here is interpreted genotypically.",
    ],
}


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def tables(summ):
    ds = summ["datasets"]
    t1 = ["| dataset | flies | visits | train dwell p1 / p2 (s) | probe dwell p1 / p2 (s) | leave rule best (time/fraction/value) | median spread (time/fraction/value) |",
          "|---|---|---|---|---|---|---|"]
    for d in ds:
        dw = d["dwell"]
        lb, ls = d["leave_best"], d["leave_spread"]
        t1.append(f"| {d['label']} | {d['flies']} | {d['episodes']} | "
                  f"{f1(dw.get('training_p1'))} / {f1(dw.get('training_p2'))} | "
                  f"{f1(dw.get('probing_p1'))} / {f1(dw.get('probing_p2'))} | "
                  f"{lb['time']}/{lb['fraction']}/{lb['value']} | "
                  f"{ls['time']:.2f}/{ls['fraction']:.2f}/{ls['value']:.2f} |")
    t2 = ["| dataset | train: dwell falls | train: speed rises | probe: dwell falls | probe: speed rises | rho early-late (train / probe) |",
          "|---|---|---|---|---|---|"]
    for d in ds:
        s = d["slopes"]
        if not s:
            continue

        def cell(key, rising=False):
            x = s.get(key)
            if not x:
                return "-"
            k = x["n"] - x["n_negative"] if rising else x["n_negative"]
            return f"{k}/{x['n']} (Holm {x['p_rank_holm']:.2f})"
        rho = " / ".join(f"{d['rho'][p]['rho']:.2f}" if p in d["rho"] else "-" for p in ("training", "probing"))
        t2.append(f"| {d['label']} | {cell('dwell_training')} | {cell('speed_training', True)} | "
                  f"{cell('dwell_probing')} | {cell('speed_probing', True)} | {rho} |")
    t3 = ["| pool | phase | metric | flies | rising / falling | median relative change | p |", "|---|---|---|---|---|---|---|"]
    names = {"earlier_atr": "earlier ATR cohorts (50/50, 20/20, 20/100, split line)",
             "lines_1d": "1D lines (OO, GO, GG)"}
    for pool, res in summ["pools"].items():
        for key, x in res.items():
            metric, ph = key.rsplit("_", 1)
            p = "< 0.001" if x["p"] < 0.001 else f"{x['p']:.3f}"
            t3.append(f"| {names[pool]} | {ph} | {metric} | {x['n']} | "
                      f"{x['n'] - x['n_negative']} / {x['n_negative']} | {x['median_rel']:+.2f} | {p} |")
    return "\n".join(t1), "\n".join(t2), "\n".join(t3)


def copy_fig(src, dst):
    im = Image.open(src)
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    im.save(dst, optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--summary", default="runs/summary/summary.json")
    ap.add_argument("--out", default="runs/summary")
    a = ap.parse_args()
    with open(a.summary) as f:
        summ = json.load(f)
    os.makedirs(os.path.join(a.out, "figs"), exist_ok=True)
    t1, t2, t3 = tables(summ)
    md = ["# Patch leaving across all foraging datasets", "", PROSE["intro"], "",
          "## Takeaways", ""] + [f"{i}. {t}" for i, t in enumerate(PROSE["takeaways"], 1)]
    md += ["", "## Datasets and headline numbers", "",
           "Median dwell is the median over flies of each fly's median visit. p1 / p2 are the two patches.",
           "", t1, "", "## Drift over the session, per dataset", "",
           "Counts are flies with the stated direction of slope; Holm is the signed-rank p corrected "
           "over all tests in that dataset. rho is the Spearman correlation of early- and late-session "
           "median dwell across flies.", "", t2, "", "## Pooled drift", "",
           "Per-fly slopes relative to each fly's median, pooled over the datasets named; exact/randomised "
           "signed-rank sign-flip test.", "", t3, ""]
    for d in summ["datasets"]:
        if d["flies"] < 3:
            continue
        md += [f"## {d['label']}", "",
               f"{d['flies']} flies, {d['episodes']} patch visits. Figures from `{d['path']}`.", ""]
        for name, rel, title in FIGS:
            src = os.path.join(a.runs, d["path"], rel)
            if os.path.isfile(src):
                dst = f"{d['key']}__{name}.png"
                copy_fig(src, os.path.join(a.out, "figs", dst))
                md += [f"**{title}**", "", f"![{d['label']} - {title}](figs/{dst})", ""]
    md += ["## Caveats", ""] + [f"- {c}" for c in PROSE["caveats"]] + [""]
    path = os.path.join(a.out, "foraging_summary.md")
    with open(path, "w") as f:
        f.write("\n".join(md))
    print("wrote", path)


if __name__ == "__main__":
    main()
