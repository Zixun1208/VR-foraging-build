#!/usr/bin/env python3
"""Write ``foraging_summary.md`` (+ ``figs/``) from summary.json and the run folders.

Tables and the model / reward sentences are generated from the json; the rest of the prose
is written by hand against those numbers, so re-read it after re-running on new data.
Wording is plain on purpose: "time spent in patch", "overall", no jargon.

Run:
    python summary_stats.py --runs runs --out runs/summary/summary.json
    python summary_md.py --runs runs --summary runs/summary/summary.json --out runs/summary
"""
from __future__ import annotations

import argparse
import json
import os

from PIL import Image

from gallery import FIGS, GLOSSARY

MAX_W = 1300
NAMES = {"shared": "one shared rule", "switching": "switching strategies",
         "fixed": "fixed differences between flies", "changing": "slowly changing"}

INTRO = """Every foraging dataset on disk, run through one pipeline (`analysis/selected_analysis`):
the trials that were kept, one table of patch visits, what decides when a fly leaves, the poster
figures, and how each fly changes over the session. Ten datasets, 76 flies. The trials come from
the preprocessing tool's recommendation (split line), from the selection saved in each session
folder (earlier experiments), or from a recommendation generated for the three 1D lines, which
had none."""

TAKEAWAYS = [
    "**Flies spend time at the patches in training, not in probing.** In training (LED reward on) "
    "every reward-active dataset with enough flies has a peak of time at the patch entrances "
    "(corridor position about 20 and 100). The exception is the OO line, whose peaks sit at the "
    "patch exits (about 40 and 122). Probing (reward off) is close to flat. The no-ATR control "
    "flies (3 flies) show no peaks and spend less time inside the patches.",
    "**On the 20/100 task, flies leave each patch after a similar time.** The 20/100 task is the one "
    "task where elapsed time, reward value and fraction of the start reward can be told apart, because "
    "its patches run out after 20 s and 100 s. There, 9 of 9 flies were most alike between their two "
    "patches in elapsed time (difference 0.24, against 1.66 for the other two). On the 50/50 tasks time "
    "and fraction of the start reward are nearly the same thing, so which one comes out closest for a "
    "fly depends on how long it stays, not on what it goes by: a fly that leaves early has a fraction "
    "near 1 in both patches, which makes the patches look alike, while flies that leave late or "
    "stay exactly as long in both patches favour time. Reward value is ruled out on every task.",
    "**Time spent in a patch shortens and walking speeds up over a session.** Overall, across the "
    "four earlier reward-active datasets (44 flies), time in patch falls in 33 of 44 flies in "
    "training and 35 of 41 in probing, and speed rises in 38 of 44 and 37 of 41 (paired test: "
    "p < 0.001 for all four). The three 1D "
    "lines show the same (speed rises in 23 of 26 flies).",
    "**The shortening is not specific to reward.** It is at least as large in probing, where no "
    "reward is given, as in training. That fits a general change in the fly over the session "
    "better than learning the reward schedule.",
    "**Tiredness, learning and restlessness are not separated by these data.** The flies die soon "
    "after a session, so faster walking and earlier leaving could be a declining fly becoming "
    "restless. Knowing when each fly died, and running the empty baseline and open-loop trials, "
    "would separate them.",
    "**Flies differ a lot in scale between datasets.** Median time in patch in training runs from "
    "about 7 s (OO line) to 20-29 s (the earlier 50/50 and 20/100 tasks), so absolute times "
    "should not be compared between datasets without care.",
]

EDGE_NOTE_PROFILE = ("Share of trial time at each distance from the entrance (onset) and exit (offset) of each patch, "
                     "training above and probing below. Positive distance is into the patch at an entrance and past the patch at an exit; "
                     "the shaded band is 5 units either side of the edge.")
EDGE_NOTE = ("The jump comes at the edge itself, then time keeps adding up more slowly. Reward-active flies add roughly 5 to 12% of trial time within 5 units after an entrance, and the split line builds up more slowly. The OO line adds time after the exits instead (about 7 to 8% by 5 units). Probing is flat and noisy, and the no-ATR control shows no entrance jump. Baseline for each edge is the mean share 15 to 9 units before it, so a flat line means no extra time.")

CAVEATS = [
    "Small numbers: 1 to 15 flies per dataset, and the exact test cannot go below p = 0.002 with "
    "10 flies. The 60/100 task has one fly and the second no-ATR folder has two.",
    "The overall (combined) test treats flies as independent and ignores differences between "
    "tasks and experiments. Treat it as a consistency check.",
    "Time and fraction of the start reward cannot be told apart on the 50/50 and 20/20 tasks.",
    "Probing has 20 to 30 trials against 60 in training depending on the dataset, so changes over "
    "the session are expressed as the change across the whole of training or probing.",
    "The earlier experiments use the selection saved in each session folder. It carries no ATR "
    "label, so the no-ATR controls are identified only by folder name, and the 1D lines were "
    "assumed to be fed ATR.",
    "Trials longer than 900 s (a stalled fly or a rig left running) are dropped, as in the earlier "
    "analysis. That is about 1% of trials, but it removes 11 of one 50/50-task fly's roughly 35 trials.",
    "Three trial files in the earlier 50/50 data could not be read (input/output error) and were "
    "skipped. If that disk is unreliable, those sessions may be incomplete.",
    "Ball-tracking figures are missing for most datasets: no session has ball-tracking "
    "frames that overlap the camera log.",
    "The model comparison uses the same inputs for every dataset but is not tuned per dataset, and "
    "its numbers are not directly comparable with the poster's.",
    "The 1D lines are named as in the info file (GG = Gr64 x Gr64, OO = Orco x Orco, GO = Orco x "
    "Gr64). Whether each is a mutant or a control is not in the data, and nothing here is "
    "interpreted genetically.",
]


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def pfmt(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def extra_takeaways(summ):
    out = []
    rw = summ.get("reward", {})
    if "past_50_50" in rw:
        v = rw["past_50_50"]
        out.append("**Reward-active flies against the no-ATR control.** Only the earlier 50/50 task has a control of the "
                   "same genotype, so only that comparison is made. Average time in patch in training (patch 1 / patch 2): "
                   f"reward-active {v['gmean'][0]:.0f} s / {v['gmean'][1]:.0f} s ({v['n']} flies), control "
                   f"{rw['control']['gmean'][0]:.0f} s / {rw['control']['gmean'][1]:.0f} s ({rw['control']['n']} flies); "
                   f"group difference p = {v['p']:.3f}. The control group is small, so this is suggestive, not firm.")
    ms = [(d["label"], d["models"]) for d in summ["datasets"] if "models" in d]
    if ms:
        wins = [lab for lab, m in ms if m["p_holm"]["switching - shared"] < 0.05]
        best = {}
        for lab, m in ms:
            best.setdefault(NAMES[max(NAMES, key=lambda k: m[k]["mean"])], []).append(lab)
        out.append("**Predicting a new fly.** Of the " f"{len(ms)} datasets with 5 or more flies, the switching-strategies model "
                   f"predicted unseen flies better than one shared rule in {len(wins)} "
                   f"({', '.join(wins) if wins else 'none'}). Which model did best overall differs by dataset: "
                   + "; ".join(f"{k} in {len(v)}" for k, v in best.items()) +
                   ". No single model wins everywhere, so the data do not clearly need hidden strategies.")
    return out


def tables(summ):
    ds = summ["datasets"]
    t1 = ["| dataset | flies | patch visits | time in patch, training: patch 1 / patch 2 (s) | probing: patch 1 / patch 2 (s) | most alike between patches: time / fraction / value | median difference between patches: time / fraction / value |",
          "|---|---|---|---|---|---|---|"]
    for d in ds:
        dw, lb, ls = d["dwell"], d["leave_best"], d["leave_spread"]
        t1.append(f"| {d['label']} | {d['flies']} | {d['episodes']} | "
                  f"{f1(dw.get('training_p1'))} / {f1(dw.get('training_p2'))} | "
                  f"{f1(dw.get('probing_p1'))} / {f1(dw.get('probing_p2'))} | "
                  f"{lb['time']} / {lb['fraction']} / {lb['value']} flies | "
                  f"{ls['time']:.2f} / {ls['fraction']:.2f} / {ls['value']:.2f} |")
    t2 = ["| dataset | training: time in patch falls | training: speed rises | probing: time in patch falls | probing: speed rises | rank correlation, first vs second half (training / probing) |",
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
            return f"{k} of {x['n']} flies (corrected p {x['p_rank_holm']:.2f})"
        rho = " / ".join(f"{d['rho'][p]['rho']:.2f}" if p in d["rho"] else "-" for p in ("training", "probing"))
        t2.append(f"| {d['label']} | {cell('dwell_training')} | {cell('speed_training', True)} | "
                  f"{cell('dwell_probing')} | {cell('speed_probing', True)} | {rho} |")
    names = {"earlier_atr": "overall, 50/50, 20/20, 20/100 and split line", "lines_1d": "overall, OO, GO and GG"}
    metric = {"dwell": "time in patch", "speed": "speed", "moving_frac": "fraction of time walking",
              "longest_stall": "longest pause"}
    t3 = ["| flies | phase | quantity | flies | rising / falling | median change (fraction of the fly's usual value) | p |", "|---|---|---|---|---|---|---|"]
    for pool, res in summ["pools"].items():
        for key, x in res.items():
            m, ph = key.rsplit("_", 1)
            t3.append(f"| {names[pool]} | {ph} | {metric[m]} | {x['n']} | {x['n'] - x['n_negative']} / {x['n_negative']} | "
                      f"{x['median_rel']:+.2f} | {pfmt(x['p'])} |")
    t4 = ["| dataset | flies | one shared rule | switching strategies | fixed differences | slowly changing | switching vs shared (corrected p) |", "|---|---|---|---|---|---|---|"]
    for d in ds:
        if "models" in d:
            m = d["models"]
            t4.append(f"| {d['label']} | {d['flies']} | " + " | ".join(f"{m[k]['mean']:+.2f}" for k in NAMES) +
                      f" | {pfmt(m['p_holm']['switching - shared'])} |")
    return "\n".join(t1), "\n".join(t2), "\n".join(t3), "\n".join(t4)


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
    t1, t2, t3, t4 = tables(summ)
    take = TAKEAWAYS + extra_takeaways(summ)
    md = ["# Patch leaving across all foraging datasets", "", INTRO, "", "## Words used", ""]
    md += [f"- **{k}**: {v}" for k, v in GLOSSARY] + ["", "## Takeaways", ""]
    md += [f"{i}. {t}" for i, t in enumerate(take, 1)]
    md += ["", "## Datasets and headline numbers", "",
           "Time in patch is the median over flies of each fly's median visit. 'Most alike between patches' "
           "counts the flies whose two patches were closest in that quantity.", "", t1, "",
           "## Change over the session, per dataset", "",
           "Counts are flies whose time in patch (or speed) went the stated way from the start to the end of "
           "training or probing. The corrected p value allows for all the tests made on that dataset. The rank "
           "correlation says how well flies keep their place in the ranking from the first to the second half "
           "of the session.", "", t2, "", "## Change over the session, overall", "",
           "Each fly's change as a fraction of its own usual value, put together over the flies named; "
           "paired test across flies.", "", t3, "", "## Predicting a new fly", "",
           "Bits per visit by which each model predicts a fly it has not seen better than a single average "
           "(higher is better). Only datasets with 5 or more flies.", "", t4, ""]
    for name, title in (("edge_profiles_by_patch.png", "Time around the four patch edges"),
                        ("edge_accumulation.png", "Extra time added up around the four patch edges")):
        if os.path.isfile(os.path.join(a.out, name)):
            copy_fig(os.path.join(a.out, name), os.path.join(a.out, "figs", name))
            md += [f"## {title}", "", EDGE_NOTE if "accumulation" in name else EDGE_NOTE_PROFILE, "", f"![{title}](figs/{name})", ""]
    for d in summ["datasets"]:
        md += [f"## {d['label']}", "", f"{d['flies']} flies, {d['episodes']} patch visits.", ""]
        for rel, title, cap in FIGS:
            src = os.path.join(a.runs, d["path"], rel)
            if os.path.isfile(src):
                dst = f"{d['key']}__{os.path.basename(rel)}"
                copy_fig(src, os.path.join(a.out, "figs", dst))
                md += [f"**{title}.** {cap}", "", f"![{d['label']}: {title}](figs/{dst})", ""]
    md += ["## Caveats", ""] + [f"- {c}" for c in CAVEATS] + [""]
    path = os.path.join(a.out, "foraging_summary.md")
    with open(path, "w") as f:
        f.write("\n".join(md))
    print("wrote", path)


if __name__ == "__main__":
    main()
