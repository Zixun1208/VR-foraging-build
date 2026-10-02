"""Trial-file readers and task geometry, vendored so this directory stands alone.

Logic matches the readers the original analysis used (build_design.py), so tables built
here are comparable with the existing ones.
"""
from __future__ import annotations

import csv
import os
import re

import numpy as np

REACHED_END_X = 125.0   # X >= this counts the traversal as completed
MAX_GAP_SEC = 2.0       # dt above this is a pause/rollover, not a real frame interval

FNAME_RE = re.compile(
    r"^(?P<phase>training|probing)_iter_(?P<iter>\d+)_trial_(?P<trial>\d+)_"
    r"(?P<ts>\d{8}_\d{6}(?:_\d+)?)\.csv$"
)

# foraging_non-iti_<corridor>_<p1lo>-<p1hi>_<p2lo>-<p2hi>_<v1>v-<f1>v_<v2>v-<f2>v_<d1>_<d2>[_non-atr]
TASK_RE = re.compile(
    r"^foraging_non[-_]iti_(?P<corridor>\d+)_"
    r"(?P<p1lo>\d+)-(?P<p1hi>\d+)_(?P<p2lo>\d+)-(?P<p2hi>\d+)_"
    r"(?P<v1>[\d.]+)v-(?P<f1>[\d.]+)v_(?P<v2>[\d.]+)v-(?P<f2>[\d.]+)v_"
    r"(?P<d1>\d+)_(?P<d2>\d+)(?P<atr>_non[-_]atr)?$"
)


def parse_task(task: str) -> dict:
    """Patch bands, start voltages and decay seconds from a task folder name."""
    m = TASK_RE.match(task)
    if m is None:
        raise ValueError(f"not a notated task name: {task!r}")
    g = m.groupdict()
    return {
        "patches": {
            0: {"band": (float(g["p1lo"]), float(g["p1hi"])), "start_volt": float(g["v1"]),
                "decay_s": float(g["d1"])},
            1: {"band": (float(g["p2lo"]), float(g["p2hi"])), "start_volt": float(g["v2"]),
                "decay_s": float(g["d2"])},
        },
        "atr": g["atr"] is None,
    }


def parse_fname(path: str):
    m = FNAME_RE.match(os.path.basename(path))
    return m.groupdict() if m else None


def load_trajectory(path: str):
    """(t_sec, X) with t zeroed to the trial start, or None if unreadable/empty."""
    ts, xs = [], []
    try:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    ts.append(float(r["Timestamp(ms)"]))
                    xs.append(float(r["X"]))
                except (KeyError, ValueError):
                    continue
    except OSError as e:
        print(f"  [skip] cannot read {path}: {e}")
        return None
    if not ts:
        return None
    t = np.asarray(ts) / 1000.0
    return t - t[0], np.asarray(xs)


def sample_dt(t):
    """Per-sample dt (s); non-positive or > MAX_GAP_SEC deltas become the median interval."""
    dt = np.diff(t, prepend=t[0])
    pos = dt[(dt > 0) & (dt <= MAX_GAP_SEC)]
    med = float(np.median(pos)) if pos.size else 0.0
    if med <= 0:
        return np.zeros_like(dt)
    dt[(dt <= 0) | (dt > MAX_GAP_SEC)] = med
    return dt


def load_flash(path: str) -> dict:
    """{zone: (elapsed_sec, amplitude_volts)} from a flash_events file; {} if absent."""
    if not os.path.exists(path):
        return {}
    by_zone: dict[int, list] = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                by_zone.setdefault(int(float(r["zone"])), []).append(
                    (float(r["elapsed_time_sec"]), float(r["amplitude_volts"])))
            except (KeyError, ValueError):
                continue
    return {z: (np.array([p[0] for p in sorted(v)]), np.array([p[1] for p in sorted(v)]))
            for z, v in by_zone.items()}


def band_dwell(dt, X, band) -> float:
    """Total in-band time (s); jitter re-entries are summed into one episode."""
    lo, hi = band
    inband = (X >= lo) & (X < hi)
    return float(dt[inband].sum()) if inband.any() else 0.0


def value_at(flash: dict, zone: int, elapsed: float) -> float:
    """LED value at per-zone cumulative in-patch time; holds the last value past the log."""
    if zone not in flash or len(flash[zone][0]) == 0:
        return float("nan")
    et, amp = flash[zone]
    return float(np.interp(elapsed, et, amp))
