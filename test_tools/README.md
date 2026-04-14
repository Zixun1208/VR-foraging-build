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
