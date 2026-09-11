"""Per-trial quality metrics, the keep/drop rules, and the recommendation file."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

import numpy as np

import config
from config import Thresholds
from tasks import TRIAL_RE


def load_trial(path: str):
    """Return ``(t_sec_from_start, x)`` for one trial, or None if unusable."""
    try:
        arr = np.genfromtxt(path, delimiter=",", skip_header=1, usecols=(0, 1),
                            invalid_raise=False)
    except (OSError, ValueError):
        return None
    if arr.ndim != 2 or len(arr) < 2:
        return None
    arr = arr[np.isfinite(arr).all(axis=1)]
    if len(arr) < 2:
        return None
    t = arr[:, 0] / 1000.0
    return t - t[0], arr[:, 1]


def _dwell_in_band(t, x, band):
    dt = np.diff(t, prepend=t[0])
    return float(dt[(x >= band[0]) & (x <= band[1])].sum())


def trial_paths(session_dir: str, phase: str) -> list[str]:
    """Trial CSVs for one phase, in true chronological order (by filename stamp)."""
    pdir = os.path.join(session_dir, phase)
    if not os.path.isdir(pdir):
        return []
    names = sorted((f for f in os.listdir(pdir) if TRIAL_RE.match(f)),
                   key=lambda f: TRIAL_RE.match(f).group("ts"))
    return [os.path.join(pdir, n) for n in names]


def qc_trials(session_dir: str, th: Thresholds) -> list[dict]:
    """One record per trial, carrying the metrics the rules below act on."""
    rows = []
    for phase in ("training", "probing"):
        for idx, path in enumerate(trial_paths(session_dir, phase)):
            name = os.path.basename(path)
            rec = {"phase": phase, "index": idx, "basename": name,
                   "iter": int(TRIAL_RE.match(name).group("iter"))}
            loaded = load_trial(path)
            if loaded is None:
                rec.update(readable=False)
                rows.append(rec)
                continue
            t, x = loaded
            dt = np.diff(t)
            # Correct the teleport wrap at the corridor end, and ignore frame
            # intervals too short to divide by (see plots.MIN_FRAME_DT).
            dx = np.diff(x)
            corridor = config.GEOM.corridor
            half = corridor / 2.0
            dx = np.where(dx > half, dx - corridor,
                          np.where(dx < -half, dx + corridor, dx))
            with np.errstate(invalid="ignore", divide="ignore"):
                speed = np.abs(dx) / np.where(dt >= 5e-3, dt, np.nan)
            moving = speed > th.speed_floor

            stall = longest = 0.0
            for is_moving, step in zip(np.nan_to_num(moving, nan=0).astype(bool), dt):
                stall = 0.0 if is_moving else stall + float(step)
                longest = max(longest, stall)

            rec.update(
                readable=True,
                n_rows=int(len(x)),
                duration_sec=round(float(t[-1]), 2),
                x_min=round(float(x.min()), 1),
                x_max=round(float(x.max()), 1),
                reached_end=bool((x >= config.GEOM.reached_end).any()),
                dwell_p1=round(_dwell_in_band(t, x, config.GEOM.patch1), 2),
                dwell_p2=round(_dwell_in_band(t, x, config.GEOM.patch2), 2),
                moving_fraction=round(float(np.nanmean(np.where(np.isfinite(speed), moving, np.nan))), 3),
                longest_stall_sec=round(longest, 1),
                median_speed=round(float(np.nanmedian(speed)), 2),
            )
            rec["entered_p1"] = rec["dwell_p1"] > 0.05
            rec["entered_p2"] = rec["dwell_p2"] > 0.05
            rows.append(rec)
    return rows


def apply_rules(rows: list[dict], th: Thresholds) -> None:
    """Set ``keep`` and ``reasons`` on each record, in place."""
    for r in rows:
        if not r.get("readable", False):
            r["keep"] = False
            r["reasons"] = ["file empty or unreadable"]
            continue
        reasons = []
        if th.require_reached_end and not r["reached_end"]:
            reasons.append(
                f"never reached x>={config.GEOM.reached_end:.0f} (max {r['x_max']})")
        if r["duration_sec"] < th.min_duration_sec:
            reasons.append(f"duration {r['duration_sec']}s < {th.min_duration_sec}s")
        if r["duration_sec"] > th.max_duration_sec:
            reasons.append(f"duration {r['duration_sec']}s > {th.max_duration_sec}s")
        if r["moving_fraction"] < th.min_moving_fraction:
            reasons.append(f"moving only {r['moving_fraction']:.1%} of frames")
        if r["longest_stall_sec"] > th.max_stall_sec:
            reasons.append(f"stalled {r['longest_stall_sec']:.0f}s in one stretch")
        if th.require_both_patches and not (r["entered_p1"] and r["entered_p2"]):
            reasons.append("did not enter both patches")
        r["keep"] = not reasons
        r["reasons"] = reasons


def trailing_dropoff(rows: list[dict], phase: str, min_run: int = 3) -> int | None:
    """Index where a session stops being usable and never recovers.

    Flies stop walking partway through and do not restart, so the tail of a
    session is often a solid block of rejects. Returns where that run begins,
    when it is at least ``min_run`` long -- a hint, not a rule.
    """
    idx = [r["index"] for r in rows if r["phase"] == phase]
    if not idx:
        return None
    keep = {r["index"]: r["keep"] for r in rows if r["phase"] == phase}
    last_good = max((i for i in idx if keep[i]), default=None)
    if last_good is None:
        return min(idx)
    return last_good + 1 if max(idx) - last_good >= min_run else None


def print_table(rows: list[dict]) -> None:
    for phase in ("training", "probing"):
        pr = [r for r in rows if r["phase"] == phase]
        if not pr:
            continue
        print(f"\n  {phase}: keep {sum(r['keep'] for r in pr)}/{len(pr)}")
        print(f"    {'idx':>3} {'dur(s)':>7} {'xmax':>6} {'move':>6} "
              f"{'stall':>6} {'p1':>6} {'p2':>6}  verdict")
        for r in pr:
            if not r.get("readable", False):
                print(f"    {r['index']:>3} {'-':>7} {'-':>6} {'-':>6} {'-':>6} "
                      f"{'-':>6} {'-':>6}  DROP: {r['reasons'][0]}")
                continue
            verdict = "keep" if r["keep"] else "DROP: " + "; ".join(r["reasons"])
            print(f"    {r['index']:>3} {r['duration_sec']:>7.1f} {r['x_max']:>6.1f} "
                  f"{r['moving_fraction']:>6.2f} {r['longest_stall_sec']:>6.0f} "
                  f"{r['dwell_p1']:>6.1f} {r['dwell_p2']:>6.1f}  {verdict}")


def write_recommendation(session_dir, date, task, sub, rows, th, atr, raw_root,
                         apply=False) -> str:
    """Write the recommendation in the schema the analysis notebook already reads.

    ``*_indices`` index into the chronologically sorted trial list, which is what
    ``foraging.io.select_and_crop_sessions`` expects; ``*_basenames`` records the
    full list so a selection stays interpretable if files are added later.
    """
    payload = {
        "schema_version": 1,
        "date": date,
        "task_name": task,
        "subject_id": sub,
        "t_start_ms": None,
        "t_end_ms": None,
        "raw_data_root": raw_root + os.sep,
    }
    for phase in ("training", "probing"):
        pr = [r for r in rows if r["phase"] == phase]
        payload[f"{phase}_indices"] = [r["index"] for r in pr if r["keep"]]
        payload[f"{phase}_basenames"] = [r["basename"] for r in pr]

    payload["recommendation"] = {
        "generated_by": "foraging_preprocess/preprocess.py",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "atr": atr,
        "atr_source": ("supplied on the command line" if atr is not None
                       else "not supplied -- unknown"),
        "thresholds": th.as_dict(),
        "trailing_dropoff": {p: trailing_dropoff(rows, p)
                             for p in ("training", "probing")},
        "trials": rows,
    }

    path = os.path.join(session_dir, f"session_selection_recommended_{date}_{sub}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"[recommend] -> {path}")

    if apply:
        live = os.path.join(session_dir, f"session_selection_{date}_{sub}.json")
        if os.path.isfile(live):
            shutil.copy2(live, live + ".bak")
            print(f"  existing selection backed up -> {os.path.basename(live)}.bak")
        with open(live, "w") as f:
            json.dump({k: v for k, v in payload.items() if k != "recommendation"},
                      f, indent=2)
            f.write("\n")
        print(f"  applied -> {live}")
    return path
