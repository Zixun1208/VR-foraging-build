# selected_analysis

Patch-leaving analysis on the trials that `foraging_preprocess` selected. Self-contained like
`foraging_preprocess` (numpy, pandas, matplotlib only); copy it anywhere.

Reads `<raw-root>/<date>/<task>/<sub>/` sessions and their
`session_selection_recommended_<date>_<sub>.json` (or the applied
`session_selection_<date>_<sub>.json` with `--selection applied`). Only trials in the
selection's `training_basenames` / `probing_basenames` are used. Nothing here applies a
recommendation.

| file | does |
|---|---|
| `selection.py` | finds sessions and reads their kept-trial lists |
| `trials.py` | trial/flash-log readers and task geometry (patch bands, voltages, decay) parsed from the task folder name |
| `build_survival.py` | episode-bin survival table from the kept trials; one row per patch visit per second |
| `figures.py` | the poster's figures from the selected trials of one task: occupancy (lines, heatmaps), speed, approach speed, FicTrac velocity, leave geometry, per-patch leave point, early/late dwell repeatability |
| `leave_rule.py` | per-fly across-patch spread of giving-up time / fraction / value; the variable with the smallest spread is the one the fly leaves by |

```
python build_survival.py --raw-root ~/Raw_data --task <task folder name>
python leave_rule.py data/survival_<tag>.csv          # --min-leaves N, --out DIR
```

The survival table has the same columns as the earlier analysis's `survival*.csv`, so
`leave_rule.py` also runs on those: on the 9-fly 20_100 table it gives 9/9 flies most
consistent in time, median spread 0.24 (time) vs 1.66 (fraction, value).

```
python figures.py --raw-root <root> --task <task> --survival data/survival_<tag>.csv --out results/<name>
```

`figures.py` skips what needs other tasks or model fits: the 20_100 panels, per-fly timer,
non-ATR reward effect, GLM comparison. Its statistics (exact paired sign-flip, permutation
Spearman, bootstrap CI) are computed in the script, not read from precomputed files.

Kept trials get `qc_ok = 1`; `reached_end` still decides `left`. `data/` and `results/` are
outputs.

Checked: `build_survival.py` end to end on one local non-ATR session (120 episodes);
`leave_rule.py` on the existing 20_100 table. Not yet run on a full multi-subject dataset.
