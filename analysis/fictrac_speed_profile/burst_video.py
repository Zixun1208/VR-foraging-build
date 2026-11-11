#!/usr/bin/env python3
"""Look at the FicTrac camera at burst moments, to see what the fly is doing.

The raw FicTrac videos are on the rig PC (kazama-pc-2:~/fictrac/foraging/<run>/fictrac-raw-<stamp>.avi,
with fictrac-vidLogFrames-<stamp>.txt). Copy the sessions you want into --video first, e.g.
    scp 'kazama-pc-2:fictrac/foraging/*/fictrac-{raw-<stamp>.avi,vidLogFrames-<stamp>.txt}' <video dir>

Sync: burst onset (bursts.csv t_sys_ms, the .dat system clock) -> .dat frame counter -> line of
vidLogFrames.txt (line i = frame counter written as video frame i) -> video frame, decoded by
ffmpeg at frame/fps. Each event becomes one row of crops (fly and top of the ball) at frame offsets
OFFSETS from onset.

Events per session (random, fixed seed):
  burst    probing, onset in a reward zone, 3-30 frames above 45 units/s
  spike    probing, 1 frame above 45 units/s
  control  probing, in a reward zone, at least 2 s from any burst (Unity log time)

Writes sheet_<kind>.png and events.csv into --out.
    python3 burst_video.py --video DIR --out DIR [--n 4]
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import fictrac_speed_profile as FT

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 96.379                      # avi frame rate written by FicTrac (r_frame_rate 96379/1000)
W, H = 720, 540
CROP = (240, 0, 600, 340)         # x0, y0, x1, y1: fly on the tether and the top of the ball
OFFSETS = [-3, 0, 2, 4, 6, 8, 10, 12, 15]
SCALE = 0.5


def in_zone(x):
    return ((x >= 20) & (x < 40)) | ((x >= 100) & (x < 120))


def grab(avi, wanted):
    """{video frame index: grey frame} for the wanted indices, in one decoding pass.

    These AVIs have essentially no keyframes after the first, so seeking decodes from the start
    every time; a single pass with ffmpeg's select filter (exact decoded frame number n) is far
    cheaper and frame-exact."""
    idx = np.unique(np.asarray(wanted, dtype=np.int64))
    idx = idx[idx >= 0]
    runs, start = [], idx[0]
    for prev, cur in zip(idx[:-1], idx[1:]):
        if cur != prev + 1:
            runs.append((start, prev))
            start = cur
    runs.append((start, idx[-1]))
    expr = "+".join(f"between(n\\,{a}\\,{b})" for a, b in runs)
    cmd = ["ffmpeg", "-v", "error", "-i", avi, "-vf", f"select='{expr}'", "-vsync", "0",
           "-frames:v", str(len(idx)), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, np.uint8).reshape(-1, H, W)
    return dict(zip(idx[:len(arr)].tolist(), arr))


def pick(bursts, audit, sid, n, rng):
    b = bursts[(bursts.session_id == sid) & (bursts.phase == "probing")]
    ev = []
    long_ = b[(b.frames >= 3) & (b.frames <= 30) & in_zone(b.start_x)]
    for r in long_.sample(min(n, len(long_)), random_state=rng).itertuples():
        ev.append(dict(kind="burst", t_sys_ms=r.t_sys_ms, x=r.start_x, frames=r.frames, peak=r.peak_speed))
    spk = b[b.frames == 1]
    for r in spk.sample(min(n, len(spk)), random_state=rng).itertuples():
        ev.append(dict(kind="spike", t_sys_ms=r.t_sys_ms, x=r.start_x, frames=1, peak=r.peak_speed))
    bt = bursts[bursts.session_id == sid].t_sys_ms.values
    cand = []
    for p in audit[(audit.session_id == sid) & (audit.phase == "probing")].path:
        u = FT.load_unity(p)
        u = u[in_zone(u[:, 1])]
        if len(u):
            far = np.min(np.abs(u[:, :1] - bt[None, :]), axis=1) > 2000 if len(bt) else np.ones(len(u), bool)
            cand.append(u[far])
    cand = np.vstack(cand)
    for i in rng.choice(len(cand), min(n, len(cand)), replace=False):
        ev.append(dict(kind="control", t_sys_ms=cand[i, 0], x=cand[i, 1], frames=0, peak=np.nan))
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "video_check"))
    ap.add_argument("--n", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(0)
    bursts = pd.read_csv(os.path.join(HERE, "bursts.csv"))
    audit = pd.read_csv(FT.AUDIT)
    rows = []
    for avi in sorted(glob.glob(os.path.join(a.video, "fictrac-raw-*.avi"))):
        stamp = os.path.basename(avi)[len("fictrac-raw-"):-4]
        vlog = np.loadtxt(os.path.join(a.video, f"fictrac-vidLogFrames-{stamp}.txt"), dtype=np.int64)
        hits = [(sid, p) for sid, p in audit.groupby("session_id").path.first().items()
                if os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(p)), f"fictrac-{stamp}.dat"))]
        if not hits:
            print(f"  [skip] {stamp}: no session uses this .dat")
            continue
        sid, p = hits[0]
        f = FT.load_dat(os.path.dirname(os.path.dirname(p)))
        for e in pick(bursts, audit, sid, a.n, rng):
            k = min(np.searchsorted(f[:, 4], e["t_sys_ms"]), len(f) - 1)
            cnt = int(f[k, 0])
            vi = int(np.searchsorted(vlog, cnt))
            rows.append(dict(session_id=sid, stamp=stamp, frame_cnt=cnt, video_frame=vi, **e))
        print(f"  {sid}: {stamp}")
    ev = pd.DataFrame(rows)
    ev.to_csv(os.path.join(a.out, "events.csv"), index=False)
    cache = {}
    for stamp, g in ev.groupby("stamp"):
        wanted = [v + o for v in g.video_frame for o in OFFSETS]
        cache[stamp] = grab(os.path.join(a.video, f"fictrac-raw-{stamp}.avi"), wanted)
        print(f"  decoded {stamp}: {len(cache[stamp])} frames", flush=True)

    cw, ch = int((CROP[2] - CROP[0]) * SCALE), int((CROP[3] - CROP[1]) * SCALE)
    lab = 230
    for kind, g in ev.groupby("kind"):
        sheet = Image.new("L", (lab + cw * len(OFFSETS), 24 + ch * len(g)), 0)
        d = ImageDraw.Draw(sheet)
        for j, o in enumerate(OFFSETS):
            d.text((lab + j * cw + 4, 4), f"{o:+d}", fill=255)
        for i, r in enumerate(g.itertuples()):
            y = 24 + i * ch
            d.text((4, y + 4), f"{r.session_id.split(':')[1]}\n{r.session_id.split(':')[0]}\nX={r.x:.0f}"
                   + (f"\n{r.frames} fr, peak {r.peak:.0f}" if r.frames else ""), fill=255)
            for j, o in enumerate(OFFSETS):
                fr = cache[r.stamp].get(r.video_frame + o)
                if fr is not None:
                    sheet.paste(Image.fromarray(fr).crop(CROP).resize((cw, ch)), (lab + j * cw, y))
        sheet.save(os.path.join(a.out, f"sheet_{kind}.png"))
        print(f"  sheet_{kind}.png: {len(g)} events")


if __name__ == "__main__":
    main()
