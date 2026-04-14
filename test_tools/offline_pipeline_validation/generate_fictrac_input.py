#!/usr/bin/env python3
"""Generate synthetic FicTrac-format input timeline for offline validation."""

import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    dt_sec: float = 1.0 / 120.0
    gain_dz: float = 3.9
    z0: float = 0.01
    path_length: float = 130.0
    stop_z: float = 125.0
    fast_speed: float = 5.0
    slow_speed: float = 0.5


def speed_for_z(z: float, fast_speed: float, slow_speed: float) -> float:
    """Boundary policy is inclusive for both slow zones."""
    if 20.0 <= z <= 40.0:
        return slow_speed
    if 100.0 <= z <= 120.0:
        return slow_speed
    return fast_speed


def next_z(z: float, dz: float, z0: float, gain_dz: float, path_length: float) -> float:
    """Replay calc_path z update and wrap/floor logic."""
    new_z = z + gain_dz * dz
    if new_z < z0:
        return z0
    if path_length > 0:
        return z0 + ((new_z - z0) % path_length)
    return new_z


def main() -> None:
    scenario = Scenario()
    out_path = "fictrac_input.csv"
    z = scenario.z0
    frame = 0

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "dt_sec", "ds", "df", "dr"])

        while z < scenario.stop_z:
            desired_speed = speed_for_z(z, scenario.fast_speed, scenario.slow_speed)
            # Approximation from pipeline assumptions: ds=0, dr=0, heading~0 => dz ~= df.
            # Then z_dot ~= gain_dz * df, so choose df from desired z speed.
            df = desired_speed / scenario.gain_dz
            ds = 0.0
            dr = 0.0
            writer.writerow([frame, f"{scenario.dt_sec:.9f}", f"{ds:.9f}", f"{df:.9f}", f"{dr:.9f}"])

            dz = df  # with ds=0 and r held at 0 (gain_r=0), calc_path transform reduces to dz=df.
            z = next_z(z, dz, scenario.z0, scenario.gain_dz, scenario.path_length)
            frame += 1

    print(f"Wrote {out_path} with {frame} frames.")


if __name__ == "__main__":
    main()
