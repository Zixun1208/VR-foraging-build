"""Acquisition folder -> a formatted session directory.

The rig writes one continuous camera log plus per-trial LED logs. Everything
downstream wants per-trial trajectory CSVs, so this slices the camera log
using teleports detected directly in its own position column (see slicer.py
for why: flash-event timestamps are not trustworthy trial boundaries), then
attaches the FicTrac recording for the same run.
"""
from __future__ import annotations

import glob
import os
import shutil
import sys

from config import Roots


def _slice(session_dir: str) -> None:
    from slicer import (
        SLICED_PHASES, collect_flash_events, detect_teleport_rows,
        build_windows, slice_camera_log, CAMERA_LOG_RE,
    )
    from pathlib import Path

    unity = Path(session_dir) / "unity"
    logs = sorted(unity.glob("CameraLog_*.csv"))
    if not logs:
        raise SystemExit(f"no CameraLog_*.csv in {unity}")
    if len(logs) > 1:
        print(f"  [warn] {len(logs)} camera logs; using {logs[0].name}")
    cam = logs[0]
    if CAMERA_LOG_RE.match(cam.name) is None:
        raise SystemExit(f"unexpected camera-log name: {cam.name}")

    flash_dir = Path(session_dir) / "flash_events"
    events = collect_flash_events(flash_dir)
    if not events:
        raise SystemExit(f"no flash-event files found in {flash_dir}")
    teleport_rows = detect_teleport_rows(cam)
    windows = build_windows(events, teleport_rows, verbose=True)

    # training/probing/openloop_training/baseline each get their own
    # subdirectory; initial_training (con_led's startup duplicate of the
    # first trial) is excluded -- it's in SLICED_PHASES's complement on
    # purpose, see collect_flash_events.
    out_dirs = {phase: Path(session_dir) / phase for phase in SLICED_PHASES}
    counts = slice_camera_log(camera_log_path=cam, windows=windows, out_dirs=out_dirs, verbose=False)
    empty = [n for n, c in counts.items() if c == 0]
    print(f"  sliced {len(counts)} trials, {sum(counts.values()):,} rows "
          f"({len(teleport_rows)} teleports detected, {len(events)} flash events)")
    if empty:
        print(f"  [warn] {len(empty)} trial(s) got no camera rows: {empty[:5]}")


def attach_fictrac(session_dir: str, acq_id: str, roots: Roots,
                   build_cache: bool = True) -> str | None:
    """Copy the run's FicTrac .dat next to the session and build its turn cache.

    The files inside a FicTrac run directory can carry a timestamp a second off
    the directory's own, so glob rather than reconstruct the name.
    """
    run = os.path.join(roots.fictrac_root, acq_id)
    if not os.path.isdir(run):
        print(f"  [warn] no FicTrac run at {run}; continuing without it")
        return None
    dats = sorted(glob.glob(os.path.join(run, "fictrac-*.dat")))
    if not dats:
        print(f"  [warn] FicTrac run {acq_id} has no .dat; continuing without it")
        return None
    dest = os.path.join(session_dir, os.path.basename(dats[0]))
    if not os.path.isfile(dest):
        print(f"  copying FicTrac ({os.path.getsize(dats[0]) / 1e9:.2f} GB)")
        shutil.copy2(dats[0], dest)
    if build_cache:
        _build_turn_cache(dest, roots)
    return dest


def _build_turn_cache(dat_path: str, roots: Roots) -> None:
    """Cache the two FicTrac columns the analysis reads, as a .npz beside the .dat.

    Uses ~/Analysis's implementation when present so the cache format matches;
    otherwise writes an identical file itself. The .dat can be several GB, so
    this is read in chunks.
    """
    cache = f"{os.path.splitext(dat_path)[0]}.turn_c7_t24.npz"
    if os.path.isfile(cache):
        print("  FicTrac turn cache already present")
        return
    try:
        sys.path.insert(0, roots.analysis_root)
        from foraging.kinematics import load_fictrac_turning
        load_fictrac_turning(dat_path, verbose=False)
        print("  FicTrac turn cache ready (via foraging.kinematics)")
        return
    except Exception:                                          # noqa: BLE001
        pass
    try:
        import numpy as np
        import pandas as pd
        cols = [7, 24]      # delta rotation lab z (yaw), and the alt. timestamp
        chunks = pd.read_csv(dat_path, header=None, usecols=cols, chunksize=2_000_000)
        turn, time_ms = [], []
        for ch in chunks:
            turn.append(ch[7].to_numpy(dtype=float))
            time_ms.append(ch[24].to_numpy(dtype=float))
        turn = np.concatenate(turn)
        time_ms = np.concatenate(time_ms)
        order = np.argsort(time_ms, kind="stable")
        np.savez(cache, time_ms=time_ms[order], turning=turn[order])
        print(f"  FicTrac turn cache ready ({len(turn):,} frames)")
    except Exception as e:                                     # noqa: BLE001
        print(f"  [warn] could not build the FicTrac turn cache: {e}")


def ingest(acq_id: str, task: str, date: str, sub: str, roots: Roots,
           skip_fictrac: bool = False) -> str:
    src = os.path.join(roots.acq_root, acq_id)
    if not os.path.isdir(src):
        raise SystemExit(f"no acquisition folder at {src}")
    dest = os.path.join(roots.raw_root, date, task, sub)
    print(f"[ingest] {src}\n      -> {dest}")

    os.makedirs(dest, exist_ok=True)
    for name in ("unity", "flash_events"):
        s = os.path.join(src, name)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, name), dirs_exist_ok=True)

    existing = glob.glob(os.path.join(dest, "training", "*.csv"))
    if existing:
        print(f"  {len(existing)} training CSVs already sliced; leaving them alone")
    else:
        _slice(dest)

    if not skip_fictrac:
        attach_fictrac(dest, acq_id, roots)
    return dest
