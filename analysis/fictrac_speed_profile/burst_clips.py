#!/usr/bin/env python3
"""Full-frame slow-motion clips of FicTrac bursts (no cropping).

Same sync as burst_video.py (bursts.csv time -> .dat frame counter -> vidLogFrames line -> video
frame; one decoding pass per video with ffmpeg's select filter). Picks --n random probing bursts per
session (onset in a reward zone, 3-30 frames above 45 units/s), cuts PRE frames before and POST
after onset, and writes one MP4 per burst at --slow x slower than real time, labelled with session,
position, burst length, peak speed and frame offset from onset, plus clips.csv.

    python3 burst_clips.py --video VIDEO_DIR --out OUT_DIR [--n 3] [--seed 1] [--slow 10]
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess

import numpy as np
import pandas as pd

import fictrac_speed_profile as FT
from burst_video import H, W, FPS, grab, in_zone

HERE = os.path.dirname(os.path.abspath(__file__))
PRE, POST = 30, 40


def write_clip(frames, path, label, slow):
    fps = FPS / slow
    esc = lambda s: s.replace(":", "\\:").replace("'", "")
    top, second = label
    vf = (f"drawtext=text='{esc(top)}':x=10:y=10:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,"
          f"drawtext=text='{esc(second)}':x=10:y=34:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.6,"
          f"drawtext=text='frame %{{eif\\:n-{PRE}\\:d}} from onset (1/{slow} speed)':x=10:y=505:"
          f"fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}",
           "-r", f"{fps:.4f}", "-i", "-", "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "20", "-r", "30", path]
    subprocess.run(cmd, input=np.ascontiguousarray(frames).tobytes(), check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--slow", type=int, default=10)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(a.seed)
    bursts = pd.read_csv(os.path.join(HERE, "bursts.csv"))
    audit = pd.read_csv(FT.AUDIT)
    rows = []
    for avi in sorted(glob.glob(os.path.join(a.video, "fictrac-raw-*.avi"))):
        stamp = os.path.basename(avi)[len("fictrac-raw-"):-4]
        vlog = np.loadtxt(os.path.join(a.video, f"fictrac-vidLogFrames-{stamp}.txt"), dtype=np.int64)
        hits = [(sid, p) for sid, p in audit.groupby("session_id").path.first().items()
                if os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(p)), f"fictrac-{stamp}.dat"))]
        if not hits:
            continue
        sid, p = hits[0]
        f = FT.load_dat(os.path.dirname(os.path.dirname(p)))
        b = bursts[(bursts.session_id == sid) & (bursts.phase == "probing") & (bursts.frames >= 3)
                   & (bursts.frames <= 30) & in_zone(bursts.start_x)]
        pick = b.iloc[np.sort(rng.choice(len(b), min(a.n, len(b)), replace=False))]
        ev = []
        for r in pick.itertuples():
            k = min(np.searchsorted(f[:, 4], r.t_sys_ms), len(f) - 1)
            vi = int(np.searchsorted(vlog, int(f[k, 0])))
            ev.append((r, vi))
        cache = grab(avi, [vi + o for _, vi in ev for o in range(-PRE, POST + 1)])
        for r, vi in ev:
            fr = np.stack([cache[vi + o] for o in range(-PRE, POST + 1) if vi + o in cache])
            name = f"{sid.split(':')[1]}_{r.trial[:-4]}_X{r.start_x:.0f}.mp4"
            zone = "zone 1" if r.start_x < 60 else "zone 2"
            label = (f"{sid}  {r.trial.split('_2026')[0]}",
                     f"X={r.start_x:.1f} ({zone})  {r.frames} frames, peak {r.peak_speed:.0f} units/s")
            write_clip(fr, os.path.join(a.out, name), label, a.slow)
            rows.append(dict(file=name, session_id=sid, trial=r.trial, start_x=r.start_x, frames=r.frames,
                             peak_speed=r.peak_speed, displacement=r.displacement, video=os.path.basename(avi),
                             video_frame_onset=vi))
            print(f"  {name}", flush=True)
    clips = pd.DataFrame(rows)
    clips.to_csv(os.path.join(a.out, "clips.csv"), index=False)
    print(f"{len(clips)} clips")


if __name__ == "__main__":
    main()
