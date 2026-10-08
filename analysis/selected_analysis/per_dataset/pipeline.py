#!/usr/bin/env python3
"""selected_analysis pipeline: selection json -> survival table -> leave rule -> figures.

One command per dataset. Every task with a selection under ``--raw-root`` is processed (or
just ``--task``); each gets its own folder:

    runs/<name>/<task tag>/
        survival.csv
        leave_rule.csv  leave_rule.png
        figures/*.png
        learning_fatigue/*.csv  *.png

Steps (``--steps`` picks a subset; each reads the previous step's files from disk, so you
can re-run one alone):

    survival    build_survival.py   kept trials -> episode-bin table
    leave_rule  leave_rule.py       per-fly time / fraction / value spread across patches
    figures     figures.py          the poster's figures (ATR tasks only)
    learning_fatigue  learning_fatigue.py  time in patch and walking over the session (ATR only)
    models      models.py           predicting a new fly: shared / switching / fixed / changing models
                                    (needs 5+ flies; the poster's model comparison)

Run:
    python -m selected_analysis.per_dataset.pipeline --raw-root ~/Raw_data_by_task/"split line" --name split_line
    python -m selected_analysis.per_dataset.pipeline --raw-root ~/Raw_data --name all --task <task folder> --steps figures
    python -m selected_analysis.per_dataset.pipeline --raw-root ... --name x --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

from .. import config
from . import build_survival
from . import figures
from . import leave_rule
from . import learning_fatigue
from . import models
from ..core import selection
from ..core import trials
STEPS = ("survival", "leave_rule", "figures", "learning_fatigue", "models")


def tasks_found(raw_root, kind, dates=None):
    """{task: n_sessions} for every task with a selection of ``kind``."""
    found: dict[str, int] = {}
    for s in selection.iter_selected(raw_root, kind, dates=dates):
        found[s.task] = found.get(s.task, 0) + 1
    return dict(sorted(found.items()))


def run_task(raw_root, task, kind, dates, out, steps, min_leaves):
    surv = os.path.join(out, "survival.csv")
    if "survival" in steps:
        rows = build_survival.build(raw_root, task, kind, dates)
        if not rows:
            print("  survival: no selected episodes -- skipping this task")
            return False
        build_survival.write_csv(rows, surv)
        print(f"  survival: {len(rows)} bins, {len({r['visit_id'] for r in rows})} episodes, "
              f"{len({r['fly_id'] for r in rows})} flies")
    elif not os.path.isfile(surv):
        print(f"  {surv} missing; run the 'survival' step first")
        return False

    if "leave_rule" in steps:
        res = leave_rule.run(surv, out, min_leaves, name="leave_rule")
        if res is None:
            print("  leave_rule: no fly has enough completed visits in both patches")
        else:
            print(f"  leave_rule: {len(res)} flies; most consistent variable "
                  f"{res.best.value_counts().to_dict()}")

    if "figures" in steps:
        if not figures.run(raw_root, task, kind, surv, os.path.join(out, "figures")):
            print("  figures: no ATR sessions for this task -- skipped")

    if "learning_fatigue" in steps:
        lf_out = os.path.join(out, "learning_fatigue")
        if not learning_fatigue.run(raw_root, task, kind, surv, lf_out):
            print("  learning_fatigue: no ATR sessions for this task -- skipped")

    if "models" in steps:
        res = models.run(raw_root, task, kind, os.path.join(out, "figures"), dates=dates)
        if res is None:
            print(f"  models: fewer than {models.MIN_FLIES} flies -- skipped")
        else:
            print("  models: bits per visit " + ", ".join(f"{m} {res.loc[m, 'mean']:+.2f}" for m in models.MODELS))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw-root", default=selection.RAW_ROOT,
                    help="<root>/<date>/<task>/<sub>/ tree (default %(default)s)")
    ap.add_argument("--name", required=True, help="run name; outputs go to runs/<name>/")
    ap.add_argument("--task", help="one task folder name (default: every task found)")
    ap.add_argument("--selection", choices=("recommended", "applied"), default="recommended")
    ap.add_argument("--dates", nargs="*", help="restrict to these YYYY-MM-DD dates")
    ap.add_argument("--steps", default=",".join(STEPS),
                    help=f"comma list from {STEPS} (default: all)")
    ap.add_argument("--min-leaves", type=int, default=3,
                    help="completed visits per patch for a fly to enter leave_rule")
    ap.add_argument("--out-root", default=config.RUNS)
    ap.add_argument("--dry-run", action="store_true", help="list what would run, write nothing")
    a = ap.parse_args()

    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in STEPS]
    if bad:
        sys.exit(f"unknown step(s) {bad}; choose from {STEPS}")
    dates = set(a.dates) if a.dates else None

    found = tasks_found(a.raw_root, a.selection, dates)
    if a.task:
        found = {a.task: found.get(a.task, 0)}
    if not any(found.values()):
        sys.exit(f"no {a.selection} selections found under {a.raw_root}")

    print(f"{a.selection} selections under {a.raw_root}")
    for task, n in found.items():
        try:
            tag = trials.task_tag(task)
        except ValueError:
            print(f"- {task}: not a notated task name, skipped")
            continue
        out = os.path.join(a.out_root, a.name, tag)
        print(f"- {task}: {n} session(s) -> {out}")
        if a.dry_run or not n:
            continue
        os.makedirs(out, exist_ok=True)
        run_task(a.raw_root, task, a.selection, dates, out, steps, a.min_leaves)


if __name__ == "__main__":
    main()
