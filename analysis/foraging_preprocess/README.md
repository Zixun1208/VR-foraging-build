# foraging_preprocess

Self-contained. Copy this directory to any machine and run `preprocess.py` — no
install, no packaging, no dependencies outside numpy and matplotlib.

Take one fly patch-foraging session straight off the rig, format it, check it, and
get a recommended trial selection.

The rig writes `<acq-root>/<YYYYMMDD_HHMMSS>/` holding one continuous
`unity/CameraLog_*.csv` and a `flash_events/` directory with one LED log per trial.
Nothing downstream can read that, because the analysis wants per-trial trajectory
CSVs. This closes the gap and then does the visual check you would otherwise do by
hand in a notebook.

## Install

There is nothing to install. **Copy this directory to the machine and run it.**

```
scp -r foraging_preprocess/ rig-machine:~/
ssh rig-machine
cd ~/foraging_preprocess
python preprocess.py --acquisition 20260810_153938
```

Requirements: Python ≥3.9, numpy, matplotlib (`pip install -r requirements.txt`).
`pandas` is only needed to build the FicTrac turn cache on a machine that does not
have the `foraging` analysis package.

Every module here imports only from this directory and the standard library — the
camera-log slicer is vendored and the figures have native implementations — so the
directory is the whole thing. It can live anywhere; `python /any/path/preprocess.py`
works from any working directory.

## Use

```
python preprocess.py --acquisition 20260810_153938              # ATR-fed (default)
python preprocess.py --acquisition 20260810_153938 --atr no     # non-ATR control
```

Four steps, run in order; `--steps` picks a subset:

| step | what it does |
|---|---|
| `ingest` | copies the acquisition folder to `<raw-root>/<date>/<task>/<sub>/`, slices the camera log into per-trial CSVs, attaches FicTrac and builds its turn cache |
| `qc` | per-trial metrics: duration, corridor coverage, whether the fly reached the end, patch entries and dwells, moving fraction, longest stall |
| `recommend` | writes `session_selection_recommended_<date>_<sub>.json` — which trials to keep, and for each rejected one, why |
| `figures` | per-trial trajectories, occupancy heatmap, speed heatmap, and the across-trial average — into `<session>/qc/` |

```
# re-check an already-formatted session
python preprocess.py --date 2026-07-23 --sub sub-1 --steps qc,recommend,figures

# accept the recommendation (backs up any existing selection first)
python preprocess.py --date 2026-08-10 --steps recommend --apply
```

## A whole day at once

`--batch` turns `--date` from naming one session into naming a day: it finds
every acquisition folder that started on that date, flags the ones that look
too short to be a real session (aborted almost immediately), lets you confirm
or extend that archive list, then preprocesses what is left as `sub-1`,
`sub-2`, ... in the order each one actually started. `--acquisition` and
`--sub` are ignored in this mode.

```
python preprocess.py --batch --date 2026-09-11
```

Flagged runs are moved (not deleted) to `<acq-root>/_archived/`, which is what
makes re-running this for the same date safe — they simply will not turn up
again. Which acquisition became which `sub-N` is remembered in
`<raw-root>/<date>/.run_day_manifest.json`, so a later run that finds new
acquisitions for the same date appends `sub-(N+1)`, ... instead of renumbering
sessions already processed.

```
python preprocess.py --batch --date 2026-09-11 --yes       # auto-archive flagged runs, no prompts
python preprocess.py --batch --date 2026-09-11 --dry-run   # show the plan, touch nothing
```

`--dry-run` isn't required — without it, `--batch` just runs, prompting you as
it goes. It's there because two things it does aren't casually undone: it
moves folders on disk (archiving), and once an acquisition gets a `sub-N` that
number is permanent (recorded in the manifest, never reused). Run `--dry-run`
first when you're not sure the short-session heuristic will call it right, or
just to sanity-check the acquisition count for the date before anything moves;
skip it if you already know what that day's runs look like.

Every other flag (`--atr`, `--steps`, thresholds, roots, ...) applies to each
acquisition it runs, e.g. `--batch --date 2026-09-11 --atr no`.

## Configuring a machine

Every path is a flag, and each also reads an environment variable, so a machine can
be configured once in a shell profile:

| flag | variable | default |
|---|---|---|
| `--experiment-config` | `FORAGING_EXPERIMENT_CONFIG` | `~/Experiment_builds/VR-foraging-build/experiment_config.json` |
| `--raw-root` | `FORAGING_RAW_ROOT` | `~/Raw_data` |
| `--acq-root` | `FORAGING_ACQ_ROOT` | `csv_main_dir` from the rig config, else `<raw-root>/foraging` |
| `--fictrac-root` | `FORAGING_FICTRAC_ROOT` | `~/fictrac/foraging` |
| `--explog-root` | `FORAGING_EXPLOG_ROOT` | `working_dir` from the rig config, else `~/Experiment_log` |
| `--analysis-root` | `FORAGING_ANALYSIS_ROOT` | `~/Analysis` |

```
export FORAGING_RAW_ROOT=/data/Raw_data
export FORAGING_FICTRAC_ROOT=/data/fictrac/foraging
```

`--analysis-root` matters only for `--plots analysis`.

## The task comes from the rig's own config

Nothing is guessed from the recorded data. The task is read from the rig's
`experiment_config.json` — by default
`~/Experiment_builds/VR-foraging-build/experiment_config.json`, overridable with
`--experiment-config` or `$FORAGING_EXPERIMENT_CONFIG`. It supplies `path_length`,
both zones' voltage range, and each zone's decay duration (`training_zones` is
`zone:decay_seconds`; `none` disables the LED, which is what makes probing trials
probing), giving:

```
foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50
```

That config also records `csv_main_dir` and `working_dir`, so the acquisition and
experiment-log roots default to whatever the rig is actually using — one less thing
to configure per machine.

**Authority runs in this order**, and the middle rule matters:

1. `--task`, if you pass it;
2. for a session that is **already formatted**, its own directory name;
3. otherwise, `experiment_config.json`.

Rule 2 exists because the config describes the build *as it is now*. Re-processing a
months-old session against a newer config would silently rename it to whatever the
rig does today.

Where the config and the recorded flash logs disagree, you get warnings rather than a
silent decision:

```
[warn] config vs recorded data: zone1 start voltage: config says 1.5 V, the flash logs recorded 2.5 V
[warn] config vs recorded data: zone1 decay: config says 20.0 s, the flash logs show 50 s
[warn] training: 10 trials on disk, config expects 30 — the session was cut short or restarted
```

**Two things the config does not contain.** The **patch band positions** live in the
Unity scene, not in any JSON, so they are flags — `--patch1 20-40 --patch2 100-120`,
which are the defaults and feed both the task name and the dwell metrics. And
whether the fly was fed all-trans-retinal.
`--atr` defaults to `yes`; pass `--atr no` for a control, which appends the
`_non-atr` suffix, or `--atr unknown` to leave it unstated. Whatever you pass is
written into the recommendation together with where it came from, so a control is
never silently indistinguishable from a reward-active fly months later. **This is
the one thing you must get right at ingest time** — it cannot be recovered from the
data afterwards.

## Trial selection

The recommendation goes to a **separate** file and is never promoted to the live
`session_selection_<date>_<sub>.json` unless you pass `--apply`, which backs up any
existing selection first. Hand curation is never silently overwritten.

It uses the same schema the analysis notebook already reads, so it drops straight
into an existing workflow, and it carries the thresholds that produced it plus a
full per-trial record:

```json
{
  "training_indices": [0, 2, 3, 4],
  "training_basenames": ["training_iter_1_...csv", "..."],
  "recommendation": {
    "atr": false,
    "atr_source": "supplied on the command line",
    "thresholds": {"max_duration_sec": 900.0, "...": "..."},
    "trailing_dropoff": {"training": 24, "probing": null},
    "trials": [{"index": 9, "keep": false,
                "reasons": ["never reached x>=125 (max 102.6)"]}]
  }
}
```

Default rules — every one is a flag:

| threshold | default | rejects |
|---|---|---|
| `--require-reached-end` | `yes` | the fly never completed the 0→130 traversal |
| `--min-duration-sec` | 5 | truncated or degenerate trials |
| `--max-duration-sec` | 900 | a stuck rig, or a fly left running |
| `--min-moving-fraction` | 0.05 | the fly barely moved |
| `--speed-floor` | 0.5 | units/s below which it counts as still |
| `--max-stall-sec` | 300 | one long motionless stretch |
| `--require-both-patches` | `no` | (off — a skipped patch is data, not an error) |

`trailing_dropoff` flags where a session stops being usable and never recovers,
which is the common failure: the fly stops walking partway through. It is reported
as a hint, not applied as a rule.

## Files

| file | what it holds |
|---|---|
| `preprocess.py` | the CLI, the single-acquisition step sequence, and `--batch` for a whole day |
| `config.py` | filesystem roots, task geometry, QC thresholds |
| `expconfig.py` | reading the rig's `experiment_config.json` — the task authority |
| `tasks.py` | reading the flash logs, used only to cross-check the config |
| `ingest.py` | acquisition folder → formatted session, FicTrac attach |
| `qc.py` | per-trial metrics, keep/drop rules, the recommendation file |
| `plots.py` | the four figure families |
| `slicer.py` | corridor position -> per-trial CSVs; see [Slicing: why not by timestamp](#slicing-why-not-by-timestamp) |

`slicer.py` started as a copy of `~/Analysis/slice_camera_log.py` but has since
diverged on purpose (see below) and should now be treated as the canonical
version — port the fix upstream if `~/Analysis` still needs to match.

## Figures

Written to `<session>/qc/`, per phase:

- **trajectories** — one panel per trial, position against time, rejected trials in red
- **occupancy** — trials × corridor position, log-scaled
- **speed** — trials × corridor position
- **average** — across-trial mean occupancy and mean speed against position, ±sem

`--figures-all-trials` includes the rejected ones. `--plots analysis` uses the
`foraging` package from `--analysis-root` instead, so figures match that notebook
exactly; it needs that package present.

## Slicing: why not by timestamp

A trial's sliced CSV should start with the fly at the corridor's beginning
(position ~0) right after a teleport. An earlier version of `slicer.py` could
instead produce a file that *starts* around position 100-130 and drops to ~0
partway through — a few leftover rows, sometimes over a hundred, genuinely
belonging to the *previous* trial.

The cause was structural: that version cut the continuous camera log using
wall-clock windows `[flash_event_time, next_flash_event_time)`, and
`flash_event_time` comes from a different process's clock than the camera
log's own timestamps. `trial_coordinator.py` stamps a new trial's start the
instant it receives the `teleport_boundary` UDP message from `calc_path.py` —
which fires *before* `calc_path.py` sends the corrected position to Unity for
logging. In production data that declared timestamp has been measured up to
~89 seconds earlier than the actual reset visible in the camera log, so the
old window could start while the log was still recording the tail end of the
fly finishing the previous trial.

The fix: find the teleport directly in the camera log's own position column —
a sharp drop from near the corridor's far end to near its start, which is a
teleport full stop, independent of any other process's clock. Flash-event
files still give each teleport-bounded row range its identity
(phase/iteration/trial/output filename), matched by **order**, not by
timestamp proximity: every trial phase (`openloop_training`, `baseline`,
`initial_training`, `training`, `probing`) gets exactly one flash-event file
and exactly one teleport in the same sequence, so the k-th detected teleport
pairs with the k-th flash-event file. `training`, `probing`,
`openloop_training` and `baseline` windows each get written to their own
subdirectory; `initial_training` is the one phase never written out at all —
it's `con_led.py`'s own hard-coded output path before it hears from
`trial_coordinator.py`, describing the same first trial a second time, so
it's excluded from the ordinal count entirely rather than treated as its own
trial. `slice_camera_log` only writes whatever phases are keys in the
`out_dirs` mapping it's given, so a caller that only wants training/probing
can still pass just those two.

This can't fix data that was never recorded: if the rig itself drops enough to
throw off the count — a lost UDP packet, or the session ending mid-trial —
`slicer.py` says so loudly (`[warn] N flash events but M teleport(s)
detected...`) and leaves the affected trial's file empty rather than guessing
a boundary. An empty trial file shows up downstream as "file empty or
unreadable" in the QC table, which is a reason to look at that specific
trial by hand, not a bug.
