#!/usr/bin/env python3
"""A PDF (and HTML) of every figure for every dataset, with plain-language captions.

Reads ``runs/<set>/<task tag>/`` for each dataset in summary_stats.DATASETS, plus the
across-dataset reward figure, and prints the pages with headless Chromium (a snap that cannot
write into hidden folders, so --out must be a normal directory).

Run (after pipeline.py, reward_effect.py and summary_stats.py):
    python -m selected_analysis.report.gallery --runs runs --summary runs/summary/summary.json --out runs/summary
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import shutil
import subprocess

from .. import config
from PIL import Image

MAX_W = 1800
GLOSSARY = [
    ("Training", "the trials where the LED reward is on, so a reward-active fly is paid for staying in a patch."),
    ("Probing", "trials where the LED is off, so nothing is paid."),
    ("Reward-active", "flies fed ATR, so the optogenetic LED reward works. The no-ATR control flies cannot sense it."),
    ("Patch 1 and patch 2", "the two reward zones along the corridor (about 20-40 and 100-120)."),
    ("Time spent in patch", "how many seconds a fly stays inside one patch on one visit."),
    ("Reward value", "the LED brightness (volts) at the moment the fly leaves; it runs down while the fly stays."),
    ("Fraction of start reward", "reward value divided by its starting value in that patch."),
    ("Overall", "all the flies of one dataset taken together."),
    ("Paired p", "the chance of seeing a difference this big between a fly's two patches if there were none. Stars: * below 0.05, ** below 0.01, *** below 0.001, ns not significant."),
    ("Corrected p", "a p value adjusted for looking at several comparisons at once."),
]
# file under runs/<set>/<tag>/, title, how to read it
FIGS = [
    ("figures/occupancy_per_fly_lines.png", "Where flies spend their time along the corridor",
     "Each thin line is one fly and the thick line is the average over flies. Shaded bands are the two patches. Top: training. Bottom: probing."),
    ("figures/occupancy_training_probing.png", "Where flies spend their time: two example flies and everyone together",
     "Each row of a heatmap is one trial and the colour is the share of the trial spent at that position. Bottom: average over flies, training against probing."),
    ("figures/occupancy_example_heatmaps.png", "One example fly, trial by trial",
     "Colour is the number of camera frames at each position (logarithmic), left training, right probing."),
    ("figures/speed_by_position.png", "Walking speed along the corridor",
     "Thin lines are single flies, thick lines the average, for training and probing."),
    ("figures/speed_approach_patch2.png", "Speed on the way into patch 2",
     "Line = average over flies, band = 95% range from resampling flies. The label gives the p value for whether speed changes along the approach."),
    ("figures/fictrac_velocity.png", "Walking velocity measured from the ball",
     "Rotation of the ball along three axes while the fly moves down the corridor. Only sessions with ball-tracking data are included."),
    ("figures/leave_geometry.png", "How the reward runs out inside each patch",
     "The LED reward starts at its starting voltage and runs down at a fixed rate while the fly stays. Solid = patch 1, dashed = patch 2."),
    ("figures/dissociation.png", "When flies leave each patch",
     "Three views of the same departures: time spent in the patch, reward left on leaving, and fraction of the start reward left. Lines join one fly's two patches; the paired p compares patch 1 with patch 2."),
    ("leave_rule.png", "Which quantity is most alike between a fly's two patches",
     "For every fly, how different its two patches are in time, fraction of start reward and reward value (lower means more alike). Black = median over flies."),
    ("leave_rule_boxes.png", "The same comparison as box plots",
     "Only flies with at least 5 completed visits in each patch. Each dot is one fly."),
    ("figures/time_in_patch_repeatability.png", "Does a fly keep its place in the ranking?",
     "Median time in patch in the first half of the session against the second half. The dashed line means no change, so points below it are shorter later."),
    ("figures/reward_vs_control.png", "Reward-active flies against the no-ATR control",
     "Only for the earlier 50/50 task, the one dataset with a control of the same genotype. Bars are the average over flies with a 95% range, dots are single flies, the p value compares the two groups."),
    ("figures/model_comparison.png", "Predicting a new fly",
     "How well four models predict a fly they have not seen (bits per visit, higher is better). Stars compare neighbouring bars (corrected p). Right: how often the switching model changes strategy. Needs at least 5 flies."),
    ("learning_fatigue/time_in_patch_over_session.png", "Time spent in patch over the session",
     "Thin lines are single flies (5-trial running average), the bold line is the average over flies."),
    ("learning_fatigue/locomotion_over_session.png", "Walking over the session",
     "Speed, fraction of time walking and longest pause, trial by trial."),
    ("learning_fatigue/slope_training_vs_probing.png", "Change over the session, training against probing",
     "Each line is one fly; the black line is the average. A negative value means the quantity fell over the session."),
    ("learning_fatigue/baseline_vs_training.png", "Walking with no reward against training trials",
     "Fraction of time walking in the baseline trial and in the first and last 10 training trials."),
]


def data_uri(path):
    im = Image.open(path).convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CSS = """
@page { size: 11in 8.5in; margin: 0.45in }
body { font-family: Calibri, Carlito, 'Liberation Sans', Arial, sans-serif; color: #12303A; font-size: 11pt; line-height: 1.35 }
h1 { font-family: Cambria, Caladea, Georgia, serif; color: #156F76; font-size: 26pt; margin: 0 0 8pt }
h2 { font-family: Cambria, Caladea, Georgia, serif; color: #156F76; font-size: 19pt; margin: 0 0 4pt }
h3 { margin: 0 0 2pt; font-size: 13pt }
.cap { margin: 0 0 6pt; font-size: 10.5pt; color: #3d5258 }
.sec { page-break-before: always }
.fig { break-inside: avoid; page-break-inside: avoid; margin: 0 0 14pt; text-align: center }
.fig img { max-width: 100%; max-height: 5.6in; border: 1px solid #dfe6e4 }
.fig.small img { max-width: 4.6in }
.fig .t { text-align: left }
table { border-collapse: collapse; font-size: 10pt; margin: 6pt 0 }
td, th { padding: 2pt 8pt; border-bottom: 1px solid #dfe6e4; text-align: left }
th { background: #f3f7f6 }
a { color: #156F76; text-decoration: none }
.note { color: #8a4a2a; font-style: italic }
dl { margin: 0 } dt { font-weight: bold; float: left; clear: left; width: 1.9in } dd { margin: 0 0 3pt 2.0in }
"""


def build(runs, summ, out):
    ds = summ["datasets"]
    parts = ["<h1>Every figure for every dataset</h1>",
             f"<p>{len(ds)} datasets, {sum(d['flies'] for d in ds)} flies. Each section shows the same figures as the poster and a few more, "
             "one dataset at a time. Figures that need something a dataset lacks (a control of the same genotype, 5 or more flies, ball-tracking data) "
             "are left out and listed on the section's first page.</p>",
             "<h2>Words used</h2><dl>" + "".join(f"<dt>{html.escape(a)}</dt><dd>{html.escape(b)}</dd>" for a, b in GLOSSARY) + "</dl>",
             "<h2>Contents</h2><ol>" + "".join(f"<li><a href='#s{i}'>{html.escape(d['label'])}</a> ({d['flies']} flies)</li>"
                                               for i, d in enumerate(ds)) + "<li><a href='#edges'>Around the patch edges (all datasets)</a></li></ol>"]
    for i, d in enumerate(ds):
        base = os.path.join(runs, d["path"])
        present = [(rel, t, c) for rel, t, c in FIGS if os.path.isfile(os.path.join(base, rel))]
        missing = [t for rel, t, c in FIGS if not os.path.isfile(os.path.join(base, rel))]
        dw = d["dwell"]
        parts.append(f"<div class='sec' id='s{i}'><h1>{html.escape(d['label'])}</h1>")
        parts.append(f"<p>{d['flies']} flies, {d['episodes']} patch visits. Median time spent in patch (training): "
                     f"patch 1 {dw.get('training_p1', float('nan')):.1f} s, patch 2 {dw.get('training_p2', float('nan')):.1f} s. "
                     f"Probing: patch 1 {dw.get('probing_p1', float('nan')):.1f} s, patch 2 {dw.get('probing_p2', float('nan')):.1f} s.</p>")
        if missing:
            parts.append("<p class='note'>Not available for this dataset: " + "; ".join(html.escape(m) for m in missing) + ".</p>")
        parts.append("</div>")
        for rel, t, c in present:
            small = rel.endswith(("leave_geometry.png", "leave_rule.png", "leave_rule_boxes.png", "baseline_vs_training.png"))
            parts.append(f"<div class='fig{' small' if small else ''}'><div class='t'><h3>{html.escape(d['label'])}: {html.escape(t)}</h3>"
                         f"<p class='cap'>{html.escape(c)}</p></div><img src='{data_uri(os.path.join(base, rel))}'></div>")
    edge = [("edge_profiles_by_patch.png", "Time around the four patch edges",
             "Share of trial time at each distance from the entrance (onset) and exit (offset) of patch 1 and patch 2, training above and probing below."),
            ("edge_accumulation.png", "Extra time added up around the four patch edges",
             "The same, added up from 15 units before each edge, over the edge's own baseline (the mean 15 to 9 units before it). A jump means extra time at that spot."),
            ("edge_window_plain.png", "Patch 1 against patch 2 around the edges",
             "Occupancy added up over -5 to +5 units around each edge, one number per fly (mean, s.e.m., single flies). Stars mark a patch 1 vs patch 2 pair that differs."),
            ("edge_window_baseline.png", "Patch 1 against patch 2 around the edges, own baseline taken off",
             "The same minus each fly's own usual share over those 11 units (mean 15 to 9 units before the edge).")]
    shown = [(n, t, c) for n, t, c in edge if os.path.isfile(os.path.join(out, n))]
    if shown:
        parts.append("<div class='sec' id='edges'><h1>Around the patch edges</h1><p>All datasets together, for the four edges. "
                     "Shaded band: 5 units either side of the edge.</p></div>")
        for n, t, c in shown:
            parts.append(f"<div class='fig'><div class='t'><h3>{html.escape(t)}</h3><p class='cap'>{html.escape(c)}</p></div>"
                         f"<img src='{data_uri(os.path.join(out, n))}'></div>")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Every figure for every dataset</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=config.RUNS)
    ap.add_argument("--summary", default=config.SUMMARY_JSON)
    ap.add_argument("--out", default=config.SUMMARY)
    ap.add_argument("--chromium", default=shutil.which("chromium-browser") or shutil.which("chromium"))
    a = ap.parse_args()
    with open(a.summary) as f:
        summ = json.load(f)
    src = os.path.join(a.out, "all_figures.html")
    pdf = os.path.join(a.out, "all_figures.pdf")
    with open(src, "w") as f:
        f.write(build(a.runs, summ, a.out))
    subprocess.run([a.chromium, "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={pdf}",
                    "--no-pdf-header-footer", src], check=True, capture_output=True)
    print("wrote", pdf, f"({os.path.getsize(pdf) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
