#!/usr/bin/env python3
"""Discrete-time survival (episode-bin) table from the *selected* trials only.

Each patch visit becomes bins t=1..ceil(dwell); ``left=1`` in the last bin if the trial
reached the corridor end. Every training bin carries the decaying LED value read from the
flash log. Trial set = the selection json's kept basenames (see selection.py), not a glob of
training/*.csv, so a recommendation actually changes what is analysed. Kept trials get
``qc_ok = 1``. Probing bins have NaN value.

Columns match the earlier analysis's data/survival*.csv, so existing scripts read it.

Run:
    python build_survival.py --raw-root ~/Raw_data --task <task folder name>
    python build_survival.py --task <task> --selection applied --dates 2026-09-11
"""
from __future__ import annotations

import argparse
import csv
import os

import numpy as np

import selection
import trials

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_EPISODE_SEC = 1.0
BIN_SEC = 1.0
FIELDS = ["fly_id", "date", "sub", "config", "phase", "patch", "start_volt", "visit_id",
          "trial_order", "t_bin", "elapsed_sec", "value_volts", "value_frac", "cum_reward",
          "left", "session_pos", "reached_end", "qc_ok"]


def build(raw_root, task, kind="recommended", dates=None):
    patches = trials.parse_task(task)["patches"]
    rows = []
    for s in selection.iter_selected(raw_root, kind, task, dates):
        files = []
        for phase in ("training", "probing"):
            for name in s.kept[phase]:
                path = os.path.join(s.sub_dir, phase, name)
                meta = trials.parse_fname(path)
                if meta and os.path.isfile(path):
                    files.append((meta["ts"], phase, path))
        files.sort()
        n = len(files)
        for order, (_, phase, path) in enumerate(files):
            traj = trials.load_trajectory(path)
            if traj is None:
                continue
            t, X = traj
            dt = trials.sample_dt(t)
            reached = int((X >= trials.REACHED_END_X).any())
            flash = (trials.load_flash(os.path.join(s.sub_dir, "flash_events",
                                                     os.path.basename(path)))
                     if phase == "training" else {})
            pos = 2.0 * order / (n - 1) - 1.0 if n > 1 else 0.0
            for patch, spec in patches.items():
                dwell = trials.band_dwell(dt, X, spec["band"])
                if dwell < MIN_EPISODE_SEC:
                    continue
                n_bins = max(1, int(np.ceil(dwell - 1e-9)))
                cum = 0.0
                for b in range(1, n_bins + 1):
                    mid = (b - 0.5) * BIN_SEC
                    if phase == "training":
                        val = trials.value_at(flash, patch, mid)
                        frac = val / spec["start_volt"]
                        if val == val:
                            cum += val * BIN_SEC
                        cr = cum
                    else:
                        val = frac = cr = float("nan")
                    rows.append({
                        "fly_id": s.fly_id, "date": s.date, "sub": s.sub, "config": task,
                        "phase": phase, "patch": patch, "start_volt": spec["start_volt"],
                        "visit_id": f"{s.fly_id}:{patch}:{order}", "trial_order": order,
                        "t_bin": b, "elapsed_sec": round(mid, 3),
                        "value_volts": round(val, 4), "value_frac": round(frac, 4),
                        "cum_reward": round(cr, 4), "left": int(b == n_bins and reached),
                        "session_pos": round(pos, 4), "reached_end": reached, "qc_ok": 1})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-root", default=selection.RAW_ROOT)
    ap.add_argument("--task", required=True, help="task folder name")
    ap.add_argument("--selection", choices=("recommended", "applied"), default="recommended")
    ap.add_argument("--dates", nargs="*", help="restrict to these YYYY-MM-DD dates")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    rows = build(a.raw_root, a.task, a.selection, set(a.dates) if a.dates else None)
    if not rows:
        raise SystemExit(f"no selected episodes for {a.task} under {a.raw_root} "
                         f"({a.selection} selections)")
    info = trials.parse_task(a.task)
    tag = "_".join(str(int(info["patches"][i]["decay_s"])) for i in (0, 1))
    out = a.out or os.path.join(HERE, "data",
                                f"survival_{tag}{'' if info['atr'] else '_non-atr'}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} bins, {len({r['visit_id'] for r in rows})} episodes, "
          f"{len({r['fly_id'] for r in rows})} flies -> {out}")


if __name__ == "__main__":
    main()
