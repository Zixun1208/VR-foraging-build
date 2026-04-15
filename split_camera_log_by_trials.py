#!/usr/bin/env python3
"""
Split a Unity CameraLog CSV into per-trial files using wall-clock time ranges
derived from experiment flash logs (con_led CSVs).

Camera rows are filtered by mapping Timestamp(ms) to wall seconds and comparing
to each trial's [start, end) window from the flash data.

Default sync (when timestamps are not Unix epoch ms): assumes the first data row
of the camera log and the earliest flash event across inputs occurred at the same
wall time. Override with --sync-flash-wall-sec and --sync-camera-ms if needed.

Output files use the same header and preserve each field cell exactly as read
from the camera CSV (so numeric formatting is unchanged).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TS_COL = "Timestamp(ms)"
FLASH_WALL_COL = "wall_timestamp"
FLASH_GLOBAL_COL = "global_trial_index"
FLASH_TS_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")


@dataclass(frozen=True)
class TrialWindow:
    label: str
    start_wall_sec: float
    end_wall_sec: float  # exclusive; use inf for last trial if unknown


def _read_flash_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _flash_paths_from_args(flash: list[Path], flash_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    for p in flash:
        paths.append(p.resolve())
    if flash_dir is not None:
        d = flash_dir.resolve()
        if not d.is_dir():
            raise SystemExit(f"Not a directory: {d}")
        for p in sorted(d.glob("*.csv")):
            paths.append(p.resolve())
    if not paths:
        raise SystemExit("Provide --flash and/or --flash-dir with at least one CSV.")
    # Stable sort by path; trial order fixed later via min wall time
    return paths


def _trial_label_from_flash_path(path: Path) -> str:
    stem = path.stem
    stem = FLASH_TS_SUFFIX_RE.sub("", stem)
    return stem or path.stem


def _windows_from_flash_directory(paths: list[Path]) -> list[TrialWindow]:
    spans: list[tuple[str, float, float]] = []
    for p in paths:
        rows = _read_flash_rows(p)
        if len(rows) < 2:
            continue
        hdr = [c.strip() for c in rows[0]]
        try:
            wi = hdr.index(FLASH_WALL_COL)
        except ValueError:
            raise SystemExit(
                f"{p}: missing '{FLASH_WALL_COL}' column. "
                f"Found columns: {hdr}"
            )
        times: list[float] = []
        for row in rows[1:]:
            if not row or len(row) <= wi:
                continue
            try:
                times.append(float(row[wi].strip()))
            except ValueError:
                continue
        if not times:
            continue
        label = _trial_label_from_flash_path(p)
        spans.append((label, min(times), max(times)))
    if not spans:
        raise SystemExit("No flash timestamps found in flash CSV inputs.")
    spans.sort(key=lambda t: t[1])
    windows: list[TrialWindow] = []
    for i, (label, t0, _t1) in enumerate(spans):
        if i + 1 < len(spans):
            end = spans[i + 1][1]
        else:
            end = float("inf")
        windows.append(TrialWindow(label=label, start_wall_sec=t0, end_wall_sec=end))
    return windows


def _windows_from_single_flash_table(path: Path) -> list[TrialWindow]:
    rows = _read_flash_rows(path)
    if len(rows) < 2:
        raise SystemExit(f"{path}: no data rows")
    hdr = [c.strip() for c in rows[0]]
    try:
        wi = hdr.index(FLASH_WALL_COL)
    except ValueError:
        raise SystemExit(f"{path}: missing '{FLASH_WALL_COL}' column. Found: {hdr}")

    if FLASH_GLOBAL_COL not in hdr:
        times = []
        for r in rows[1:]:
            if len(r) > wi and r[wi].strip():
                try:
                    times.append(float(r[wi].strip()))
                except ValueError:
                    continue
        if not times:
            raise SystemExit(f"{path}: no usable {FLASH_WALL_COL} values")
        t0 = min(times)
        return [
            TrialWindow(
                label=path.stem,
                start_wall_sec=t0,
                end_wall_sec=float("inf"),
            )
        ]

    gi = hdr.index(FLASH_GLOBAL_COL)
    by_g: dict[int, list[float]] = {}
    order: list[int] = []
    for row in rows[1:]:
        if len(row) <= max(wi, gi) or not row[wi].strip():
            continue
        try:
            g = int(float(row[gi].strip()))
            t = float(row[wi].strip())
        except ValueError:
            continue
        if g not in by_g:
            order.append(g)
            by_g[g] = []
        by_g[g].append(t)
    if not order:
        raise SystemExit(f"{path}: no usable rows with trial index and wall time")

    order.sort(key=lambda g: min(by_g[g]))
    windows: list[TrialWindow] = []
    for i, g in enumerate(order):
        times = by_g[g]
        start = min(times)
        if i + 1 < len(order):
            g_next = order[i + 1]
            end = min(by_g[g_next])
        else:
            end = float("inf")
        windows.append(
            TrialWindow(
                label=f"global_{g:03d}",
                start_wall_sec=start,
                end_wall_sec=end,
            )
        )
    return windows


def _detect_unix_ms(camera_ts_values: list[float]) -> bool:
    if not camera_ts_values:
        return False
    med = sorted(camera_ts_values)[len(camera_ts_values) // 2]
    return med >= 1e11


def _camera_rows(path: Path) -> tuple[list[str], list[list[str]], int]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise SystemExit(f"{path}: empty file")
    header = [c.strip() for c in rows[0]]
    try:
        ti = header.index(TS_COL)
    except ValueError:
        raise SystemExit(f"{path}: missing '{TS_COL}' column. Found: {header}")
    return header, rows[1:], ti


def _wall_sec_for_camera_ts(
    ts_ms: float,
    *,
    unix_ms: bool,
    offset_sec: float,
) -> float:
    if unix_ms:
        return ts_ms / 1000.0
    return offset_sec + ts_ms / 1000.0


def _default_offset_sec(
    first_camera_ms: float,
    earliest_flash_wall_sec: float,
    *,
    unix_ms: bool,
) -> float:
    if unix_ms:
        return 0.0
    return earliest_flash_wall_sec - first_camera_ms / 1000.0


def _earliest_flash_wall(paths: list[Path]) -> float:
    best: float | None = None
    for p in paths:
        rows = _read_flash_rows(p)
        if len(rows) < 2:
            continue
        hdr = [c.strip() for c in rows[0]]
        try:
            wi = hdr.index(FLASH_WALL_COL)
        except ValueError:
            continue
        for row in rows[1:]:
            if len(row) <= wi or not row[wi].strip():
                continue
            try:
                t = float(row[wi].strip())
            except ValueError:
                continue
            best = t if best is None else min(best, t)
    if best is None:
        raise SystemExit("Could not read any flash wall_timestamp values.")
    return best


def _sanitize_label(label: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", label.strip())
    return s.strip("_") or "trial"


def split_camera_log(
    camera_path: Path,
    flash_paths: list[Path],
    output_dir: Path,
    *,
    sync_flash_wall_sec: float | None,
    sync_camera_ms: float | None,
    force_unix_ms: bool | None,
) -> None:
    header, cam_body, ti = _camera_rows(camera_path)
    cam_ts: list[float] = []
    for row in cam_body:
        if len(row) <= ti or not row[ti].strip():
            continue
        try:
            cam_ts.append(float(row[ti].strip()))
        except ValueError:
            continue

    unix_ms = bool(force_unix_ms) if force_unix_ms is not None else _detect_unix_ms(cam_ts)

    if sync_flash_wall_sec is not None and sync_camera_ms is not None:
        offset_sec = sync_flash_wall_sec - sync_camera_ms / 1000.0
    elif unix_ms:
        offset_sec = 0.0
    else:
        first_cam_ms: float | None = None
        for row in cam_body:
            if len(row) <= ti or not row[ti].strip():
                continue
            try:
                first_cam_ms = float(row[ti].strip())
                break
            except ValueError:
                continue
        if first_cam_ms is None:
            raise SystemExit("No camera timestamps to sync.")
        earliest_flash = _earliest_flash_wall(flash_paths)
        offset_sec = _default_offset_sec(first_cam_ms, earliest_flash, unix_ms=False)

    # Build trial windows: single combined file vs many per-trial files
    if len(flash_paths) == 1:
        windows = _windows_from_single_flash_table(flash_paths[0])
    else:
        windows = _windows_from_flash_directory(flash_paths)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = camera_path.stem

    # One writer per trial; accumulate rows
    buckets: dict[str, list[list[str]]] = {w.label: [] for w in windows}

    for row in cam_body:
        if len(row) <= ti or not row[ti].strip():
            continue
        try:
            ts_ms = float(row[ti].strip())
        except ValueError:
            continue
        wall = _wall_sec_for_camera_ts(ts_ms, unix_ms=unix_ms, offset_sec=offset_sec)
        for w in windows:
            if w.start_wall_sec <= wall < w.end_wall_sec:
                buckets[w.label].append(row)
                break

    for w in windows:
        label = _sanitize_label(w.label)
        out_path = output_dir / f"{stem}__{label}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator=os.linesep)
            writer.writerow(header)
            writer.writerows(buckets[w.label])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--camera", type=Path, required=True, help="Unity CameraLog CSV path")
    p.add_argument(
        "--flash",
        type=Path,
        nargs="*",
        default=[],
        help="One or more flash CSV files (con_led output)",
    )
    p.add_argument(
        "--flash-dir",
        type=Path,
        default=None,
        help="Directory of per-trial flash CSVs (merged with --flash if both given)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for per-trial camera CSVs",
    )
    p.add_argument(
        "--sync-flash-wall-sec",
        type=float,
        default=None,
        help="Override: wall time (seconds) at sync event",
    )
    p.add_argument(
        "--sync-camera-ms",
        type=float,
        default=None,
        help="Override: camera Timestamp(ms) at the same sync event",
    )
    p.add_argument(
        "--camera-time-unix-ms",
        action="store_true",
        help="Treat Timestamp(ms) as Unix epoch milliseconds (no offset sync)",
    )
    p.add_argument(
        "--camera-time-not-unix-ms",
        action="store_true",
        help="Force relative Unity ms + anchor sync (ignore auto-detect)",
    )
    args = p.parse_args()
    if args.camera_time_unix_ms and args.camera_time_not_unix_ms:
        p.error("Choose at most one of --camera-time-unix-ms / --camera-time-not-unix-ms")
    sf, sc = args.sync_flash_wall_sec, args.sync_camera_ms
    if (sf is None) ^ (sc is None):
        p.error("Provide both --sync-flash-wall-sec and --sync-camera-ms, or neither")
    return args


def main() -> None:
    args = parse_args()
    flash_paths = _flash_paths_from_args(list(args.flash), args.flash_dir)
    force_unix: bool | None = None
    if args.camera_time_unix_ms:
        force_unix = True
    elif args.camera_time_not_unix_ms:
        force_unix = False

    split_camera_log(
        args.camera.resolve(),
        flash_paths,
        args.output_dir.resolve(),
        sync_flash_wall_sec=args.sync_flash_wall_sec,
        sync_camera_ms=args.sync_camera_ms,
        force_unix_ms=force_unix,
    )


if __name__ == "__main__":
    main()
