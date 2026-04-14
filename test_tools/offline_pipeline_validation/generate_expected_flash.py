#!/usr/bin/env python3
"""Generate expected flash events from emulated z(t) and con_led logic."""

import csv
from bisect import bisect_right
from math import exp, log


def parse_zone_decay_rates(zones_str: str, max_amp: float, min_amp: float) -> dict[int, float | None]:
    zone_decay_constants: dict[int, float | None] = {}
    for zone_pair in zones_str.split(","):
        zone, decay_spec = zone_pair.split(":")
        if decay_spec.lower() == "none":
            zone_decay_constants[int(zone)] = None
        else:
            decay_time = float(decay_spec)
            if decay_time == 0.0:
                zone_decay_constants[int(zone)] = 0.0
            else:
                k = log(max_amp / min_amp) / decay_time
                zone_decay_constants[int(zone)] = k
    return zone_decay_constants


def zone_for_z(z: float) -> int | None:
    if 20.0 <= z <= 40.0:
        return 0
    if 100.0 <= z <= 120.0:
        return 1
    return None


def interpolate_z(t: float, times: list[float], zs: list[float]) -> float:
    if t <= times[0]:
        return zs[0]
    if t >= times[-1]:
        return zs[-1]

    right = bisect_right(times, t)
    i0 = right - 1
    i1 = right
    t0 = times[i0]
    t1 = times[i1]
    z0 = zs[i0]
    z1 = zs[i1]
    if t1 == t0:
        return z1
    alpha = (t - t0) / (t1 - t0)
    return z0 + alpha * (z1 - z0)


def main() -> None:
    calc_path = "calc_path_emulated.csv"
    out_path = "expected_flash.csv"

    max_amp = 5.0
    min_amp = 0.2
    flash_frequency_hz = 50.0
    flash_period_sec = 1.0 / flash_frequency_hz
    trial_start_wall_time = 0.0
    zone_decay_constants = parse_zone_decay_rates("0:20,1:100", max_amp, min_amp)

    times: list[float] = []
    zs: list[float] = []
    with open(calc_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["t_sec"]))
            zs.append(float(row["z"]))

    t_end = times[-1]
    flash_index = 0
    emitted = 0
    t = 0.0

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["expected_flash_time_sec", "zone", "elapsed_time_sec", "expected_amplitude_volts", "flash_index"]
        )

        while t <= t_end + 1e-12:
            z = interpolate_z(t, times, zs)
            zone = zone_for_z(z)
            if zone is not None:
                decay_constant = zone_decay_constants[zone]
                if decay_constant is not None:
                    elapsed_time_sec = max(0.0, t - trial_start_wall_time)
                    if decay_constant == 0.0:
                        amplitude = max_amp
                    else:
                        amplitude = max_amp * exp(-decay_constant * elapsed_time_sec)
                        amplitude = max(min_amp, amplitude)
                    writer.writerow(
                        [
                            f"{t:.9f}",
                            zone,
                            f"{elapsed_time_sec:.9f}",
                            f"{amplitude:.9f}",
                            flash_index,
                        ]
                    )
                    emitted += 1
                    flash_index += 1
            t += flash_period_sec

    print(f"Wrote {out_path} with {emitted} flashes.")


if __name__ == "__main__":
    main()
