# Corridor speed from the raw FicTrac ball (Nov 10, 2026)

This folder tests whether the reward-zone speed bump in the Gr64f/split-line deck
(`analysis/reports/2026-11-09-gr64f-split-only`, "speed diagnostics" appendix)
comes from the Unity position log. Speed here is taken from FicTrac's own `.dat`
output, not from the Unity trial CSV.

## How speed is measured

- **Clock:** the FicTrac camera timestamp (column 22, ns on this rig), which is
  regular at 10.375 ms/frame. Unity stamps each position when its main thread
  drains the UDP queue, so several frames can share one timestamp.
- **Distance:** `calc_path.py` moves the corridor position by
  `4 × column 7` (lab-frame delta rotation about y, rad) and clamps it at 0.
  The same rule is applied here, anchored to the first Unity sample of each trial.
  The rebuilt end position matches Unity to a median 0.18 units over 3927 trials.
  The rebuilt duration matches Unity's (median ratio 1.0000).
- **Profile:** time-weighted speed per bin and session (Σ|ΔX| / Σdt over 100 bins
  across 0–130), averaged over sessions. Zone contrasts use the deck's
  definition: zone 1 is 20–40 vs 10–20 and 40–50; zone 2 is 100–120 vs 90–100 and
  120–130.
- **Bursts:** frames faster than 45 units/s. The walking distribution ends near
  30–40 units/s (99.9th percentile 31), and a separate cluster sits at
  60–160 units/s. Burst frames within 3 frames of each other form one episode.
  The "bursts removed" curves drop each episode plus 2 frames on each side.
- **Coverage:** Gr64f 20/100 (all May sessions) and 3 Gr64f 50/50 sessions have no
  FicTrac `.dat`, so they are absent here.

## Results

**1. The bursts are in the ball data, not caused by Unity logging.** In the deck's example
trial (`fig_example.png`), FicTrac shows about 10 consecutive frames at 110–167
units/s (about 40 rad/s of ball rotation) on a perfectly regular camera clock.
Unity's 63 and 56 units/s steps are this event, received in clumps. FicTrac's
error score rises from about 6000 to about 10000 during the burst. That is still
below `opt_max_err` 15000, so the frames were not flagged.

**2. FicTrac and the time-weighted Unity log give the same profile.**
`fig_profiles_split.png` shows the two curves lying on top of each other. The
reward-zone bump appears only in the older equal-trial curve, the gold line
(`legacy`). The probing zone contrasts, mean ± SEM over sessions with the count
of positive sessions, are:

| Cohort, zone | older curve | Unity time-weighted | FicTrac | FicTrac, bursts removed |
|---|---:|---:|---:|---:|
| Split 50/50, zone 2 | +1.30 (12/12) | −0.04 (6/12) | −0.03 (6/12) | −0.16 (4/12) |
| Split 50/50, zone 1 | +0.78 (11/12) | +0.23 (8/12) | +0.23 (7/12) | +0.18 (7/12) |
| Split 20/100, zone 1 | +1.05 (14/15) | +0.70 (15/15) | +0.71 ± 0.13 (14/15) | +0.61 ± 0.13 (14/15) |
| Split 20/100, zone 2 | +0.80 (13/15) | +0.15 (10/15) | +0.16 (9/15) | +0.06 (6/15) |

The 50/50 zone-2 bump does not appear on the independent ball measurement. This
confirms the earlier estimator explanation in `bump_mechanism_20261110`. The
20/100 zone-1 increase holds on the ball at its own clock, with or without bursts.

**3. Multi-frame bursts cluster in the reward zones during probing, when the LED is off.**
`fig_burst_rate.png` and `burst_enrichment.py` show this.

- Bursts of 3 or more frames in split-line probing: median 0.55 per minute in
  zones vs 0.00 outside for 50/50, higher in zones in 11/12 sessions. For 20/100
  it is 0.30 vs 0.00, in 12/15 sessions.
- No zone excess in training, when the LED is on in zones.
- Single-frame spikes are spread evenly in and out of zones, which looks like
  tracking noise.
- Of 776 split-line probing bursts, 76% start in a zone and 89% move forward.
  The median peak is 84 units/s and the median displacement is 3.4 units.

Probing trials have no LED flashes (`flash_events/probing_*.csv` are empty), so
these bursts cannot be a light artifact on the tracking camera. They are brief, fast
forward movements of the ball where reward is expected but not delivered. This
analysis does not determine whether they are fast runs, jumps or a fly kicking the
ball. Their rate is far above normal walking, and the error score rises during them.
They make up 0.06% of tracked time, so they barely change time-weighted speeds.

## Files

- `fictrac_speed_profile.py`: the full analysis, about 5 minutes. It reads the
  deck's `speed_trajectory_review/trial_audit.csv` and `bump_mechanism_20261110`
  legacy profiles.
- `burst_enrichment.py`: zone vs outside burst rates per session, written to
  `burst_enrichment.csv`.
- `session_profiles.csv`, `zone_contrasts.csv`, `zone_contrast_summary.csv`,
  `bursts.csv` and `trial_checks.csv`: tables.
- `fig_profiles_split.png`, `fig_profiles_split_forward.png`,
  `fig_profiles_gr64f.png`, `fig_burst_rate.png`, `fig_burst_edges.png` and
  `fig_example.png`: figures.

```
python3 fictrac_speed_profile.py [--burst 45] [--out DIR]
python3 burst_enrichment.py
```

## Update Nov 11: equal-trial averaging on the ball data

`fictrac_eq` / `fictrac_eq_noburst` in `session_profiles.csv` use the older deck's weighting. Each
trial's own bin speed is computed first, then trials and sessions are averaged equally. With this
weighting the bumps reappear on FicTrac, larger than on Unity because FicTrac sees the full burst
speed. They come from the bursts:

| Probing, zone minus flanks | equal-trial | equal-trial, bursts removed | time-weighted |
|---|---:|---:|---:|
| Split 50/50, zone 2 | +3.58 (12/12) | +0.02 (8/12) | −0.03 (6/12) |
| Split 50/50, zone 1 | +2.12 (11/12) | +0.72 (10/12) | +0.23 (7/12) |
| Split 20/100, zone 1 | +2.73 (14/15) | +1.17 (15/15) | +0.71 (14/15) |
| Split 20/100, zone 2 | +2.27 (13/15) | +0.43 (9/15) | +0.16 (9/15) |

A trial that bursts through a bin in about 10 ms counts as much as a trial that spends seconds
there, so equal-trial averaging answers "how fast is a typical pass" and time weighting answers
"how fast does the fly move while here". Deck slide 26 now shows the equal-trial version.
