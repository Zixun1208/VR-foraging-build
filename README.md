# Time-based trial foraging (VR)

Python and shell tooling to run **closed-loop VR foraging** on flies with **FicTrac** (ball tracking), **Unity** (visual world), and **NI-DAQ** LED rewards. Sessions are organized into **time-limited trials** (training vs probing) within iterations, with optional **open-loop training** and **baseline** blocks.

## What each part does

| Component | Role |
|-----------|------|
| `calc_path.py` | Listens for FicTrac UDP data, integrates position/orientation, sends pose to Unity on UDP. |
| `con_led.py` | Listens for reward cues from Unity (UDP), drives the reward LED via NI-DAQ with configurable zone decay; logs flash events to CSV. |
| `openloop_sim.py` | Feeds scripted position/orientation over UDP for open-loop training (no fly-driven motion). **Not launched by `run_experiment.sh`** — run it by hand; the continuous teleport-driven design does not start it, so openloop trials scheduled by the coordinator currently still run on live FicTrac input. |
| `con_lum.py` | Sets up / controls ambient LED illumination (separate from reward). |
| `run_experiment.sh` | Orchestrates FicTrac, Unity, Python helpers, trial timers, logs, and inter-session gaps. |
| `exp_gui.py` | Desktop UI to edit paths and timing parameters, save `experiment_config.json`, and launch the bash workflow. |
| `experiment_defaults.json` | Shipped experiment parameters — the single source of truth for defaults (see Configuration). |
| `experiment_config.json` | Per-machine GUI working copy (untracked): paths plus any parameter overrides. |
| `ports.py` | The UDP wiring, declared once for the Python side (see UDP ports). |
| `led_selftest.py` (in `test_tools/`) | Standalone bench tool: lists NI-DAQ hardware and drives LED pulses without Unity/FicTrac. |

## Session flow (high level)

1. **Open-loop training** (optional): repeated blocks of `openloop_sim.py` + Unity + reward script; duration and iteration count are configurable.
2. **Baseline** (optional): closed-loop with rewards disabled in probing-style zones; useful for habituation or controls.
3. **Main loop**: for each iteration, run **N training trials** (time-capped, with reward zones), then **M probing trials** (typically rewards off), with **inter-session** pauses between trials.

Trial length is controlled by **session time** (seconds), not by a fixed step count, hence “time-based” trials.

## Requirements

- Linux (paths and scripts assume a POSIX shell).
- **FicTrac** built and a camera config (e.g. `config.txt`).
- **Unity** Linux player for your foraging scene, invoked with `--csvDirectory` pointing at the session CSV folder.
- **Python 3** with `numpy`, `numba` (`calc_path.py`), **`nidaqmx`** (`con_led.py`), and **`ttkbootstrap`** (`exp_gui.py`). The sample `run_experiment.sh` activates a Conda env named `daqcon`—adjust to match your setup.
- **NI-DAQ** hardware and channels matching `con_led.py` (default channel is edited in that file).

## Configuration

1. **`experiment_defaults.json`** (tracked) holds the shipped experiment parameters — iteration counts, zone specs, voltages, decay mode. It is the single source of truth: `run_experiment.sh`, `exp_gui.py` and `con_led.py` all read it through `experiment_defaults.py`, so no launcher can silently disagree with another. Edit it to change the protocol.
2. **`experiment_config.json`** (untracked, per-machine) is the GUI's working copy: absolute paths for the Unity binary, FicTrac binary/config, this repo's scripts, log working directory, and raw CSV root, plus any parameter overrides. Precedence at run time is **CLI flag > `experiment_config.json` > `experiment_defaults.json`**.
3. Or run **`python exp_gui.py`**, browse to those paths, set iteration counts, **training / probing session times (seconds)**, trials per iteration, open-loop and baseline options, then save.
4. **`run_experiment.sh`** also supports environment variable overrides (e.g. `UNITY_EXE`, `FICTRAC_EXE`, `CALC_PATH`, `CON_LED`, `WORKING_DIR`, `CSV_MAIN_DIR`) for machines where you don’t want hard-coded paths.

## Running

**GUI (recommended for interactive use):**

```bash
python exp_gui.py
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

Any flag you omit falls back to `experiment_defaults.json`.

## Pre-flight and runtime checks

`run_experiment.sh` refuses to start unless the required binaries are present and
executable, the UDP ports are free, and the NI-DAQ AO channel can actually be
reserved (`con_led.py --check-daq` opens the channel and writes 0 V — merely
enumerating it would miss a device held by a crashed run). The requested AO
channel is **not** silently substituted; pass `--allow-ao-fallback` if you want
the old behavior.

While a session runs, each component is monitored. If FicTrac, `calc_path`,
`con_led` or Unity dies, the run aborts rather than recording remaining trials
with a missing signal chain — `--abort-on-component-failure 0` reverts to
warn-only.

Logs and per-trial stdout/stderr land under the session working directory (see `run_experiment.sh` for `logs/` layout). Raw CSV outputs are written under the configured `csv_main_dir` tree.

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

## License

See [LICENSE](LICENSE) (MIT).
