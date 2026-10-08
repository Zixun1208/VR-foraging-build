# selected_analysis

Patch-leaving analysis on the trials that `foraging_preprocess` selected, as one pipeline.
A Python package (numpy, pandas, matplotlib; python-pptx, Pillow and Chromium for the reports);
copy `selected_analysis/` anywhere and run it from the folder that contains it.

```
python -m selected_analysis all            # stage -> analyze -> summarize -> report
python -m selected_analysis analyze --sets split_line --steps survival,leave_rule
python -m selected_analysis analyze --dry-run
```

| command | does | writes |
|---|---|---|
| `stage [--recommend]` | links the 1D line sessions (OO, GO, GG) into `<date>/<task>/<sub>/` form; `--recommend` also runs `foraging_preprocess` (qc + recommend) so each has a selection json | `runs/_stage/` |
| `analyze [--sets ...] [--steps ...]` | the per-dataset pipeline (below) for every run set in `config.RUN_SETS` | `runs/<set>/<task tag>/` |
| `summarize` | reward effect, cross-dataset numbers, time around the four patch edges | `runs/summary/summary.json`, `edge_*.png` |
| `report` | markdown summary, slides (.pptx, .pdf), gallery of every figure | `runs/summary/` |

Every command skips what it cannot do and says so. Paths and the run sets (which folder, which
selection file, which tasks) are all in `config.py`; environment variables `SELECTED_ANALYSIS_RUNS`,
`FORAGING_RAW_ROOT`, `FORAGING_BY_TASK` and `FORAGING_STAGE` override them. `runs/` is output and git-ignored.

## Layout

```
selected_analysis/
  config.py          paths, task names, run sets
  cli.py, __main__.py   the entry point above
  core/              selection.py (find sessions, kept trials), trials.py (readers, task geometry),
                     stats.py (sign-flip, signed ranks), plotstyle.py (colours, axis style)
  per_dataset/       pipeline.py runs: build_survival -> leave_rule -> figures -> learning_fatigue -> models
  cross_dataset/     summary_stats.py (one json over all datasets), reward_effect.py, edges.py, edge_compare.py
  report/            summary_md.py, make_slides.py + deck_spec.py (slide text), slides_pdf.py, gallery.py
  vendored/          glmhmm.py, drift.py (switching and drifting models used by models.py)
  tools/             stage_lines.py
```

Each module also runs alone, e.g. `python -m selected_analysis.per_dataset.figures --help`.
Slide and summary prose (`report/deck_spec.py`, `report/summary_md.py`) is written by hand against
the numbers, so re-read it after new data. The PDFs use headless Chromium, which cannot write to hidden folders.

## Per-dataset pipeline

`analyze` calls `per_dataset/pipeline.py` for each run set. Reads `<raw-root>/<date>/<task>/<sub>/`
sessions and their `session_selection_recommended_<date>_<sub>.json` (`applied` reads the live
`session_selection_<date>_<sub>.json` instead; each run set in `config.py` says which). Only trials in the
selection's `training_basenames` / `probing_basenames` are used. Nothing here applies a recommendation.
Every task with a selection under the root is processed (or the run set's listed tasks). Each gets its
own folder:

```
runs/<name>/<task tag>/        tag = decay seconds, e.g. 50_50, 20_100, 50_50_non-atr
    survival.csv               episode-bin table, one row per patch visit per second
    leave_rule.csv/.png        per-fly across-patch spread of giving-up time/fraction/value
    figures/*.png              the poster's figures (ATR tasks only)
    learning_fatigue/          per-fly slopes of dwell and locomotion over the session (ATR only)
```

### Steps

`--steps` picks a subset. Each step reads the previous one's files from disk, so any step can
be re-run alone, e.g. `--steps figures` after changing `figures.py`.

| step | module | does |
|---|---|---|
| `survival` | `build_survival.py` | kept trials -> episode-bin table; same columns as the earlier analysis's `survival*.csv` |
| `leave_rule` | `leave_rule.py` | the variable with the smallest across-patch spread is the one the fly leaves by |
| `figures` | `figures.py` | time at each position (lines and heatmaps), speed, approach speed, FicTrac velocity, how the reward runs out, when flies leave each patch, early vs late time in patch |
| `learning_fatigue` | `learning_fatigue.py` | dwell, speed, moving fraction, stall and inter-patch speed against trial index; per-fly slopes, exact sign-flip and signed-rank tests, training vs probing, baseline reference (see `../learning_fatigue/README.md`) |

Poster figures across datasets come from `summarize`/`report` (run `analyze` on each dataset first):
`cross_dataset/reward_effect.py` compares reward-active flies against the no-ATR control (earlier 50/50
task only, the one dataset with a control of the same genotype); `cross_dataset/edges.py` is the time
spent around the four patch edges and how the extra time adds up with distance;
`cross_dataset/edge_compare.py` compares patch 1 with patch 2 around the edges (-5 to +5 units, every dataset, error bars; plain and baseline-subtracted versions, plus a paired per-fly table); `summary_stats.py`
collects the numbers every report reads (`summary.json`).

Other flags: `--dates D [D ...]`, `--min-leaves N` (visits per patch for a fly to enter
`leave_rule`, default 3), `--out-root`, and `--dry-run` to list what would run and write
nothing. Each module's own CLI still works standalone (`build_survival.py`, `leave_rule.py`,
`figures.py`).

## Notes

- Before anything else, trials that cannot be read, last under 5 s or over 900 s are dropped (`trials.trial_ok`): the
  long ones are a stalled fly or a rig left running, and the earlier analysis dropped them too. About 1% of
  trials, but 11 of one 50/50-task fly's roughly 35 trials.
- The original builders glob `training/*.csv` and never read the selection json; this one
  does. Kept trials get `qc_ok = 1`; `reached_end` still decides `left`.
- `figures.py` skips what needs other tasks or model fits: the 20_100 panels, per-fly timer,
  non-ATR reward effect, GLM comparison. Its statistics (exact paired sign-flip, permutation
  Spearman, bootstrap CI) are computed in the script, not read from precomputed files, so
  p-values are not directly comparable with the poster's.
- On the 50/50 task time and fraction of start value are confounded by design, so
  `leave_rule` can't separate them there; the 20_100 task does.
- `leave_rule.py` on the earlier 9-fly 20_100 table gives 9/9 flies most consistent in time
  (median spread 0.24 vs 1.66).
- `runs/` is output and git-ignored.

Checked end to end on the `split line` dataset (12 flies, one 50/50 task) and on one
non-ATR session for the survival step.
