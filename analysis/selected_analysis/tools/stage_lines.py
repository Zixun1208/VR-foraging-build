"""Stage the 1D line dataset (<line>/sub-N/, no date or task level) as
<out>/<line>/<date>/<task>/<sub>/ with symlinks, so foraging_preprocess and the pipeline can read it.
Date comes from the trial filenames; nothing under the source is written.

With ``--recommend`` it also runs foraging_preprocess (qc + recommend) on every staged session,
which writes the ``session_selection_recommended_*.json`` the analysis needs.

    python -m selected_analysis.tools.stage_lines                  # link into config.STAGE
    python -m selected_analysis.tools.stage_lines --recommend      # ... and write the selections
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys

from .. import config


def stage(out, source=config.LINES_1D_SOURCE, task=config.T50, lines=config.LINES_1D):
    """Link every session; returns [(line, date, sub, staged dir)]."""
    staged = []
    for line in lines:
        for sub in sorted(glob.glob(f"{source}/{line}/sub-*")):
            name = os.path.basename(sub)
            tr = sorted(os.listdir(f"{sub}/training")) if os.path.isdir(f"{sub}/training") else []
            if not tr:
                print("skip empty", line, name)
                continue
            ts = min(re.search(r"_(\d{8})_\d{6}", f).group(1) for f in tr)
            date = f"{ts[:4]}-{ts[4:6]}-{ts[6:]}"
            d = f"{out}/{line}/{date}/{task}/{name}"
            os.makedirs(d, exist_ok=True)
            for k in os.listdir(sub):
                if not os.path.lexists(f"{d}/{k}"):
                    os.symlink(f"{sub}/{k}", f"{d}/{k}")
            print(line, name, date)
            staged.append((line, date, name, d))
    return staged


def recommend(out, staged, task=config.T50):
    """foraging_preprocess qc + recommend on each staged session (writes the selection json)."""
    script = os.path.join(config.PREPROCESS_DIR, "preprocess.py")
    for line, date, sub, d in staged:
        if glob.glob(os.path.join(d, "session_selection_recommended_*.json")):
            continue
        cmd = [sys.executable, script, "--raw-root", f"{out}/{line}", "--date", date, "--sub", sub,
               "--task", task, "--steps", "qc,recommend"]
        print("recommend", line, date, sub)
        subprocess.run(cmd, check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?", default=config.STAGE, help="staging folder (default %(default)s)")
    ap.add_argument("--recommend", action="store_true", help="also write the selection json for each session")
    a = ap.parse_args(argv)
    staged = stage(a.out)
    if a.recommend:
        recommend(a.out, staged)


if __name__ == "__main__":
    main()
