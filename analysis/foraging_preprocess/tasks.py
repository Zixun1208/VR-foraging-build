"""Reconstruct the task name from what the LED actually did.

The rig does not record the task anywhere machine-readable, but the flash logs
show it: each zone's start voltage, and how long the amplitude took to reach the
0.1 V floor. Those four numbers are the task name.

The one thing they do not show is whether the fly was fed all-trans-retinal.
That has to come from the person who ran the experiment.
"""
from __future__ import annotations

import csv
import glob
import os
import re
from collections import Counter, defaultdict

TRIAL_RE = re.compile(
    r"^(?P<phase>training|probing)_iter_(?P<iter>\d+)_trial_(?P<trial>\d+)_"
    r"(?P<ts>\d{8}_\d{6}(?:_\d+)?)\.csv$"
)

VOLT_FLOOR = 0.101   # "reached the floor" -- the logs settle at exactly 0.1 V


def _fmt_volt(v: float) -> str:
    return f"{v:.1f}"


def infer_task(flash_dir: str, atr: bool | None,
               corridor: int = 130, patch1=(20, 40), patch2=(100, 120)):
    """Return ``(task_name_or_None, evidence_dict)`` for one session's flash logs."""
    starts, decays = defaultdict(list), defaultdict(list)
    for path in sorted(glob.glob(os.path.join(flash_dir, "*.csv"))):
        if not TRIAL_RE.match(os.path.basename(path)):
            continue
        by_zone = defaultdict(list)
        try:
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    by_zone[row["zone"]].append(
                        (float(row["elapsed_time_sec"]), float(row["amplitude_volts"])))
        except (OSError, KeyError, ValueError):
            continue
        for zone, rows in by_zone.items():
            if len(rows) < 3:
                continue
            starts[zone].append(round(rows[0][1], 2))
            floor = [t for t, a in rows if a <= VOLT_FLOOR]
            if floor:
                decays[zone].append(round(floor[0]))

    evidence = {}
    for zone in sorted(starts):
        evidence[f"zone{zone}_start_v"] = Counter(starts[zone]).most_common(1)[0][0]
        evidence[f"zone{zone}_decay_s"] = (
            Counter(decays[zone]).most_common(1)[0][0] if decays[zone] else None)
        evidence[f"zone{zone}_n_trials"] = len(starts[zone])

    if not {"zone0_start_v", "zone1_start_v"} <= evidence.keys():
        return None, evidence
    if evidence["zone0_decay_s"] is None or evidence["zone1_decay_s"] is None:
        # The LED never reached the floor in any trial: the fly always left early,
        # so the decay duration is not recoverable from this session alone.
        return None, evidence

    name = (f"foraging_non-iti_{corridor}_"
            f"{patch1[0]}-{patch1[1]}_{patch2[0]}-{patch2[1]}_"
            f"{_fmt_volt(evidence['zone0_start_v'])}v-0.1v_"
            f"{_fmt_volt(evidence['zone1_start_v'])}v-0.1v_"
            f"{evidence['zone0_decay_s']}_{evidence['zone1_decay_s']}")
    if atr is False:
        name += "_non-atr"
    return name, evidence
