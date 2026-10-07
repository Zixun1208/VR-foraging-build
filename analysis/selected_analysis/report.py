#!/usr/bin/env python3
"""One self-contained HTML report from ``runs/<dataset>/<task tag>/`` outputs.

Figures are embedded (downscaled PNG), tables are computed here from the run folders, so the
file can be copied anywhere. The prose lives in ``FINDINGS`` below; edit it with the data.

Run:
    python report.py --runs runs --task-tag 50_50 --out runs/report.html \
        OO:"OO (Orco x Orco)" GO:"GO (Orco x Gr64)" GG:"GG (Gr64 x Gr64)" \
        split_line:"split line (earlier cohort)"
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import os

import numpy as np
import pandas as pd
from PIL import Image

MAX_W = 1500

FIGURES = [
    ("Where flies spend time", "figures/occupancy_training_probing.png",
     "Example flies' trial-by-position occupancy and the population profile. Shaded = patches."),
    ("Speed along the corridor", "figures/speed_by_position.png", ""),
    ("Leave point by patch", "figures/dissociation.png",
     "Time, LED value and fraction of the start value at the moment the fly leaves each patch."),
    ("Which variable the fly leaves by", "leave_rule.png",
     "Across-patch spread per fly; the smallest spread is the variable the fly is most consistent in."),
    ("Early vs late dwell", "figures/dwell_repeatability.png",
     "Median dwell, first against second half of the session, per fly."),
    ("Dwell over the session", "learning_fatigue/dwell_over_session.png", ""),
    ("Locomotion over the session", "learning_fatigue/locomotion_over_session.png", ""),
    ("Slope, training vs probing", "learning_fatigue/slope_training_vs_probing.png",
     "Change across the phase, per fly. Mean is outlier-sensitive; read with summary.csv."),
]

FINDINGS = """
<ul>
<li><b>Training builds patch-specific occupancy; probing does not.</b> In all three new lines
the population occupancy profile has peaks at the patches during training and is flat during
probing. Where the peak sits differs: OO flies pile up at the patch <i>exits</i> (x about 40
and 122), GG and GO flies at the patch <i>entries</i> (x about 20 and 100). GG peaks are the
strongest (about 7.5% of time per bin), GO about 4-5%, OO about 3%.</li>
<li><b>Leave rule.</b> Flies are most consistent in the <i>fraction</i> of the start value
(or time) at which they leave, and not in absolute LED value (across-patch spread about 0.85).
On this 50/50 task time and fraction are confounded by design, so the data cannot say which of
the two the fly uses.</li>
<li><b>Dwell differs by line.</b> Median training dwell: OO about 7-8 s, GO about 14 s, GG
14-20 s, against about 14-15 s in the earlier cohort. GG probing dwell stays long
(about 17-18 s) where the other lines fall to 6-9 s.</li>
<li><b>Rank order of flies is not consistently preserved</b> (early vs late median dwell):
training rho 0.72 (OO), -0.19 (GO), 0.23 (GG); probing 0.31, 0.68, 0.77. With 6-10 flies these
are weak estimates; none is an established line difference.</li>
<li><b>Changes over the session.</b> Walking speed rises across the session in nearly every
fly in all three lines (OO 10/10 in both phases; GO and GG 8/10 and 5/6). After Holm correction
only OO is significant (0.041); GO and GG have too few flies for the exact test to reach it.
The earlier cohort also rose (12/12). Dwell falls in training in the earlier cohort (12/12,
Holm 0.010) but only weakly in OO (8/10, Holm 0.19) and not in GO (5/10) or GG. In OO
probing, dwell falls steeply (9/10 flies) because the first probing trials are long searches.
Because the flies die shortly after a session, rising speed with shorter dwell can reflect a
declining or hyperactive state as well as learning; these data do not separate the two.</li>
</ul>
"""

CAVEATS = """
<ul>
<li>Trial selection is the <code>foraging_preprocess</code> recommendation, generated here
for the new data (no selection existed). It kept almost every trial.</li>
<li>The new data were treated as ATR-fed (the preprocess default); the info file does not say.</li>
<li>Sessions: GG sub-7 had no trials and was skipped; GO sub-2, GG sub-1 and GG sub-5 are
partial (52, 41 and 47 training trials).</li>
<li>Probing has 20 trials (training 60) in the new data, so slopes are expressed as change
across the phase, not per trial.</li>
<li>FicTrac figures were skipped: no session has FicTrac frames overlapping the camera log.</li>
<li>n is 6-10 flies per line and many p-values are floors of the exact test (about 0.002 for
n = 10). Holm-corrected values are in each run's <code>learning_fatigue/summary.csv</code>.</li>
<li>Time spent in a patch is in 1 s bins from the survival table, so dwell is quantised.</li>
</ul>
"""


def data_uri(path):
    im = Image.open(path)
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def dwell_table(d):
    s = pd.read_csv(os.path.join(d, "survival.csv"))
    v = s.drop_duplicates("visit_id").copy()
    v["dwell"] = s.groupby("visit_id").t_bin.max().reindex(v.visit_id).to_numpy()
    med = v.groupby(["fly_id", "phase", "patch"]).dwell.median().groupby(["phase", "patch"]).median()
    lr = pd.read_csv(os.path.join(d, "leave_rule.csv"))
    r = pd.read_csv(os.path.join(d, "figures", "dwell_repeatability_by_fly.csv")) \
        if os.path.isfile(os.path.join(d, "figures", "dwell_repeatability_by_fly.csv")) else None
    rho = {ph: g.early.corr(g.late, method="spearman") for ph, g in r.groupby("phase")} if r is not None else {}
    return {
        "flies": s.fly_id.nunique(), "episodes": v.visit_id.nunique(),
        "train p1/p2": f"{med[('training', 0)]:.1f} / {med[('training', 1)]:.1f}",
        "probe p1/p2": f"{med[('probing', 0)]:.1f} / {med[('probing', 1)]:.1f}",
        "leave rule (time/fraction/value)": "{}/{}/{}".format(
            *(int((lr.best == k).sum()) for k in ("time", "fraction", "value"))),
        "rho train": f"{rho.get('training', np.nan):.2f}", "rho probe": f"{rho.get('probing', np.nan):.2f}",
    }


def slope_table(d):
    sl = pd.read_csv(os.path.join(d, "learning_fatigue", "slopes.csv"))
    sm = pd.read_csv(os.path.join(d, "learning_fatigue", "summary.csv"))
    rows = []
    for metric, patch in (("dwell", "both"), ("speed", "all"), ("moving_frac", "all"),
                          ("longest_stall", "all")):
        for ph in ("training", "probing"):
            g = sl[(sl.metric == metric) & (sl.patch == patch) & (sl.phase == ph)].slope.dropna()
            row = sm[(sm.metric == metric) & (sm.patch == patch) & (sm.test == ph)]
            if len(g) and len(row):
                rows.append({"metric": metric, "phase": ph, "n": len(g),
                             "median change": f"{g.median():+.3g}",
                             "flies with negative slope": f"{int((g < 0).sum())}/{len(g)}",
                             "p (signed-rank)": f"{row.p_rank.iloc[0]:.3f}",
                             "Holm": f"{row.p_rank_holm.iloc[0]:.3f}"})
    return pd.DataFrame(rows)


def table(df, index=False):
    return df.to_html(index=index, border=0, classes="t", escape=True)


def build(runs, tag, sets):
    css = ("body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;"
           "color:#1b2a2f;line-height:1.5}h1,h2,h3{color:#156f76}img{max-width:100%;border:1px solid #dfe6e4}"
           ".t{border-collapse:collapse;font-size:.9em;margin:.5em 0}.t td,.t th{padding:3px 10px;"
           "border-bottom:1px solid #dfe6e4;text-align:right}.t th{background:#f3f7f6}"
           "figure{margin:1em 0}figcaption{font-size:.85em;color:#52666b}code{background:#f3f7f6}")
    out = [f"<html><head><meta charset='utf-8'><title>Foraging lines report</title><style>{css}</style></head><body>",
           "<h1>Patch-leaving analysis across lines</h1>",
           "<p>50/50 task (patches 20-40 and 100-120, 1.0 V and 2.5 V, 50 s decay). "
           "Datasets: " + ", ".join(html.escape(lab) for _, lab in sets) + ".</p>",
           "<h2>Findings</h2>", FINDINGS, "<h2>Summary table</h2>"]
    rows = {lab: dwell_table(os.path.join(runs, k, tag)) for k, lab in sets}
    out.append("<p>Median dwell (s) per patch is the median over flies of each fly's median visit.</p>")
    out.append(table(pd.DataFrame(rows).T.rename_axis("dataset").reset_index()))
    out.append("<h2>Changes over the session</h2><p>Per-fly slope against position in the phase, "
               "tested across flies (exact signed-rank sign-flip, Holm over all tests of that dataset).</p>")
    for k, lab in sets:
        out.append(f"<h3>{html.escape(lab)}</h3>" + table(slope_table(os.path.join(runs, k, tag))))
    for title, rel, note in FIGURES:
        out.append(f"<h2>{html.escape(title)}</h2>")
        if note:
            out.append(f"<p>{html.escape(note)}</p>")
        for k, lab in sets:
            p = os.path.join(runs, k, tag, rel)
            if os.path.isfile(p):
                out.append(f"<figure><figcaption><b>{html.escape(lab)}</b></figcaption>"
                           f"<img src='{data_uri(p)}'></figure>")
    out += ["<h2>Caveats and methods</h2>", CAVEATS, "</body></html>"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--task-tag", default="50_50")
    ap.add_argument("--out", default="runs/report.html")
    ap.add_argument("sets", nargs="+", help="run_name:Label")
    a = ap.parse_args()
    sets = [tuple(s.split(":", 1)) for s in a.sets]
    with open(a.out, "w") as f:
        f.write(build(a.runs, a.task_tag, sets))
    print(f"wrote {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
