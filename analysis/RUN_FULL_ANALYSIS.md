# Running the full foraging analysis (rig data → tables → slide deck)

Written November 11, 2026, after adding three inverted 50/50 ("reversed V", split-line reward
type 3) sessions. Part A is the routine path for new sessions; it was run end to end that day.
Part B rebuilds the whole deck from scratch; its order comes from the scripts' own docstrings
and `REVISION_CHECKS.md`, and was not rerun from scratch on Nov 11.

## Where things live

| What | Path (this machine unless noted) |
|---|---|
| Rig PC (acquisition) | `ssh kazama-pc-2` |
| Raw sessions on the rig | `kazama-pc-2:~/Raw_data/split line/reward type {1,2,3}/<date>/<task>/sub-N/` (curated split-line sessions); Gr64f sessions at `~/Raw_data/<date>/<task>/sub-N/` |
| FicTrac raw camera video | `kazama-pc-2:~/fictrac/foraging/<YYYYMMDD_HHMMSS>/` (see `fictrac_speed_profile/README.md`) |
| Split-line copies + per-type results | `analysis/split_line_20261106/source/reward type N/`, `.../results/reward_type_N/<tag>/`, `REPORT.md` |
| Gr64f and old split-line results | `analysis/selected_analysis/runs/<set>/<tag>/` (`python -m selected_analysis`) |
| The deck | `analysis/reports/2026-11-09-gr64f-split-only/` (`foraging_progress_report.pptx/.pdf`, `REVISION_CHECKS.md`) |
| FicTrac ball-speed + burst analysis | `<deck>/fictrac_speed_20261110/` (tables, `burst_detail/`, `video_check/`) |
| Versioned code for the steps below | `analysis/fictrac_speed_profile/` (+ `deck/`, `split_line/`) on branch `worktree-inverted-5050` |

The data and deck folders are **not tracked by git**. Their scripts are copied from the versioned
`analysis/fictrac_speed_profile/` tree by `deck/run_update.sh`; edit the versioned copy, never only
the copy in the deck folder.

Cohort ids used everywhere: `past_50_50`, `past_20_100` (Gr64f), `split_line` (split 50/50,
zone 1 = 1.0 V, zone 2 = 2.5 V), `split_type2` (split 20/100), `split_type3` (split 50/50 reversed V:
zone 1 = 2.5 V, zone 2 = 1.0 V). The main comparisons use the first four (51 sessions);
`split_type3` is shown separately (data slides and the speed, burst and zone-time appendix).

## Part A: add new sessions and update everything (~25 min)

### 1. Find and copy the new sessions from the rig

```bash
# what exists on the rig (example: reversed V)
ssh kazama-pc-2 'ls ~/Raw_data/"split line"/"reward type 3"'
# copy a day (keeps the folder layout), then compare SHA-256 of every file
SRC="/home/kazama/Raw_data/split line/reward type 3"; DST="analysis/split_line_20261106/source/reward type 3"
T=foraging_non-iti_130_20-40_100-120_2.5v-0.1v_1.0v-0.1v_50_50; D=2026-11-10
mkdir -p "$DST/$D/$T" && rsync -a --protect-args "kazama-pc-2:$SRC/$D/$T/" "$DST/$D/$T/"
(cd "$DST" && find $D -type f -exec sha256sum {} + | sort -k2) > /tmp/local.sha
ssh kazama-pc-2 "cd '$SRC' && find $D -type f -exec sha256sum {} + | sort -k2" > /tmp/remote.sha
diff /tmp/local.sha /tmp/remote.sha   # only the day-level .run_day_manifest.json may differ (not copied)
```

Only take sessions from the curated `split line/` tree. On Nov 11 there was also a reversed-voltage
session in `~/Raw_data/2026-10-20/` on the rig, outside that tree with no line label. It was **not**
added. Ask before including it. Each session needs its `session_selection_recommended_<date>_<sub>.json`
(made by `foraging_preprocess` on the rig) and a `fictrac-*.dat` for the FicTrac steps.

### 2. Per-dataset pipeline (survival → leave rule → figures → learning/fatigue → models)

```bash
cd <repo>   # any checkout; the package code is unchanged since d96e8e0
PYTHONPATH=analysis python3 -m selected_analysis.per_dataset.pipeline \
  --raw-root "analysis/split_line_20261106/source/reward type 3" --name reward_type_3 \
  --out-root analysis/split_line_20261106/results
python3 analysis/fictrac_speed_profile/split_line/make_report.py    # rewrites split_line_20261106/REPORT.md
```

Use `reward type 1` / `reward_type_1` and `reward type 2` / `reward_type_2` for the other split-line
types. Gr64f / older sets: `python3 -m selected_analysis analyze --sets past` (see
`analysis/selected_analysis/README.md`). Models run only with ≥ 5 sessions and group tests with
≥ 3. Back up `results/reward_type_N` first if you want a before/after comparison.

### 3–6. Deck tables, FicTrac speed, bursts, slides: one command

```bash
bash analysis/fictrac_speed_profile/deck/run_update.sh            # pipeline → render, all stages
bash analysis/fictrac_speed_profile/deck/run_update.sh --from fictrac   # after step 2 was run by hand
bash analysis/fictrac_speed_profile/deck/run_update.sh --from deck      # only redraw slides + render
```

Stages, in order (each idempotent):

| Stage | Script(s) | Does |
|---|---|---|
| `pipeline` | `selected_analysis.per_dataset.pipeline`, `split_line/make_report.py` | step 2 for reward type 3 |
| `inventory` | `deck/add_reversed_sessions.py` | appends new `split_type3` sessions to the deck's `session_inventory.csv`, `analyzed_trials.csv`, `source_config.json`; asserts earlier sessions' survival rows are unchanged |
| `fictrac` | `trial_list.py`, `fictrac_speed_profile.py` (~10 min) | trial list from the inventory (checked identical to `speed_trajectory_review/trial_audit.csv` for the earlier sessions), then speed profiles, bursts, zone contrasts from the raw `.dat` on the camera clock |
| `bursts` | `burst_enrichment.py`, `burst_detail.py` (~8 min) | zone vs outside rates, burst classes, timing, triggered speed, session tests |
| `deck` | `deck/fictrac_slides.py` → `deck/burst_slides.py` → `deck/zone_time_slides.py` → `deck/reversed_v_counts.py` | redraw and re-place slides 26-28, 29-32, 34; update session counts on slides 1, 4, 5, 6 |
| `render` | `render_decks.py`, `validate_report.py` | PDF + previews in `review/foraging_progress_report/`, text-overflow check, full audit → `validation.json` |

`add_reversed_sessions.py` only handles `split_type3`. For new sessions of another cohort, extend it
(same columns) and also rebuild the main comparisons (Part B), since those slides are drawn by
`build_compact.py`.

### 7. Check

- `validate_report.py` prints a JSON with `"status": "passed"`, and `review/foraging_progress_report/overflow.json` is `[]`.
- Look at the previews of every changed slide (`review/foraging_progress_report/slide_0NN.png`).
- The other cohorts' FicTrac/burst rows should be identical to before. Compare against the
  `before_*` zip that each step writes (e.g. `before_reversed_v_20261111/`).
- Slide notes are written against the numbers. Reread titles and notes after new data: they are
  computed, but the wording (for example "points the same way") is a judgement on the result.
- Add a follow-up entry to `<deck>/REVISION_CHECKS.md`.

## Part B: rebuild the deck from scratch

Run inside the deck folder. Each script backs up what it replaces into a `before_*` folder.

1. Per-dataset results for every cohort (Part A step 2, plus `python3 -m selected_analysis analyze`).
2. `python3 build_report.py`: runs `build_compact.py`, which calls `build_statistics`, `build_examples`,
   `combined_conditions`, `merge_revisions`, `assay_intro`, `population_order` and `bump_explanation`
   (the main 1-25 slide structure, counts hard-coded at 53 sessions).
3. `python3 speed_trajectory_review/build_review.py` (speed/trajectory audit; writes `trial_audit.csv`).
4. Revision steps in this order: `contextual_examples.py`, `revise_speed_slides.py`,
   `finalize_deck.py` (also runs `replot_changes.py`, `replot_edge_summary.py`; rewrites the conclusion).
5. Part A stages `fictrac` → `render` (`run_update.sh --from fictrac`). `fictrac_slides.py` must
   follow `finalize_deck.py`, `burst_slides.py` must follow `fictrac_slides.py`, and
   `reversed_v_counts.py` must come after `build_compact.py` (it restores the 56-session counts).

The stage-specific validators (`validate_assay_intro.py`, `validate_bump_explanation.py`,
`validate_merged_revisions.py`, `validate_combined_conditions.py`, `validate_examples.py`) assert
older slide counts and are known to be stale. Only `validate_report.py` is maintained.

## Gotchas

- FicTrac `.dat` column 22 is camera **nanoseconds**, frame rate is 96.4 fps (not 120).
- Old Gr64f sessions keep their `.dat` only in `~/fictrac/foraging/` on this machine;
  `fictrac_speed_profile.find_dats` matches them by system-clock overlap. Gr64f 20/100 (May) has none.
- Set `MPLCONFIGDIR` to a writable folder (the runner does). `render_decks.py` needs headless
  Chromium and cannot write into hidden folders.
- The rig PC has no ffmpeg or cv2: copy videos here before running `burst_video.py` / `burst_clips.py`.
