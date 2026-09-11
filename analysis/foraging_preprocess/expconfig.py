"""Read the rig's own ``experiment_config.json`` -- the authority on the task.

This is what the experiment was actually run with, so it is the source of truth
for the task name, rather than anything reconstructed from the recorded data.

It gives the corridor length, both zones' voltage range, and each zone's decay
duration (``training_zones`` is ``zone:decay_seconds``, with ``none`` meaning the
LED is disabled for that zone -- which is what makes probing trials probing).

Two things it does NOT give:

* **the patch band positions** -- those live in the Unity scene, not here, so they
  stay flags with the standard 20-40 / 100-120 defaults;
* **ATR status** -- no file anywhere records whether the fly was fed retinal.

One caveat worth knowing: this file describes the build *as it is now*. Re-running
an old session against a newer build config would mislabel it, so a session that is
already formatted takes its task from its own directory name instead, and the config
is only consulted for fresh material. Where the flash logs disagree with the config,
you get a warning.
"""
from __future__ import annotations

import json
import os

DEFAULT_CONFIG = "~/Experiment_builds/VR-foraging-build/experiment_config.json"
ENV_VAR = "FORAGING_EXPERIMENT_CONFIG"


def config_path(explicit: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(
        explicit or os.environ.get(ENV_VAR) or DEFAULT_CONFIG))


def load(explicit: str | None = None) -> dict:
    path = config_path(explicit)
    if not os.path.isfile(path):
        raise SystemExit(
            f"no experiment config at {path}\n"
            f"Pass --experiment-config /path/to/experiment_config.json, set "
            f"${ENV_VAR}, or pass --task to name the task directly.")
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"could not read {path}: {e}") from e
    cfg["_path"] = path
    return cfg


def _zone_decays(spec: str) -> dict[int, float | None]:
    """Parse ``"0:50,1:none"`` into ``{0: 50.0, 1: None}``.

    ``none`` disables the LED for that zone (see con_led.parse_zone_decay_rates).
    """
    out: dict[int, float | None] = {}
    for pair in (spec or "").split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        zid_s, val = pair.split(":", 1)
        try:
            zid = int(zid_s)
        except ValueError:
            continue
        val = val.strip().lower()
        out[zid] = None if val == "none" else float(val)
    return out


def _fmt_volt(v: float) -> str:
    return f"{float(v):.1f}"


def _fmt_decay(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def task_from_config(cfg: dict, atr: bool | None, patch1, patch2) -> tuple[str, dict]:
    """Build the task folder name from the rig config. Returns ``(name, details)``."""
    try:
        corridor = int(float(cfg["path_length"]))
        v0_max, v0_min = float(cfg["zone0_max_volts"]), float(cfg["zone0_min_volts"])
        v1_max, v1_min = float(cfg["zone1_max_volts"]), float(cfg["zone1_min_volts"])
    except (KeyError, ValueError) as e:
        raise SystemExit(
            f"{cfg.get('_path')} is missing or malformed: {e}\n"
            "Expected path_length, zone0_max_volts/zone0_min_volts, "
            "zone1_max_volts/zone1_min_volts, training_zones.") from e

    decays = _zone_decays(cfg.get("training_zones", ""))
    missing = [z for z in (0, 1) if decays.get(z) is None]
    if missing:
        raise SystemExit(
            f"training_zones={cfg.get('training_zones')!r} in {cfg.get('_path')} "
            f"gives no decay duration for zone(s) {missing} "
            "('none' means the LED is disabled there).\n"
            "That config cannot name a task; pass --task explicitly.")

    name = (f"foraging_non-iti_{corridor}_"
            f"{int(patch1[0])}-{int(patch1[1])}_{int(patch2[0])}-{int(patch2[1])}_"
            f"{_fmt_volt(v0_max)}v-{_fmt_volt(v0_min)}v_"
            f"{_fmt_volt(v1_max)}v-{_fmt_volt(v1_min)}v_"
            f"{_fmt_decay(decays[0])}_{_fmt_decay(decays[1])}")
    if atr is False:
        name += "_non-atr"

    details = {
        "config_path": cfg.get("_path"),
        "corridor": corridor,
        "zone0": {"max_v": v0_max, "min_v": v0_min, "decay_s": decays[0]},
        "zone1": {"max_v": v1_max, "min_v": v1_min, "decay_s": decays[1]},
        "training_zones": cfg.get("training_zones"),
        "probing_zones": cfg.get("probing_zones"),
        "iterations": cfg.get("iterations"),
        "training_trials_per_iteration": cfg.get("training_trials_per_iteration"),
        "probing_trials_per_iteration": cfg.get("probing_trials_per_iteration"),
        "flash_freq_hz": cfg.get("flash_freq_hz"),
        "decay_mode": cfg.get("decay_mode"),
    }
    return name, details


def roots_from_config(cfg: dict) -> dict:
    """Roots the rig config already knows, for defaults when not overridden."""
    out = {}
    if cfg.get("csv_main_dir"):
        out["acq_root"] = os.path.expanduser(cfg["csv_main_dir"])
    if cfg.get("working_dir"):
        out["explog_root"] = os.path.expanduser(cfg["working_dir"])
    return out


def expected_trial_counts(cfg: dict) -> dict:
    """How many trials the config says a complete session should have."""
    def _int(key):
        try:
            return int(float(cfg.get(key, 0)))
        except (TypeError, ValueError):
            return 0
    iters = _int("iterations")
    return {"training": iters * _int("training_trials_per_iteration"),
            "probing": iters * _int("probing_trials_per_iteration")}


def cross_check(details: dict, evidence: dict) -> list[str]:
    """Compare the config against what the LED logs actually recorded.

    A mismatch means the config on disk is not the one this session was run with --
    usually a build that changed afterwards. Reported, never silently corrected.
    """
    problems = []
    for zone in (0, 1):
        want_v = details[f"zone{zone}"]["max_v"]
        got_v = evidence.get(f"zone{zone}_start_v")
        if got_v is not None and abs(float(got_v) - want_v) > 0.05:
            problems.append(
                f"zone{zone} start voltage: config says {want_v} V, "
                f"the flash logs recorded {got_v} V")
        want_d = details[f"zone{zone}"]["decay_s"]
        got_d = evidence.get(f"zone{zone}_decay_s")
        if got_d is not None and abs(float(got_d) - float(want_d)) > 1.5:
            problems.append(
                f"zone{zone} decay: config says {want_d} s, "
                f"the flash logs show {got_d} s")
    return problems
