# selected_analysis

Patch-leaving analysis on the trials that `foraging_preprocess` selected, as one pipeline.
Self-contained like `foraging_preprocess` (numpy, pandas, matplotlib only); copy it anywhere.

```
python pipeline.py --raw-root ~/Raw_data_by_task/"split line" --name split_line
```

Reads `<raw-root>/<date>/<task>/<sub>/` sessions and their
`session_selection_recommended_<date>_<sub>.json` (`--selection applied` reads the live
`session_selection_<date>_<sub>.json` instead). Only trials in the selection's
`training_basenames` / `probing_basenames` are used. Nothing here applies a recommendation.

Every task with a selection under the root is processed (or one, with `--task`). Each gets
its own folder:

```
runs/<name>/<task tag>/        tag = decay seconds, e.g. 50_50, 20_100, 50_50_non-atr
    survival.csv               episode-bin table, one row per patch visit per second
    leave_rule.csv/.png        per-fly across-patch spread of giving-up time/fraction/value
    figures/*.png              the poster's figures (ATR tasks only)
    learning_fatigue/          per-fly slopes of dwell and locomotion over the session (ATR only)
```

## Steps

`--steps` picks a subset. Each step reads the previous one's files from disk, so any step can
be re-run alone, e.g. `--steps figures` after changing `figures.py`.

| step | module | does |
|---|---|---|
| `survival` | `build_survival.py` | kept trials -> episode-bin table; same columns as the earlier analysis's `survival*.csv` |
| `leave_rule` | `leave_rule.py` | the variable with the smallest across-patch spread is the one the fly leaves by |
| `figures` | `figures.py` | time at each position (lines and heatmaps), speed, approach speed, FicTrac velocity, how the reward runs out, when flies leave each patch, early vs late time in patch |
| `learning_fatigue` | `learning_fatigue.py` | dwell, speed, moving fraction, stall and inter-patch speed against trial index; per-fly slopes, exact sign-flip and signed-rank tests, training vs probing, baseline reference (see `../learning_fatigue/README.md`) |

Supporting: `selection.py` (finds sessions, reads kept-trial lists) and `trials.py` (trial and
flash-log readers, task geometry parsed from the task folder name).

Poster figures for every dataset, and across datasets (run the pipeline on each dataset first):

- `pipeline.py` also makes the poster's per-fly "which quantity matches" box plot
  (`leave_rule_boxes.png`) and, with 5+ flies, the model comparison `figures/model_comparison.png`
  (`models.py`: shared rule, switching strategies, fixed fly differences, slowly changing; the
  switching and drifting code is vendored in `glmhmm.py` and `drift.py`)
- `reward_effect.py` reward-active flies against the no-ATR control, for the earlier 50/50 task only (the one dataset with a control of the same genotype)
- `stage_lines.py` stages a `<line>/sub-N/` dataset as `<date>/<task>/<sub>/` with symlinks
- `summary_stats.py` -> `summary_md.py` / `make_slides.py` / `slides_pdf.py` / `gallery.py` write
  `summary.json`, `foraging_summary.md`, `foraging_summary.pptx`, `foraging_summary.pdf` and
  `all_figures.pdf` (every figure for every dataset) into `runs/summary/`. Slide content is in
  `deck_spec.py`; the prose there and in `summary_md.py` is written by hand against the numbers, so
  re-read it after new data. The PDFs use headless Chromium, which cannot write to hidden folders.

Other flags: `--dates D [D ...]`, `--min-leaves N` (visits per patch for a fly to enter
`leave_rule`, default 3), `--out-root`, and `--dry-run` to list what would run and write
nothing. Each module's own CLI still works standalone (`build_survival.py`, `leave_rule.py`,
`figures.py`).

## Notes

- The original builders glob `training/*.csv` and never read the selection json; this one
  does. Kept trials get `qc_ok = 1`; `reached_end` still decides `left`.
- `figures.py` skips what needs other tasks or model fits: the 20_100 panels, per-fly timer,
  non-ATR reward effect, GLM comparison. Its statistics (exact paired sign-flip, permutation
  Spearman, bootstrap CI) are computed in the script, not read from precomputed files, so
  p-values are not directly comparable with the poster's.
- On the 50/50 canonical task time and fraction of start value are confounded by design, so
  `leave_rule` can't separate them there; the 20_100 task does.
- `leave_rule.py` on the earlier 9-fly 20_100 table gives 9/9 flies most consistent in time
  (median spread 0.24 vs 1.66).
- `runs/` is output and git-ignored.

Checked end to end on the `split line` dataset (12 flies, one 50/50 task) and on one
non-ATR session for the survival step.
