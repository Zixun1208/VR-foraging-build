# learning_fatigue

Plan for a follow-up to `selected_analysis`: does patch dwell change over a session, and if so
is it fatigue or learning?

Status: **planned, not built.** Nothing in this folder runs yet.

## Why

`selected_analysis` on the `split line` dataset (12 flies, canonical 50/50, ATR) made
`dwell_repeatability.png`: median dwell in the first half of a session against the second half.
Every fly falls below the no-change diagonal, so dwell is **shorter late in the session**.
Rank order across flies holds in training (Spearman rho 0.68, Holm p = 0.028) but not clearly in
probing (rho 0.46, p = 0.14).

That figure asks whether flies keep their rank, not whether dwell falls, so the drop itself has
not been tested.

## Two readings

- **Fatigue / habituation.** The fly becomes less motivated or less active, so it spends less
  time everywhere.
- **Learning / adaptation.** The fly has learned the corridor or the reward schedule. It may
  traverse faster, or expect less from a patch, and so leave sooner.

## How to tell them apart

1. **Training against probing.** Probing has no LED reward. A fall that is equal in both points
   to general fatigue. A fall only in training points to something about the reward.
2. **Locomotion across trials.** Moving fraction, speed and longest stall per trial (already in
   the preprocess QC records). Fatigue should show as slower and stiller; learning as faster
   traversal between the patches.
3. **Baseline and open-loop trials.** Every session also has `baseline/` and
   `openloop_training/`, which no analysis has used. They give a no-reward locomotion reference
   for whether walking speed alone explains the drop.
4. **Per-fly slope.** Fit dwell against trial order over all 60 trials instead of splitting at
   the median, one slope per fly, then a paired exact sign-flip test across flies (the same test
   `selected_analysis/figures.py` uses). Do it per patch and per phase.

## Outputs planned

- per-fly slope table (fly, phase, patch, slope, n trials)
- dwell against trial order, flies as thin lines and the mean in bold, training and probing side
  by side
- the same for speed and moving fraction
- a training-minus-probing slope comparison

## Caveats

- **Cohort.** These flies leave much earlier (median about 12-14 s) than the poster's cohort
  (about 22-25 s). A within-session shift and a cohort difference can look alike, so check the
  cohort question first.
- **Selection.** The recommended selection kept 1,423 of 1,424 trials, so it removes almost
  nothing here. Slopes are therefore over essentially every trial, including any bad ones.
- **Dwell definition.** Use the survival table's per-visit dwell (bins per episode) so numbers
  match `selected_analysis`.

## Inputs

`selected_analysis/runs/<name>/<task tag>/survival.csv` for dwell, and the per-trial CSVs listed
in each selection json for speed. It would be built as a further `selected_analysis` pipeline
step or a sibling pipeline reading the same `runs/` folders.
