"""One entry point for the whole analysis.

    python -m selected_analysis stage       [--recommend]        link the 1D line sessions (and write selections)
    python -m selected_analysis analyze     [--sets NAME ...]    per-dataset pipeline for every run set
    python -m selected_analysis summarize                        cross-dataset numbers + figures (edges, reward effect)
    python -m selected_analysis report                           summary.md, slides, PDFs and the all-figures gallery
    python -m selected_analysis all                              the four above, in order

Run from the folder that contains ``selected_analysis/`` (``analysis/``). Paths and the run sets
are in ``config.py``. Every stage skips what it cannot do and says so; ``--dry-run`` lists what
``analyze`` would process and writes nothing. Each module also runs on its own, e.g.
``python -m selected_analysis.per_dataset.figures --help``.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config

STAGES = ("stage", "analyze", "summarize", "report")


def do_stage(a):
    from .tools import stage_lines
    stage_lines.main(["--recommend"] if a.recommend else [])


def do_analyze(a):
    from .per_dataset import pipeline
    sets = a.sets or list(config.RUN_SETS)
    for name in sets:
        if name not in config.RUN_SETS:
            sys.exit(f"unknown set {name!r}; choose from {list(config.RUN_SETS)}")
    for name in sets:
        spec = config.RUN_SETS[name]
        print(f"\n=== {name}: {spec['root']}")
        if not os.path.isdir(spec["root"]):
            print("  not found -- skipped (for the 1D lines, run the 'stage' step first)")
            continue
        for task in spec["tasks"] or [None]:
            argv = ["--raw-root", spec["root"], "--name", name, "--selection", spec["selection"]]
            if task:
                argv += ["--task", task]
            if a.steps:
                argv += ["--steps", a.steps]
            if a.dry_run:
                argv.append("--dry-run")
            sys.argv = ["pipeline"] + argv
            try:
                pipeline.main()
            except SystemExit as e:
                if e.code not in (0, None):
                    print(f"  {e.code}")


def do_summarize(a):
    from .cross_dataset import edge_compare, edges, reward_effect, summary_stats
    for mod in (reward_effect, summary_stats):
        sys.argv = [mod.__name__]
        mod.main()
    sys.argv = ["edges"]
    edges.main()
    sys.argv = ["edge_compare"]
    edge_compare.main()


def do_report(a):
    from .report import gallery, make_slides, slides_pdf, summary_md
    for mod in (summary_md, make_slides, slides_pdf, gallery):
        sys.argv = [mod.__name__]
        mod.main()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m selected_analysis", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=STAGES + ("all",))
    ap.add_argument("--recommend", action="store_true", help="stage: also write the selection json (runs foraging_preprocess)")
    ap.add_argument("--sets", nargs="*", help=f"analyze: run sets from {list(config.RUN_SETS)} (default: all)")
    ap.add_argument("--steps", help="analyze: pipeline steps (default: all; see per_dataset/pipeline.py)")
    ap.add_argument("--dry-run", action="store_true", help="analyze: list what would run, write nothing")
    a = ap.parse_args(argv)
    todo = STAGES if a.command == "all" else (a.command,)
    for stage_name in todo:
        print(f"\n##### {stage_name}")
        globals()[f"do_{stage_name}"](a)


if __name__ == "__main__":
    main()
