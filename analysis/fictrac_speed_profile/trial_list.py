#!/usr/bin/env python3
"""Trial list for the FicTrac analyses, built from the deck's session inventory.

Same rule as the deck's speed_trajectory_review/build_review.py (which wrote trial_audit.csv):
every basename in the session's selection json, read as Unity (Timestamp(ms), X), kept if it has
at least 6 finite samples and a cleaned duration (selected_analysis sample_dt) of 5-900 s.
Writes cohort, session_id, phase, trial, path, i.e. the columns fictrac_speed_profile.py reads.

Use this instead of rerunning build_review.py when sessions are added: it leaves the older
speed-review tables untouched. --check compares the result with an existing trial_audit.csv.

    python3 trial_list.py --inventory DECK/session_inventory.csv --out DECK/fictrac_speed_20261110/trial_list.csv \
        [--check DECK/speed_trajectory_review/trial_audit.csv]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# works from the repo (analysis/fictrac_speed_profile/) and from the deck copy (analysis/reports/<deck>/fictrac_speed_*/)
ANALYSIS = next(p for p in Path(__file__).resolve().parents if (p / "selected_analysis").is_dir())
sys.path.insert(0, str(ANALYSIS))
from selected_analysis.core.trials import sample_dt  # noqa: E402

COLS = ["cohort", "session_id", "phase", "trial", "path"]


def build(inventory):
    rows = []
    for r in pd.read_csv(inventory).itertuples():
        sel = json.loads(Path(r.selection_file).read_text())
        for phase in ["training", "probing"]:
            for fn in sorted(sel.get(phase + "_basenames") or []):
                p = Path(r.source_path) / phase / fn
                try:
                    a = pd.read_csv(p, usecols=["Timestamp(ms)", "X"])
                    t = a["Timestamp(ms)"].to_numpy(float) / 1000
                    x = a.X.to_numpy(float)
                    if len(t) < 6 or not np.isfinite(np.c_[t, x]).all():
                        continue
                    if not 5 <= float(sample_dt(t - t[0]).sum()) <= 900:
                        continue
                except (OSError, ValueError, IndexError):
                    continue
                rows.append(dict(cohort=r.cohort, session_id=r.session_id, phase=phase, trial=fn, path=str(p)))
    return pd.DataFrame(rows, columns=COLS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check", help="existing trial_audit.csv: every session in it must match exactly")
    a = ap.parse_args()
    d = build(a.inventory)
    if a.check:
        old = pd.read_csv(a.check)[COLS]
        new = d[d.session_id.isin(set(old.session_id))]
        key = lambda f: f.sort_values(COLS).reset_index(drop=True)
        same = key(old).equals(key(new))
        print(f"check against {a.check}: {'identical' if same else 'DIFFERENT'} ({len(old)} trials)")
        if not same:
            sys.exit(1)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    d.to_csv(a.out, index=False)
    print(f"{len(d)} trials, {d.session_id.nunique()} sessions -> {a.out}")
    print(d.groupby("cohort").session_id.nunique().to_string())


if __name__ == "__main__":
    main()
