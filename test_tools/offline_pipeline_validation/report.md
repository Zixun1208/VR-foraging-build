# Offline pipeline report

This folder contains an offline, file-based reproduction of the current runtime chain:

`FicTrac line fields -> calc_path kinematics/update rules -> zone mapping -> con_led flash timing + amplitude decay`.

## Fixed scenario used

- `z0 = 0.01`
- `path_length = 130.0` (forward wrap enabled but not reached before stop)
- `dt_sec = 1/120`
- zone boundaries inclusive:
  - zone 0: `[20, 40]`
  - zone 1: `[100, 120]`
- speeds:
  - outside zones: `5.0 z-units/s`
  - inside zone 0 or 1: `0.5 z-units/s`
- gains match `calc_path.py`, including `gain_dz = 3.9`, `gain_r = 0.0`, `gain_dx = 0.0`
- LED parameters:
  - flash frequency: `50 Hz`
  - max amplitude: `5.0 V`
  - min amplitude: `0.2 V`
  - decay specs: zone 0 = `20 s`, zone 1 = `100 s`

## Approximation note

Input generation uses the same assumption requested for this offline scenario:

- `ds = 0`, `dr = 0`, heading remains near zero (`r` stays at `0` because `gain_r = 0`)
- therefore `dz ~= df` (exact under these assumptions)
- set `df = desired_speed / 3.9` so that `z_dot ~= gain_dz * df`

Discretization is by fixed `dt = 1/120`, so boundaries are reached on frame grid times.

## Stop condition

Input generation stops when next loop check sees `z >= 125`.
In this run, the final emulated point is `z = 125.01`, with no wrap event.

## Outputs from this run

- `fictrac_input.csv` : 97 frames
- `calc_path_emulated.csv` : 98 timepoints (includes initial state at `t=0`)
- `expected_flash.csv` : 33 flash events

## Validation result

- `VALIDATION PASS`
- zone checks: `33/33`
- amplitude checks: `33/33`
- failures: `0`
