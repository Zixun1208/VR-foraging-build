#!/usr/bin/env python3
"""Per-session burst rate inside the reward zones vs the rest of the corridor (reads the outputs
of fictrac_speed_profile.py). Rate = burst onsets per minute spent in that region.
Writes burst_enrichment.csv and prints a summary by cohort, phase and burst length."""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
p = pd.read_csv(os.path.join(HERE, "session_profiles.csv"))
b = pd.read_csv(os.path.join(HERE, "bursts.csv"))
inzone = lambda x: ((x >= 20) & (x < 40)) | ((x >= 100) & (x < 120))
p["region"] = np.where(inzone(p.position), "zone", "outside")
b["region"] = np.where(inzone(b.start_x), "zone", "outside")
b["kind"] = np.where(b.frames >= 3, "3+ frames", "1-2 frames")
t = p.groupby(["cohort", "session_id", "phase", "region"]).fic_time.sum().unstack() / 60
rows = []
for kind in ["all", "1-2 frames", "3+ frames"]:
    bb = b if kind == "all" else b[b.kind == kind]
    n = bb.groupby(["cohort", "session_id", "phase", "region"]).size().unstack().reindex(t.index).fillna(0)
    r = (n / t).add_prefix("rate_")
    r["kind"] = kind
    rows.append(r.reset_index())
e = pd.concat(rows)
e["zone_minus_outside"] = e.rate_zone - e.rate_outside
e.to_csv(os.path.join(HERE, "burst_enrichment.csv"), index=False)
s = e.groupby(["kind", "cohort", "phase"]).agg(
    sessions=("session_id", "nunique"), zone_per_min=("rate_zone", "median"),
    outside_per_min=("rate_outside", "median"),
    zone_higher=("zone_minus_outside", lambda x: f"{(x > 0).sum()}/{len(x)}"))
print(s.round(2).to_string())
q = b[(b.phase == "probing") & b.cohort.str.startswith("split")]
print("\nsplit-line probing bursts:", len(q), "| in zone:", (q.region == "zone").mean().round(3),
      "| median peak", q.peak_speed.median().round(1), "units/s | median displacement",
      q.displacement.median().round(2), "| forward share", (q.displacement > 0).mean().round(3))
