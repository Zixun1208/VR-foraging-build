# VR foraging (closed-loop, teleport-driven trials)

Python and shell tooling to run **closed-loop VR foraging** on flies with **FicTrac** (ball tracking), **Unity** (visual world), and **NI-DAQ** LED rewards, plus an offline **analysis pipeline** that turns a finished run into QC'd per-trial data. A run is one continuous session: a trial ends when the fly walks off the far end of the corridor and is teleported back to the start, and the trial schedule (training vs probing, within iterations, with optional **open-loop training** and **baseline** blocks) advances on each teleport.

## What each part does

| Component | Role |
|-----------|------|
| `calc_path.py` | Listens for FicTrac UDP data, integrates position/orientation, sends pose to Unity on UDP. When z reaches `path_length` it wraps the fly back to `trial_start_z` and emits a teleport boundary event. |
| `trial_coordinator.py` | Owns the trial schedule. Advances to the next trial on each teleport boundary, tells `con_led.py` which zones are active and which flash CSV to write, and exits after the last trial (which ends the run). |
| `con_led.py` | Listens for reward cues from Unity (UDP), drives the reward LED via NI-DAQ analog output with configurable zone decay; logs flash events to one CSV per trial. `--check-daq` is the pre-flight probe. |
| `openloop_sim.py` | Feeds scripted position/orientation over UDP for open-loop training (no fly-driven motion). **Not launched by `run_experiment.sh`** — run it by hand; the continuous teleport-driven design does not start it, so openloop trials scheduled by the coordinator currently still run on live FicTrac input. |
| `con_lum.py` | Interactive prompt to switch the ambient LED (a DAQ digital line, set in the file) on/off. Separate from reward. |
| `run_experiment.sh` | Orchestrates one run: pre-flight checks, then FicTrac, the coordinator, `calc_path`, `con_led` and Unity; monitors them and tears everything down when the coordinator finishes. |
| `exp_gui.py` | NiceGUI web UI (http://127.0.0.1:8080) to edit paths and parameters, save `experiment_config.json`, launch `run_experiment.sh`, and stream its log. Uses `local_file_picker.py` for path browsing. |
| `experiment_defaults.json` | Shipped experiment parameters — the single source of truth for defaults (see Configuration). |
| `experiment_defaults.py` | Loads those defaults for every entry point (`--shell` emits them for `run_experiment.sh`). |
| `experiment_config.json` | Per-machine GUI working copy (**gitignored**): paths plus any parameter overrides. Also read by the analysis pipeline. |
| `experiment_config.template.json` | Tracked starting point for a new machine — copy it to `experiment_config.json` and fill in the paths. |
| `ports.py` | The UDP wiring, declared once for the Python side (see UDP ports). Run directly, it checks the ports are free. |
| `log_markers.py` | `[PREFLIGHT …]` / `[COMPONENT …]` log prefixes shared by the launcher, `con_led.py` and the GUI's notifications. |
| `analysis/foraging_preprocess/` | Offline pipeline: acquisition → per-trial CSVs → QC → trial-selection recommendation → figures (see Analysis). |
| `test_tools/` | Local bench tools (**gitignored, not in the repo**), e.g. `led_selftest.py` (drives LED pulses without Unity/FicTrac) and `fictrac_socket_stub.py` (needed for `--use-fictrac-sim 1`). |

## Session flow (high level)

`trial_coordinator.py` runs this schedule, one trial per teleport:

1. **Open-loop training** (optional): `openloop_training_iterations` trials using `openloop_zones`.
2. **Baseline** (optional): `baseline_iterations` trials using `baseline_zones` (typically rewards off); useful for habituation or controls.
3. **Main loop**: for each of `iterations`, **N training trials** (`training_zones`) then **M probing trials** (`probing_zones`, typically rewards off).

There is no inter-trial interval and no per-trial timer: a trial lasts as long as the fly takes to traverse the corridor. Zone specs are `zone:decay_seconds` pairs, e.g. `0:50,1:50`; `none` disables the LED for that zone, which is what makes a probing trial a probing trial.

## Requirements

- Linux (paths and scripts assume a POSIX shell).
- **FicTrac** built and a camera config (e.g. `config.txt`).
- **Unity** Linux player for your foraging scene, invoked with `--csvDirectory` pointing at the session CSV folder.
- **Python 3** with `numpy`, `numba` (`calc_path.py`), **`nidaqmx`** (`con_led.py`, `con_lum.py`), and **`nicegui`** (`exp_gui.py`). `run_experiment.sh` activates a Conda env named `daqcon` from `~/miniconda3` — adjust `activate_conda` to match your setup.
- **NI-DAQ** hardware; the reward AO channel is `ao_channel` in `experiment_defaults.json` (or `--ao-channel`).
- For analysis only: Python ≥3.9 with `numpy` and `matplotlib` (`pandas` optional). No NI-DAQ, FicTrac or Unity needed.

## Configuration

1. **`experiment_defaults.json`** (tracked) holds the shipped experiment parameters — iteration counts, zone specs, voltages, decay mode. It is the single source of truth: `run_experiment.sh`, `exp_gui.py` and `con_led.py` all read it through `experiment_defaults.py`, so no launcher can silently disagree with another. Edit it to change the protocol.
2. **`experiment_config.json`** (untracked, per-machine) is the GUI's working copy: absolute paths for the Unity binary, FicTrac binary/config, this repo's scripts, log working directory, and raw CSV root, plus any parameter overrides. Precedence at run time is **CLI flag > `experiment_config.json` > `experiment_defaults.json`**. It's gitignored on purpose: every machine's paths are different, so tracking it just means merge conflicts on every pull. On a new machine, `cp experiment_config.template.json experiment_config.json` and fill in the (currently blank) path fields — the parameter fields already match `experiment_defaults.json`.
3. Or run **`python exp_gui.py`**, browse to those paths, set iteration counts, trials per iteration, zones, voltages, open-loop and baseline options, then save — this creates `experiment_config.json` for you if it doesn't exist yet.
4. **`run_experiment.sh`** reads paths from environment variables — `UNITY_EXE`, `FICTRAC_EXE`, `FICTRAC_CONFIG`, `CALC_PATH`, `CON_LED`, `TRIAL_COORDINATOR`, `WORKING_DIR`, `CSV_MAIN_DIR`, `FICTRAC_WORKING_DIR` — falling back to hard-coded paths under `/home/kazama`. The GUI sets these from its config; set them yourself on any other machine.

## Running

**GUI (recommended for interactive use):**

```bash
python exp_gui.py        # opens http://127.0.0.1:8080
```

**Headless / scripted:**

```bash
chmod +x run_experiment.sh
./run_experiment.sh \
  --iterations 6 \
  --training-trials-per-iteration 5 \
  --probing-trials-per-iteration 1 \
  --training-zones 0:50,1:50 \
  --ao-channel cDAQ1Mod3/ao0
```

Any parameter flag you omit falls back to `experiment_defaults.json`. Parameter
flags: `--iterations`, `--training-trials-per-iteration`,
`--probing-trials-per-iteration`, `--openloop-training-iterations`,
`--baseline-iterations`, `--path-length`, `--{openloop,baseline,training,probing}-zones`,
`--ao-channel`, `--{max,min}-amplitude-volts-by-zone`, `--{max,min}-amplitude-volts`,
`--flash-frequency-hz`, `--decay-mode`, `--trial-start-z`. Run-control flags:
`--use-fictrac-sim 1` (replace FicTrac with `test_tools/fictrac_socket_stub.py`)
and `--abort-on-component-failure 0` (warn instead of abort).

> Headless flags are **not** written to `experiment_config.json`. If you run
> headless with a protocol that differs from that file, pass `--task` to the
> analysis pipeline (see Analysis).

## Pre-flight and runtime checks

`run_experiment.sh` refuses to start unless the required binaries are present and
executable, the UDP ports are free, and the NI-DAQ AO channel can actually be
reserved (`con_led.py --check-daq` opens the channel and writes 0 V — merely
enumerating it would miss a device held by a crashed run). The requested AO
channel is **not** silently substituted; `con_led.py --allow-ao-fallback` restores
the old behavior, but `run_experiment.sh` has no flag for it.

While a session runs, each component is monitored. If FicTrac, `calc_path`,
`con_led` or Unity dies, the run aborts rather than recording remaining trials
with a missing signal chain — `--abort-on-component-failure 0` reverts to
warn-only.

## Where a run writes

Every run is stamped with one `TIMESTAMP` (`YYYYMMDD_HHMMSS`), which is also the
**acquisition id** the analysis pipeline takes:

```
<CSV_MAIN_DIR>/<TIMESTAMP>/unity/CameraLog_*.csv          one continuous Unity pose log
<CSV_MAIN_DIR>/<TIMESTAMP>/flash_events/<phase>_iter_<i>_trial_<t>_<TIMESTAMP_ms>.csv
                                                         one LED log per trial; its name carries the trial start
<FICTRAC_WORKING_DIR>/<TIMESTAMP>/fictrac-*.dat          FicTrac output
<WORKING_DIR>/<TIMESTAMP>/logs/                          one log per component for the whole run
```

A run is one continuous session, so each component writes one log for the whole
run, flat in `logs/` with no per-phase or per-trial subdirectories. That log
directory is the only thing created before pre-flight; the FicTrac working
directory and the raw CSV directories are created only once pre-flight passes,
so an aborted launch leaves no empty tree behind.

## UDP ports — a frozen wire protocol

| Port | From | To | Notes |
|------|------|-----|-------|
| 1317 | FicTrac | `calc_path.py` | |
| 1318 | `calc_path.py` | Unity | Unity side: `receivePort` |
| 1319 | Unity | `con_led.py` | Unity side: `sendPort` (reward cues) |
| 1320 | `trial_coordinator.py` | `con_led.py` | trial metadata |
| 1321 | `calc_path.py` | `trial_coordinator.py` | teleport boundary events |

The Python side declares these once, in **`ports.py`**. **That file does not
control Unity.** Unity's two ports are `public int` Inspector fields on
`Closed_loop_client.cs`, serialized into every `.unity` scene and frozen into
each built player. Changing 1318 or 1319 therefore means editing the C#, every
scene that serializes those fields, *and* rebuilding every player still in use —
so treat these numbers as fixed and verify rather than re-centralize them.

`run_experiment.sh` checks before launch that 1317/1319/1320/1321 are free. A
port still bound means a process from a previous run survived and would silently
eat the packets the new run expects — a session that records nothing. Find the
culprit with `lsof -iUDP:<port>`.

## Analysis

`analysis/foraging_preprocess/` takes the raw output of a run (see
[Where a run writes](#where-a-run-writes)) and produces a formatted session:
per-trial trajectory CSVs, QC metrics, a recommended trial selection, and
figures. It is self-contained (numpy + matplotlib, no install), runs from any
directory, and can be copied to another machine on its own. The full
step/flag/threshold reference is
[`analysis/foraging_preprocess/README.md`](analysis/foraging_preprocess/README.md);
this section is the workflow.

### 1. After a run: preprocess it

```bash
cd analysis/foraging_preprocess
pip install -r requirements.txt                 # once, if numpy/matplotlib are missing

# the whole day's runs (usual case)
python preprocess.py --batch --date 2026-09-11             # do it directly, prompting as it goes
python preprocess.py --batch --date 2026-09-11 --dry-run   # or preview the plan first, changes nothing

# or a single run, by its acquisition id (the run's TIMESTAMP)
python preprocess.py --acquisition 20260911_160349
```

`--dry-run` is optional, not a required first step — worth reaching for when
you're unsure the short-session heuristic will call a day's runs right, since
archiving moves folders and a `sub-N` assignment is permanent once made.

**Always state ATR status.** `--atr` defaults to `yes`. For a non-ATR control
pass `--atr no` (adds the `_non-atr` task suffix); if you don't know, pass
`--atr unknown`. Nothing in the raw files records it, so a wrong value cannot be
fixed from the data later.

What happens, in order (`--steps` picks a subset of `ingest,qc,recommend,figures`):

1. **ingest** — copies `unity/` and `flash_events/` from `<acq-root>/<acq-id>/` into
   `<raw-root>/<date>/<task>/<sub>/`, slices the camera log into per-trial CSVs
   under `training/`, `probing/`, `openloop_training/` and `baseline/` (cut at
   teleports detected in the position column itself, not at flash-event
   timestamps — see
   [`analysis/foraging_preprocess/README.md`](analysis/foraging_preprocess/README.md#slicing-why-not-by-timestamp)
   for why that distinction matters), and copies the matching FicTrac `.dat`
   from `<fictrac-root>/<acq-id>/` plus a turn cache (`--skip-fictrac` skips
   this multi-GB copy). The raw acquisition folder is left untouched.
2. **qc** — prints a per-trial table for training/probing trials: duration,
   farthest x, moving fraction, longest stall, dwell in each patch, keep/drop
   verdict with reasons. Open-loop/baseline trials aren't foraging trials, so
   they're sliced but not QC'd.
3. **recommend** — writes `session_selection_recommended_<date>_<sub>.json`.
4. **figures** — trajectories, occupancy and speed heatmaps, and across-trial
   averages into `<session>/qc/`.

`--batch` finds every acquisition that started on `--date`, flags ones that look
aborted (no `unity/`, no flash-event files, or under 30 s), asks before moving
them to `<acq-root>/_archived/`, and processes the rest in start order. Add
`--yes` to archive flagged runs without prompting.

**Sub numbers are stable.** Each acquisition's `sub-N` is recorded in
`<raw-root>/<date>/.run_day_manifest.json`, for `--batch` and single
`--acquisition` runs alike. Re-running an acquisition reuses its number, and new
acquisitions on the same date get the next one. An explicit `--sub` overrides it
and does not touch the manifest.

### 2. Review and accept the trial selection

The recommendation is never used on its own. Look at the QC table and
`<session>/qc/` figures, then either accept it:

```bash
python preprocess.py --date 2026-09-11 --sub sub-1 --steps recommend --apply
```

`--apply` writes the live `session_selection_<date>_<sub>.json` that the analysis
notebook reads, backing up any existing one to `.bak` first. Or edit the
selection by hand. To re-check an already-formatted session with different
thresholds (e.g. `--max-stall-sec 120`, `--require-reached-end no`), rerun
without `ingest`:

```bash
python preprocess.py --date 2026-09-11 --sub sub-1 --steps qc,recommend,figures
```

### Where it reads and writes

| flag | env var | default |
|---|---|---|
| `--experiment-config` | `FORAGING_EXPERIMENT_CONFIG` | `~/Experiment_builds/VR-foraging-build/experiment_config.json` |
| `--acq-root` (run output) | `FORAGING_ACQ_ROOT` | `csv_main_dir` from that config, else `<raw-root>/foraging` |
| `--fictrac-root` | `FORAGING_FICTRAC_ROOT` | `~/fictrac/foraging` (matches the launcher's `FICTRAC_WORKING_DIR` default) |
| `--raw-root` (formatted sessions) | `FORAGING_RAW_ROOT` | `~/Raw_data` |
| `--analysis-root` | `FORAGING_ANALYSIS_ROOT` | `~/Analysis` (only for `--plots analysis`) |

A formatted session looks like:

```
<raw-root>/<date>/<task>/<sub>/
  unity/  flash_events/            copied from the acquisition
  training/  probing/              one trajectory CSV per trial
  openloop_training/  baseline/    same, when the protocol used them
  fictrac-*.dat  *.turn_c7_t24.npz
  session_selection_recommended_<date>_<sub>.json
  session_selection_<date>_<sub>.json   (only after --apply or hand curation)
  qc/                              figures
```

`openloop_training/` and `baseline/` are sliced the same way as
training/probing, but aren't QC'd, don't feed the trial-selection
recommendation, and don't get figures — those are about picking foraging
trials to analyze, and open-loop/baseline trials aren't foraging trials.
They're written out so the raw per-trial trajectories are still available if
you want to check a habituation or open-loop control by hand, and because the
expected-trial-count check (see below) now covers all four phases, not just
training/probing.

### Keeping analysis in step with the rig

- **The task name comes from `experiment_config.json`**, e.g.
  `foraging_non-iti_130_20-40_100-120_1.0v-0.1v_2.5v-0.1v_50_50` (corridor,
  patch bands, zone voltages, training-zone decays). It is **not** read from
  `experiment_defaults.json` or from headless CLI flags. So preprocess before
  changing the GUI config for the next protocol, or pass `--task` explicitly. A
  mismatch between the config and what the flash logs recorded is printed as a
  `[warn] config vs recorded data` line. Don't ignore it.
- **Expected trial counts also come from the config**: `iterations x
  training_trials_per_iteration` / `x probing_trials_per_iteration` for
  training/probing, and `openloop_training_iterations` /
  `baseline_iterations` directly (those two are one trial per iteration, no
  per-iteration multiplier). A mismatch against what's actually on disk
  prints `[warn] <phase>: N trials on disk, config expects M`.
- A session that is already formatted keeps its task from its directory name,
  so re-running QC on old sessions after a config change won't rename them.
- **Patch band positions live in the Unity scene**, not in any config. If a
  scene moves them, pass `--patch1 LO-HI --patch2 LO-HI` (defaults `20-40`,
  `100-120`).
- Only **training** and **probing** trials are sliced. Open-loop training and
  baseline trials (and con_led's startup `initial_training_*` CSV) are
  ignored by the pipeline.
- If you rename flash CSVs, change the `flash_events/` layout, or change the
  CameraLog format, update `analysis/foraging_preprocess/slicer.py` and
  `tasks.py`, which parse those names.

## License

See [LICENSE](LICENSE) (MIT).
