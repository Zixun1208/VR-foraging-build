#!/usr/bin/env python3
"""Single source of truth for experiment parameter defaults.

Every entry point reads its defaults from experiment_defaults.json through this
module: run_experiment.sh (via --shell), exp_gui.py, and con_led.py. Previously
each carried its own copy and they drifted, so which launcher you used silently
changed the experiment.

Precedence at run time: command-line flag > experiment_config.json (the GUI's
per-machine working copy, untracked) > experiment_defaults.json (tracked).
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS_PATH = Path(__file__).resolve().parent / "experiment_defaults.json"

# JSON key -> shell variable name in run_experiment.sh. Parameters whose shell
# form is derived rather than copied (the by-zone voltage strings) are built in
# shell_assignments() instead.
_SHELL_VARS = {
    "openloop_training_iterations": "OPENLOOP_TRAINING_ITERATIONS",
    "baseline_iterations": "BASELINE_ITERATIONS",
    "iterations": "ITERATIONS",
    "training_trials_per_iteration": "TRAINING_TRIALS_PER_ITERATION",
    "probing_trials_per_iteration": "PROBING_TRIALS_PER_ITERATION",
    "path_length": "PATH_LENGTH",
    "openloop_zones": "OPENLOOP_ZONES",
    "baseline_zones": "BASELINE_ZONES",
    "training_zones": "TRAINING_ZONES",
    "probing_zones": "PROBING_ZONES",
    "ao_channel": "AO_CHANNEL",
    "flash_freq_hz": "FLASH_FREQUENCY_HZ",
    "decay_mode": "DECAY_MODE",
    "trial_start_z": "TRIAL_START_Z",
}


def load_defaults() -> dict[str, str]:
    """Return the shipped defaults as strings, keyed as in experiment_defaults.json."""
    with open(DEFAULTS_PATH, encoding="utf-8") as f:
        return {k: str(v) for k, v in json.load(f).items()}


def get(key: str, fallback: str = "") -> str:
    """Return one default, falling back if the file is missing or lacks the key.

    con_led.py must stay runnable standalone even if the defaults file is gone,
    so a missing file is not fatal here.
    """
    try:
        return load_defaults().get(key, fallback)
    except (OSError, ValueError):
        return fallback


def get_float(key: str, fallback: float) -> float:
    try:
        return float(get(key, str(fallback)))
    except ValueError:
        return fallback


def zone_volt_spec(defaults: dict[str, str], bound: str) -> str:
    """Build con_led's '0:<v>,1:<v>' per-zone voltage string. bound is 'max' or 'min'."""
    return f"0:{defaults[f'zone0_{bound}_volts']},1:{defaults[f'zone1_{bound}_volts']}"


def zone_volt_default(bound: str, fallback: str) -> str:
    """Per-zone voltage string from the defaults file, or fallback if unavailable."""
    try:
        return zone_volt_spec(load_defaults(), bound)
    except (OSError, ValueError, KeyError):
        return fallback


def shell_assignments() -> list[str]:
    """Emit `VAR=value` lines for run_experiment.sh to eval."""
    defaults = load_defaults()
    lines = []
    for key, var in _SHELL_VARS.items():
        lines.append(f"{var}={_quote(defaults[key])}")

    max_by_zone = zone_volt_spec(defaults, "max")
    min_by_zone = zone_volt_spec(defaults, "min")
    lines.append(f"MAX_AMPLITUDE_VOLTS_BY_ZONE={_quote(max_by_zone)}")
    lines.append(f"MIN_AMPLITUDE_VOLTS_BY_ZONE={_quote(min_by_zone)}")
    # con_led's scalar fallbacks must span every zone, or a per-zone value would
    # fall outside the DAQ range configured from them.
    lines.append(f"MAX_AMPLITUDE_VOLTS={_quote(str(max(float(defaults['zone0_max_volts']), float(defaults['zone1_max_volts']))))}")
    lines.append(f"MIN_AMPLITUDE_VOLTS={_quote(str(min(float(defaults['zone0_min_volts']), float(defaults['zone1_min_volts']))))}")
    return lines


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", action="store_true", help="Emit shell variable assignments to eval.")
    opts = parser.parse_args()
    if opts.shell:
        print("\n".join(shell_assignments()))
    else:
        print(json.dumps(load_defaults(), indent=2))
