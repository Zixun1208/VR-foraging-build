# Time-based trial foraging (VR)

Python and shell tooling to run **closed-loop VR foraging** on flies with **FicTrac** (ball tracking), **Unity** (visual world), and **NI-DAQ** LED rewards. Sessions are organized into **time-limited trials** (training vs probing) within iterations, with optional **open-loop training** and **baseline** blocks.

## What each part does

| Component | Role |
|-----------|------|
| `calc_path.py` | Listens for FicTrac UDP data, integrates position/orientation, sends pose to Unity on UDP. |
| `con_led.py` | Listens for reward cues from Unity (UDP), drives the reward LED via NI-DAQ with configurable zone decay; logs flash events to CSV. |
| `openloop_sim.py` | Feeds scripted position/orientation over UDP for open-loop training (no fly-driven motion). |
| `con_lum.py` | Sets up / controls ambient LED illumination (separate from reward). |
| `run_experiment.sh` | Orchestrates FicTrac, Unity, Python helpers, trial timers, logs, and inter-session gaps. |
| `exp_gui.py` | Desktop UI to edit paths and timing parameters, save `experiment_config.json`, and launch the bash workflow. |
| `experiment_config.json` | Paths and numeric parameters consumed by the GUI and passed into `run_experiment.sh`. |

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

1. Copy or edit **`experiment_config.json`**: set absolute paths for the Unity binary, FicTrac binary/config, this repo’s scripts, log working directory, and raw CSV root.
2. Or run **`python exp_gui.py`**, browse to those paths, set iteration counts, **training / probing session times (seconds)**, trials per iteration, open-loop and baseline options, then save.
3. **`run_experiment.sh`** also supports environment variable overrides (e.g. `UNITY_EXE`, `FICTRAC_EXE`, `CALC_PATH`, `CON_LED`, `WORKING_DIR`, `CSV_MAIN_DIR`) for machines where you don’t want hard-coded paths.

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
  --training-session-time 30 \
  --probing-session-time 30 \
  --training-trials-per-iteration 5 \
  --probing-trials-per-iteration 1 \
  --inter-session-time 10
```

Logs and per-trial stdout/stderr land under the session working directory (see `run_experiment.sh` for `logs/` layout). Raw CSV outputs are written under the configured `csv_main_dir` tree.

## UDP ports (default)

- **1317** — FicTrac → `calc_path.py`
- **1318** — position stream → Unity / open-loop sim
- **1319** — Unity → `con_led.py` (reward signaling)

Keep firewalls and any other consumers aligned with these ports.

## License

See [LICENSE](LICENSE) (MIT).
