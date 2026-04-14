#!/usr/bin/env python3
"""Emulate calc_path.py update loop from offline FicTrac input."""

import csv
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CalcPathParams:
    gain_ds: float = 1.0
    gain_df: float = 1.0
    gain_dr: float = 1.0
    gain_dx: float = 0.0
    gain_dz: float = 3.9
    gain_r: float = 0.0
    z0: float = 0.01
    path_length: float = 130.0


def calculate_dx_dz(ds: float, df: float, r: float, ds_gain: float, df_gain: float) -> tuple[float, float]:
    local_x = ds_gain * ds
    local_z = df_gain * df
    cos_r = math.cos(r)
    sin_r = math.sin(r)
    dx = local_x * cos_r - local_z * sin_r
    dz = local_x * sin_r + local_z * cos_r
    return dx, dz


def update_z(z: float, dz: float, p: CalcPathParams) -> float:
    new_z = z + p.gain_dz * dz
    if new_z < p.z0:
        return p.z0
    if p.path_length > 0:
        return p.z0 + ((new_z - p.z0) % p.path_length)
    return new_z


def main() -> None:
    params = CalcPathParams()
    in_path = "fictrac_input.csv"
    out_path = "calc_path_emulated.csv"

    x = 0.0
    z = params.z0
    r = 0.0
    t_sec = 0.0
    row_count = 0

    with open(in_path, "r", newline="", encoding="utf-8") as in_f, open(
        out_path, "w", newline="", encoding="utf-8"
    ) as out_f:
        reader = csv.DictReader(in_f)
        writer = csv.writer(out_f)
        writer.writerow(["t_sec", "z", "x", "r"])
        writer.writerow([f"{t_sec:.9f}", f"{z:.9f}", f"{x:.9f}", f"{r:.9f}"])

        for row in reader:
            dt = float(row["dt_sec"])
            ds = float(row["ds"])
            df = float(row["df"])
            dr = float(row["dr"])

            r_step = params.gain_dr * dr
            r = params.gain_r * r_step + r

            dx, dz = calculate_dx_dz(ds, df, r, params.gain_ds, params.gain_df)
            _ = dx * params.gain_dx  # kept for faithfulness; x remains constant with gain_dx=0.
            z = update_z(z, dz, params)
            t_sec += dt

            writer.writerow([f"{t_sec:.9f}", f"{z:.9f}", f"{x:.9f}", f"{r:.9f}"])
            row_count += 1

    print(f"Wrote {out_path} with {row_count + 1} timepoints.")


if __name__ == "__main__":
    main()
