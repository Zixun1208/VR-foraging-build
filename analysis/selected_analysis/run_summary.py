#!/usr/bin/env python3
"""Everything across datasets, in order, after ``pipeline.py`` has been run on each dataset.

    1  summary_stats.py     runs/*/<tag>/ tables -> runs/summary/summary.json
    2  edges.py             time around the four patch edges, corridor running total (figures + csv)
    3  patch_trajectory.py  inside a patch: path length, speed, reversals (figures + patch_visits.csv)
    4  trial_view.py        whole-trial traces for one split-line fly and one 50/50 fly
    5  summary_md.py        foraging_summary.md
    6  make_slides.py       foraging_summary.pptx
    7  slides_pdf.py        foraging_summary.pdf   (headless Chromium)
    8  gallery.py           all_figures.pdf        (headless Chromium)

Steps 2 to 4 read trial files, so they need ``--stage``: the folder made by ``stage_lines.py`` and
``foraging_preprocess`` for the OO, GO and GG lines (<stage>/OO/<date>/<task>/<sub>/ with selection
json). Without it those datasets are silently missing from the figures, so it is required.

Run (from this folder):
    python run_summary.py --stage <stage dir>
    python run_summary.py --stage <stage dir> --only 2,3,5    # re-run some steps
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", required=True, help="folder holding OO/, GO/, GG/ with their selection json")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="runs/summary")
    ap.add_argument("--only", help="comma list of step numbers (default: all)")
    a = ap.parse_args()
    py = [sys.executable]
    steps = [
        (1, "summary_stats", ["summary_stats.py", "--runs", a.runs, "--out", f"{a.out}/summary.json"]),
        (2, "edges", ["edges.py", "--stage", a.stage, "--out", a.out]),
        (3, "patch_trajectory", ["patch_trajectory.py", "--stage", a.stage, "--out", a.out]),
        (4, "trial_view (split line)", ["trial_view.py", "--stage", a.stage, "--out", a.out,
                                        "--dataset", "split line", "--png", "trial_view_split_line.png"]),
        (4, "trial_view (50/50)", ["trial_view.py", "--stage", a.stage, "--out", a.out,
                                   "--dataset", "50/50 (Gr64f)", "--png", "trial_view_50-50.png"]),
        (5, "summary_md", ["summary_md.py", "--runs", a.runs, "--summary", f"{a.out}/summary.json", "--out", a.out]),
        (6, "make_slides", ["make_slides.py", "--dir", a.out]),
        (7, "slides_pdf", ["slides_pdf.py", "--dir", a.out]),
        (8, "gallery", ["gallery.py", "--runs", a.runs, "--summary", f"{a.out}/summary.json", "--out", a.out]),
    ]
    want = {int(x) for x in a.only.split(",")} if a.only else None
    os.makedirs(a.out, exist_ok=True)
    for n, name, cmd in steps:
        if want and n not in want:
            continue
        print(f"== {n} {name}", flush=True)
        subprocess.run(py + [os.path.join(HERE, cmd[0])] + cmd[1:], check=True, cwd=os.getcwd())


if __name__ == "__main__":
    main()
