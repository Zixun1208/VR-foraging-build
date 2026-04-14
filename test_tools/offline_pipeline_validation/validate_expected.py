#!/usr/bin/env python3
"""Validate expected flash CSV against emulated calc_path trajectory."""

import csv
from bisect import bisect_right
from math import exp, isclose, log


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
                zone_decay_constants[int(zone)] = log(max_amp / min_amp) / decay_time
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


def expected_amplitude(t: float, zone: int, zone_decay_constants: dict[int, float | None], max_amp: float, min_amp: float) -> float:
    k = zone_decay_constants[zone]
    if k is None:
        return 0.0
    if k == 0.0:
        return max_amp
    amp = max_amp * exp(-k * max(0.0, t))
    return max(min_amp, amp)


def main() -> None:
    calc_path = "calc_path_emulated.csv"
    flash_path = "expected_flash.csv"
    amp_abs_tol = 1e-6
    amp_rel_tol = 1e-6

    max_amp = 5.0
    min_amp = 0.2
    zone_decay_constants = parse_zone_decay_rates("0:20,1:100", max_amp, min_amp)

    times: list[float] = []
    zs: list[float] = []
    with open(calc_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["t_sec"]))
            zs.append(float(row["z"]))

    total = 0
    zone_pass = 0
    amp_pass = 0
    failures: list[str] = []

    with open(flash_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            t = float(row["expected_flash_time_sec"])
            zone_csv = int(row["zone"])
            amp_csv = float(row["expected_amplitude_volts"])
            flash_index = int(row["flash_index"])

            z = interpolate_z(t, times, zs)
            zone_calc = zone_for_z(z)
            if zone_calc == zone_csv:
                zone_pass += 1
            else:
                failures.append(
                    f"flash_index={flash_index} zone mismatch: expected_csv={zone_csv}, derived={zone_calc}, z={z:.6f}, t={t:.6f}"
                )

            amp_calc = expected_amplitude(t, zone_csv, zone_decay_constants, max_amp, min_amp)
            if isclose(amp_csv, amp_calc, rel_tol=amp_rel_tol, abs_tol=amp_abs_tol):
                amp_pass += 1
            else:
                failures.append(
                    f"flash_index={flash_index} amp mismatch: csv={amp_csv:.9f}, formula={amp_calc:.9f}, t={t:.6f}"
                )

    all_pass = (zone_pass == total) and (amp_pass == total)
    print("VALIDATION PASS" if all_pass else "VALIDATION FAIL")
    print(f"total_flashes={total}")
    print(f"zone_checks_passed={zone_pass}/{total}")
    print(f"amplitude_checks_passed={amp_pass}/{total}")
    print(f"failure_count={len(failures)}")
    if failures:
        print("sample_failures:")
        for msg in failures[:10]:
            print(f"- {msg}")


if __name__ == "__main__":
    main()
