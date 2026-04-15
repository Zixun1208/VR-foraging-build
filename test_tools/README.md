# Test Tools

This directory contains test-only scripts and data for validating movement/flash logic without changing the main experiment pipeline.

## Contents

- `fictrac_socket_stub.py`
  - FicTrac replacement sender (UDP) for simulation mode.
- `flash_logic_socket_test.py`
  - Standalone flash scheduling/delay checker with optional Unity forwarding.
- `offline_pipeline_validation/`
  - Offline generator/emulator/validator scripts and CSV outputs.

## Offline pipeline validation

Run from `test_tools/offline_pipeline_validation`:

```bash
python3 generate_fictrac_input.py
python3 emulate_calc_path.py
python3 generate_expected_flash.py
python3 validate_expected.py
```

Expected validator output:

```text
VALIDATION PASS
total_flashes=33
zone_checks_passed=33/33
amplitude_checks_passed=33/33
failure_count=0
```

Generated CSV files:

- `fictrac_input.csv`
- `calc_path_emulated.csv`
- `expected_flash.csv`

## FicTrac sim sender only

Run from repository root:

```bash
python3 test_tools/fictrac_socket_stub.py --profile forward --hz 120 --df 0.03
```

This sends FicTrac-style UDP packets to `127.0.0.1:1317` for `calc_path.py`.

## Flash logic socket test

Run from repository root:

```bash
python3 test_tools/flash_logic_socket_test.py --self-stimulus --runtime-sec 20 --csv-output test_tools/flash_logic_test.csv
```

With Unity forwarding:

```bash
python3 test_tools/flash_logic_socket_test.py --self-stimulus --unity-forward --runtime-sec 20 --csv-output test_tools/flash_logic_test.csv
```

Default Unity target is `127.0.0.1:1318`.

Auto-launch Unity from the same command:

```bash
python3 test_tools/flash_logic_socket_test.py --self-stimulus --unity-forward --auto-launch-unity --runtime-sec 20 --csv-output test_tools/flash_logic_test.csv
```

Optionally auto-launch additional commands (repeatable flag):

```bash
python3 test_tools/flash_logic_socket_test.py --self-stimulus --unity-forward --auto-launch-unity --auto-launch-cmd "python3 test_tools/fictrac_socket_stub.py --profile forward" --runtime-sec 20 --csv-output test_tools/flash_logic_test.csv
```

If Unity appears static, drive it through the same normal motion pipeline:

```bash
python3 test_tools/flash_logic_socket_test.py --auto-launch-unity --auto-launch-calc-pipeline --runtime-sec 20 --csv-output test_tools/flash_logic_test.csv
```

This launches `calc_path.py` plus `test_tools/fictrac_socket_stub.py` so Unity receives motion on `1318` via calc_path (matching production flow).

## Session output data structure

Every session creates two root trees, using a shared `{TIMESTAMP}` (`YYYYMMDD_HHMMSS`).

**Logs** — under `WORKING_DIR` (default `/home/kazama/Experiment_log/foraging/`):

```
{TIMESTAMP}/
├── run_experiment_{TIMESTAMP}.log       ← top-level script log
└── logs/
    ├── continuous/                      ← stdout/stderr for all long-running processes
    │   ├── fictrac_{T}.log
    │   ├── calc_path_{T}.log
    │   ├── con_led_{T}.log
    │   ├── unity_{T}.log
    │   ├── trial_coordinator_{T}.log
    │   └── trial_coordinator_stdout_{T}.log
    ├── training/
    │   └── iter_{N}_trial_{T}/          ← reserved per-trial log dirs
    ├── probing/
    │   └── iter_{N}_trial_{T}/
    ├── baseline/
    │   └── iter_{N}/
    └── openloop_training/
        └── iter_{N}/
```

**FicTrac working dir** — under `FICTRAC_WORKING_DIR` (default `/home/kazama/fictrac/foraging/`):

```
{TIMESTAMP}/                             ← FicTrac output files and config copies
```

**Raw CSV data** — under `CSV_MAIN_DIR` (default `/home/kazama/Raw_data/foraging/`):

```
{TIMESTAMP}/
├── training/                            ← per-trial path CSVs (calc_path, training phase)
│   └── training_iter_{N}_trial_{T}_{timestamp}.csv
├── probing/                             ← per-trial path CSVs (probing phase)
│   └── probing_iter_{N}_trial_{T}_{timestamp}.csv
├── baseline/                            ← per-trial path CSVs (baseline phase)
│   └── baseline_iter_{N}_{timestamp}.csv
├── openloop_training/                   ← per-trial path CSVs (open-loop phase)
│   └── openloop_training_iter_{N}_{timestamp}.csv
├── flash_events/                        ← flash ON event CSVs (con_led_exp.py)
│   └── {phase}_iter_{N}_trial_{T}_{timestamp}.csv
└── unity/                               ← files written by Unity (--csvDirectory)
                                         e.g. camera log CSV
```

**Path CSV format** (columns written by `calc_path.py`):

| Column | Description |
|--------|-------------|
| `t_sec` | Seconds elapsed since trial start (`trial_start_wall_time`) |
| `z` | Virtual corridor z position |
| `x` | Virtual corridor x position |
| `r` | Heading angle (radians) |

**File naming:** flash and path CSVs share the same base name (e.g. `training_iter_1_trial_1_{timestamp}.csv`), making it straightforward to pair them by name.
