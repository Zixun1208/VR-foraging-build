"""Where things live, and the QC thresholds.

Every root is resolved in the same order: an explicit CLI flag, then an
environment variable, then the default under the user's home. Nothing in this
package hard-codes a path to one machine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict

@dataclass
class Geometry:
    """Corridor layout.

    ``corridor`` comes from ``path_length`` in the rig's experiment_config.json.
    The patch bands do not: they live in the Unity scene, which is a binary, so
    they stay flags defaulting to the layout every task has used so far.
    """
    corridor: float = 130.0
    patch1: tuple = (20.0, 40.0)
    patch2: tuple = (100.0, 120.0)
    reached_end_x: float | None = None   # default: 5 units short of the far end

    @property
    def reached_end(self) -> float:
        return self.corridor - 5.0 if self.reached_end_x is None else self.reached_end_x

    @property
    def zones(self) -> tuple:
        return (self.patch1, self.patch2)


# Mutated once, by the CLI, before anything reads it. Modules reference
# ``config.GEOM`` rather than importing the values, so an override actually takes.
GEOM = Geometry()

_ENV = {
    "raw_root": "FORAGING_RAW_ROOT",
    "acq_root": "FORAGING_ACQ_ROOT",
    "fictrac_root": "FORAGING_FICTRAC_ROOT",
    "explog_root": "FORAGING_EXPLOG_ROOT",
    "analysis_root": "FORAGING_ANALYSIS_ROOT",
}

_DEFAULTS = {
    "raw_root": "~/Raw_data",
    "acq_root": "~/Raw_data/foraging",
    "fictrac_root": "~/fictrac/foraging",
    "explog_root": "~/Experiment_log",
    "analysis_root": "~/Analysis",
}


@dataclass
class Roots:
    """Filesystem layout of one rig machine."""
    raw_root: str
    acq_root: str
    fictrac_root: str
    explog_root: str
    analysis_root: str

    @classmethod
    def resolve(cls, **overrides) -> "Roots":
        vals = {}
        for key, default in _DEFAULTS.items():
            val = overrides.get(key) or os.environ.get(_ENV[key]) or default
            vals[key] = os.path.abspath(os.path.expanduser(val))
        # acq_root defaults to a subdirectory of raw_root, so follow raw_root
        # when only raw_root was overridden.
        if not overrides.get("acq_root") and not os.environ.get(_ENV["acq_root"]):
            vals["acq_root"] = os.path.join(vals["raw_root"], "foraging")
        return cls(**vals)

    def describe(self) -> str:
        return "\n".join(f"  {k:<14} {v}{'' if os.path.isdir(v) else '   [missing]'}"
                         for k, v in asdict(self).items())


@dataclass
class Thresholds:
    """QC rules. Whatever was actually used is recorded in the recommendation."""
    min_duration_sec: float = 5.0        # shorter is a truncated/degenerate trial
    max_duration_sec: float = 900.0      # longer is a stuck rig or a fly left running
    require_reached_end: bool = True     # the fly must complete the 0->130 traversal
    min_moving_fraction: float = 0.05    # fraction of frames above the speed floor
    speed_floor: float = 0.5             # units/s below which the fly counts as still
    max_stall_sec: float = 300.0         # longest single motionless stretch tolerated
    require_both_patches: bool = False   # off: a skipped patch is data, not an error

    def as_dict(self) -> dict:
        return asdict(self)
