#!/usr/bin/env python3
"""Slice the Unity camera log.

Vendored verbatim from ``~/Analysis/slice_camera_log.py`` (stdlib-only, no local
imports) so this package runs on a machine that has no ~/Analysis tree. If you
change the slicing logic, change it there and re-copy, or the two will drift.

Slice the Unity camera log into per-iteration/per-trial CSVs using the
start timestamps encoded in the flash-event filenames.

Each flash-event file is named like:
    training_iter_{iter}_trial_{trial}_YYYYMMDD_HHMMSS_mmm.csv
    probing_iter_{iter}_trial_{trial}_YYYYMMDD_HHMMSS_mmm.csv

The trailing YYYYMMDD_HHMMSS_mmm is the trial start time in local wall clock.

The Unity camera log's first column is "Timestamp(ms)" expressed as
milliseconds since local midnight on the acquisition day (this matches the
time-of-day in the camera log's filename: CameraLog_YYYY-MM-DD_HH-MM-SS.csv).

For each flash-event trial we take:
    start_ms = ms-since-midnight derived from the flash-event filename
    end_ms   = start_ms of the next trial (or +inf for the final trial)
and write every camera-log row within [start_ms, end_ms) into
    <DATA_DIR>/training/<flash_event_filename>
or
    <DATA_DIR>/probing/<flash_event_filename>
(keeping the flash-event filename so the mapping between the two is obvious).

Midnight rollover is handled automatically: when the camera log's
ms-since-midnight column drops backwards (wraps at a day boundary), 24 h is
added to all subsequent timestamps before matching them against trial windows.
Trial windows themselves are built from full wall-clock datetimes in the
flash-event filenames, so trials starting after midnight are placed correctly
too. Rows are written with their original (wrapped) timestamps; downstream
readers unwrap the same way (see ``foraging.io.unwrap_midnight_ms``).

The script streams the camera log line-by-line to keep memory usage low for
large files.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


FNAME_RE = re.compile(
    r"^(?P<phase>training|probing)"
    r"_iter_(?P<iter>\d+)"
    r"_trial_(?P<trial>\d+)"
    r"_(?P<date>\d{8})_(?P<time>\d{6})(?:_(?P<ms>\d{3}))?\.csv$"
)

CAMERA_LOG_RE = re.compile(
    r"^CameraLog_(?P<date>\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}\.csv$"
)


@dataclass
class TrialWindow:
    phase: str
    iteration: int
    trial: int
    filename: str
    start_ms: float          # ms since local midnight of acquisition day (may exceed 24 h)
    end_ms: float            # exclusive upper bound


def parse_flash_event_filename(fname: str) -> dict | None:
    m = FNAME_RE.match(fname)
    if not m:
        return None
    ms = m.group("ms") or "000"
    dt = datetime.strptime(
        m.group("date") + m.group("time") + ms, "%Y%m%d%H%M%S%f"
    )
    return {
        "phase": m.group("phase"),
        "iter": int(m.group("iter")),
        "trial": int(m.group("trial")),
        "datetime": dt,
        "filename": fname,
    }


def collect_windows(flash_dir: Path, acquisition_date: datetime) -> list[TrialWindow]:
    events = []
    for p in sorted(flash_dir.iterdir()):
        if not p.is_file():
            continue
        info = parse_flash_event_filename(p.name)
        if info is None:
            continue
        events.append(info)

    events.sort(key=lambda e: e["datetime"])

    midnight = acquisition_date.replace(hour=0, minute=0, second=0, microsecond=0)
    windows: list[TrialWindow] = []
    for i, ev in enumerate(events):
        start_ms = (ev["datetime"] - midnight).total_seconds() * 1000.0
        if i + 1 < len(events):
            end_dt = events[i + 1]["datetime"]
            end_ms = (end_dt - midnight).total_seconds() * 1000.0
        else:
            end_ms = float("inf")
        windows.append(
            TrialWindow(
                phase=ev["phase"],
                iteration=ev["iter"],
                trial=ev["trial"],
                filename=ev["filename"],
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )

    return windows


def find_window_index(windows: list[TrialWindow], ts_ms: float) -> int:
    """Return index of window containing ts_ms, or -1 if none.

    Uses a simple linear scan from a cached index because the camera log is
    strictly increasing in time within the trial period and windows are sorted.
    """
    # Binary search: windows are sorted by start_ms, non-overlapping.
    lo, hi = 0, len(windows) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        w = windows[mid]
        if ts_ms < w.start_ms:
            hi = mid - 1
        elif ts_ms >= w.end_ms:
            lo = mid + 1
        else:
            return mid
    return -1


def slice_camera_log(
    camera_log_path: Path,
    windows: list[TrialWindow],
    training_dir: Path,
    probing_dir: Path,
    boundary_guard_ms: float = 1000.0,
    reset_from_pos: float = 100.0,
    reset_to_pos: float = 10.0,
    min_reset_drop: float = 60.0,
    verbose: bool = True,
) -> dict[str, int]:
    training_dir.mkdir(parents=True, exist_ok=True)
    probing_dir.mkdir(parents=True, exist_ok=True)

    # Pre-open a writer for each window lazily.
    writers: dict[str, csv.writer] = {}
    files: dict[str, object] = {}
    row_counts: dict[str, int] = {w.filename: 0 for w in windows}

    def writer_for(window: TrialWindow, header: list[str]) -> csv.writer:
        if window.filename in writers:
            return writers[window.filename]
        out_dir = training_dir if window.phase == "training" else probing_dir
        out_path = out_dir / window.filename
        f = open(out_path, "w", newline="")
        w = csv.writer(f)
        w.writerow(header)
        files[window.filename] = f
        writers[window.filename] = w
        return w

    ms_per_day = 24 * 60 * 60 * 1000.0

    try:
        with open(camera_log_path, "r", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            expected_cols = len(header)
            prev_ts_ms = -1.0
            day_offset_ms = 0.0
            prev_pos: float | None = None
            forced_window_idx: int | None = None
            forced_until_ms = -1.0
            raw_row_no = 1  # starts after header
            total_rows = 0
            matched_rows = 0
            early_switch_rows = 0
            malformed_rows = 0
            for row in reader:
                raw_row_no += 1
                if not row:
                    continue
                if len(row) != expected_cols:
                    malformed_rows += 1
                    if verbose and malformed_rows <= 10:
                        print(
                            f"Skipping malformed camera row {raw_row_no}: "
                            f"expected {expected_cols} fields, got {len(row)}.",
                            file=sys.stderr,
                        )
                    continue
                try:
                    raw_ts_ms = float(row[0])
                except ValueError:
                    continue
                total_rows += 1

                # Day rollover: the ms-since-midnight column drops back to
                # near 0 at each midnight. Unwrap by accumulating 24 h so
                # window matching keeps working across day boundaries.
                if prev_ts_ms >= 0 and raw_ts_ms + 1000.0 < prev_ts_ms:
                    day_offset_ms += ms_per_day
                    if verbose:
                        print(
                            f"Detected midnight rollover at row {total_rows}; "
                            f"continuing with +{day_offset_ms/ms_per_day:.0f} day offset.",
                            file=sys.stderr,
                        )
                prev_ts_ms = raw_ts_ms
                ts_ms = raw_ts_ms + day_offset_ms

                idx = find_window_index(windows, ts_ms)
                if forced_window_idx is not None and ts_ms < forced_until_ms:
                    idx = forced_window_idx
                elif forced_window_idx is not None and ts_ms >= forced_until_ms:
                    forced_window_idx = None
                    forced_until_ms = -1.0
                if idx == -1:
                    if len(row) > 1:
                        try:
                            prev_pos = float(row[1])
                        except ValueError:
                            prev_pos = None
                    continue

                # Boundary safeguard:
                # if we see a sharp position reset very close to the next trial start,
                # treat the current and subsequent pre-boundary rows as belonging to
                # the next trial instead of the current one.
                curr_pos: float | None = None
                if len(row) > 1:
                    try:
                        curr_pos = float(row[1])
                    except ValueError:
                        curr_pos = None
                if (
                    curr_pos is not None
                    and prev_pos is not None
                    and idx + 1 < len(windows)
                ):
                    next_start_ms = windows[idx + 1].start_ms
                    ms_to_next = next_start_ms - ts_ms
                    drop = prev_pos - curr_pos
                    if (
                        0.0 <= ms_to_next <= boundary_guard_ms
                        and prev_pos >= reset_from_pos
                        and curr_pos <= reset_to_pos
                        and drop >= min_reset_drop
                    ):
                        idx = idx + 1
                        forced_window_idx = idx
                        forced_until_ms = windows[idx].start_ms
                        early_switch_rows += 1

                w = windows[idx]
                wr = writer_for(w, header)
                wr.writerow(row)
                row_counts[w.filename] += 1
                matched_rows += 1
                prev_pos = curr_pos

                if verbose and total_rows % 500_000 == 0:
                    print(
                        f"  scanned {total_rows:>10,} rows, "
                        f"matched {matched_rows:>10,}",
                        file=sys.stderr,
                    )
            if verbose and early_switch_rows:
                print(
                    f"Applied early boundary-switch safeguard to {early_switch_rows} row(s).",
                    file=sys.stderr,
                )
            if verbose and malformed_rows:
                suffix = " (first 10 logged above)" if malformed_rows > 10 else ""
                print(
                    f"Skipped {malformed_rows} malformed camera-log row(s){suffix}.",
                    file=sys.stderr,
                )
    finally:
        for f in files.values():
            f.close()

    return row_counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/home/kazama/Raw_data/2026-04-17"),
        help="Root data directory (default: %(default)s).",
    )
    ap.add_argument(
        "--flash-subdir", default="flash_events", help="Flash events subdirectory."
    )
    ap.add_argument(
        "--unity-subdir", default="unity", help="Unity camera log subdirectory."
    )
    ap.add_argument(
        "--training-subdir", default="training", help="Output training subdirectory."
    )
    ap.add_argument(
        "--probing-subdir", default="probing", help="Output probing subdirectory."
    )
    ap.add_argument(
        "--camera-log",
        type=Path,
        default=None,
        help="Explicit camera log path (default: auto-detect CameraLog_*.csv).",
    )
    ap.add_argument(
        "--boundary-guard-ms",
        type=float,
        default=1000.0,
        help=(
            "If a reset-like position jump occurs within this many ms before "
            "the next trial start, rows are reassigned to the next trial."
        ),
    )
    ap.add_argument(
        "--reset-from-pos",
        type=float,
        default=100.0,
        help="Previous position must be >= this value to trigger reset safeguard.",
    )
    ap.add_argument(
        "--reset-to-pos",
        type=float,
        default=10.0,
        help="Current position must be <= this value to trigger reset safeguard.",
    )
    ap.add_argument(
        "--min-reset-drop",
        type=float,
        default=60.0,
        help="Minimum position drop needed to trigger reset safeguard.",
    )
    args = ap.parse_args()

    data_dir: Path = args.data_dir
    flash_dir = data_dir / args.flash_subdir
    unity_dir = data_dir / args.unity_subdir
    training_out = data_dir / args.training_subdir
    probing_out = data_dir / args.probing_subdir

    if args.camera_log is not None:
        camera_log = args.camera_log
    else:
        candidates = sorted(unity_dir.glob("CameraLog_*.csv"))
        if not candidates:
            print(f"No CameraLog_*.csv found in {unity_dir}", file=sys.stderr)
            return 1
        if len(candidates) > 1:
            print(
                f"Multiple camera logs found; using the first: {candidates[0].name}",
                file=sys.stderr,
            )
        camera_log = candidates[0]

    m = CAMERA_LOG_RE.match(camera_log.name)
    if m is None:
        print(
            f"Camera log filename {camera_log.name} does not match expected "
            "CameraLog_YYYY-MM-DD_HH-MM-SS.csv pattern.",
            file=sys.stderr,
        )
        return 1
    acquisition_date = datetime.strptime(m.group("date"), "%Y-%m-%d")

    print(f"Data dir         : {data_dir}")
    print(f"Flash events dir : {flash_dir}")
    print(f"Camera log       : {camera_log}")
    print(f"Acquisition day  : {acquisition_date.date()}")

    windows = collect_windows(flash_dir, acquisition_date)
    print(f"Found {len(windows)} trial windows.")
    for w in windows:
        dur = (w.end_ms - w.start_ms) / 1000.0 if w.end_ms != float("inf") else float("inf")
        print(
            f"  {w.phase:<8} iter {w.iteration} trial {w.trial}  "
            f"start={w.start_ms/1000:9.3f}s  "
            f"dur={dur:7.3f}s  -> {w.filename}"
        )

    print(f"\nSlicing camera log ({camera_log.stat().st_size/1e6:.1f} MB)...")
    counts = slice_camera_log(
        camera_log_path=camera_log,
        windows=windows,
        training_dir=training_out,
        probing_dir=probing_out,
        boundary_guard_ms=args.boundary_guard_ms,
        reset_from_pos=args.reset_from_pos,
        reset_to_pos=args.reset_to_pos,
        min_reset_drop=args.min_reset_drop,
    )

    print("\nPer-trial camera-log row counts:")
    for w in windows:
        out_dir = training_out if w.phase == "training" else probing_out
        print(
            f"  {w.phase:<8} iter {w.iteration} trial {w.trial}:  "
            f"{counts[w.filename]:>8,} rows -> {out_dir / w.filename}"
        )
    total = sum(counts.values())
    print(f"\nTotal rows written: {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
