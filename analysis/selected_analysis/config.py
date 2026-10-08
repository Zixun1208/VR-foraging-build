"""Where everything lives: input trees, output folders and the list of datasets.

Change paths here (or with the environment variables below); every other module takes its
defaults from this file, so no script has a path of its own.

    SELECTED_ANALYSIS_RUNS    output root (default: ``runs/`` next to this file, git-ignored)
    FORAGING_RAW_ROOT         date-level raw tree (default ~/Raw_data)
    FORAGING_BY_TASK          folder holding the per-task / per-line datasets (default ~/Raw_data_by_task)
    FORAGING_STAGE            where stage_lines.py links the 1D line sessions (default <runs>/_stage)
"""
from __future__ import annotations

import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PREPROCESS_DIR = os.path.join(os.path.dirname(PACKAGE_DIR), "foraging_preprocess")

RUNS = os.environ.get("SELECTED_ANALYSIS_RUNS", os.path.join(PACKAGE_DIR, "runs"))
SUMMARY = os.path.join(RUNS, "summary")
SUMMARY_JSON = os.path.join(SUMMARY, "summary.json")

RAW_ROOT = os.path.expanduser(os.environ.get("FORAGING_RAW_ROOT", "~/Raw_data"))
BY_TASK = os.path.expanduser(os.environ.get("FORAGING_BY_TASK", "~/Raw_data_by_task"))
STAGE = os.path.expanduser(os.environ.get("FORAGING_STAGE", os.path.join(RUNS, "_stage")))

# task folder names the cross-dataset figures refer to
T50 = "foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50"
T20_100 = "foraging_non-iti_130_20-40_100-120_2.5v-0.1v_2.5v-0.1v_20_100"

T50_NONATR = T50 + "_non-atr"
T50_NONATR_B = T50 + "_non_atr"                    # the second no-ATR folder (same task, different spelling)
T20_20 = "foraging_non-iti_130_20-40_100-120_1.5v-0.1v_2.5v-0.1v_20_20"
T60_100 = "foraging_non_iti_130_20-40_100-120_1.5v-0.1v_2.5v-0.1v_60_100"

SPLIT_LINE_ROOT = os.path.join(BY_TASK, "split line")
LINES_1D_SOURCE = os.path.join(BY_TASK, "1D: " + T50)     # <line>/sub-N/, no date or task level
LINES_1D = ("OO", "GO", "GG")

# One entry per ``runs/<name>/`` folder: where its sessions live, which selection file to read
# (``recommended`` = written by foraging_preprocess, ``applied`` = the live one) and which tasks to
# take (None = every task found). A run folder holds one sub-folder per task tag (50_50, 20_100, ...).
# The staged 1D lines are read from STAGE/<line>, made by ``python -m selected_analysis stage``.
RUN_SETS = {
    "past": dict(root=RAW_ROOT, selection="applied", tasks=[T50, T50_NONATR, T20_20, T20_100, T60_100]),
    "past_nonatr_b": dict(root=RAW_ROOT, selection="applied", tasks=[T50_NONATR_B]),
    "split_line": dict(root=SPLIT_LINE_ROOT, selection="recommended", tasks=None),
    **{line: dict(root=os.path.join(STAGE, line), selection="recommended", tasks=None) for line in LINES_1D},
}
