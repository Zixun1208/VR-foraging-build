#!/usr/bin/env python3
"""Slice the Unity camera log into per-trial CSVs.

Vendored verbatim from ``~/Analysis/slice_camera_log.py`` (stdlib-only, no local
imports) so this package runs on a machine that has no ~/Analysis tree. If you
change the slicing logic, change it there and re-copy, or the two will drift.

Each flash-event file is named like:
    training_iter_{iter}_trial_{trial}_YYYYMMDD_HHMMSS_mmm.csv
    probing_iter_{iter}_trial_{trial}_YYYYMMDD_HHMMSS_mmm.csv
    openloop_training_iter_{iter}_YYYYMMDD_HHMMSS_mmm.csv   (no _trial_ suffix)
    baseline_iter_{iter}_YYYYMMDD_HHMMSS_mmm.csv            (no _trial_ suffix)

A trial boundary is NOT taken from that filename's timestamp. Earlier versions
of this script did exactly that -- windowing the camera log by
[flash_event_time, next_flash_event_time) -- and it produced trial files that
sometimes started with a hundred-plus leftover rows from the *previous* trial
(corridor position ~100-130) before dropping to ~0 partway through the file.

The cause is structural, not a tuning problem: ``trial_coordinator.py`` stamps
a new trial's start time the instant it receives the ``teleport_boundary`` UDP
event from ``calc_path.py`` -- which fires *before* ``calc_path.py`` sends the
corrected (wrapped) position to Unity for logging. In production data that
declared timestamp has been observed up to ~89 seconds earlier than the actual
position reset visible in the camera log, so the old windowing scheme would
start a trial's window while the log was still recording the tail end of the
fly finishing the previous one.

The fix: find the teleport directly in the camera log's own position column --
a sharp drop from near the corridor's far end to near its start is a teleport,
full stop, independent of any other process's clock. Flash-event files are
still needed, but only to give each teleport-bounded row range an identity
(phase/iteration/trial/output filename), matched by ORDER rather than by
timestamp proximity: every trial phase (openloop_training, baseline,
initial_training, training, probing) gets exactly one flash-event file and
exactly one teleport, in the same sequence, so the k-th detected teleport
corresponds to the k-th flash-event file. Only training/probing windows are
written out; the rest exist purely to keep that ordinal alignment correct.

Midnight rollover needs no handling here at all: since cutting is done by row
index rather than by comparing timestamps across the log and the flash-event
filenames, there is no cross-source time arithmetic to get wrong. Row
timestamps are still written out unmodified.

The script streams the camera log twice (once to detect teleports, once to
write trial files) to keep memory usage low for large files.
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
    r"^(?P<phase>.+?)"
    r"_iter_(?P<iter>\d+)"
    r"(?:_trial_(?P<trial>\d+))?"
    r"_(?P<date>\d{8})_(?P<time>\d{6})(?:_(?P<ms>\d{3}))?\.csv$"
)

CAMERA_LOG_RE = re.compile(
    r"^CameraLog_(?P<date>\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}\.csv$"
)

# Phases written out as trial CSVs by default, one subdirectory each.
# "initial_training" is deliberately excluded (see collect_flash_events):
# it's con_led.py's own startup filename for the same first trial another
# event already describes, not a distinct trial. A phase can still be
# ordinally aligned against detected teleports without being written out --
# slice_camera_log only writes whatever phases are keys in its `out_dirs`.
SLICED_PHASES = ("training", "probing", "openloop_training", "baseline")


@dataclass
class FlashEvent:
    phase: str
    iteration: int
    trial: int | None
    filename: str
    approx_dt: datetime  # from the filename -- identity only, never a cut point


@dataclass
class TrialWindow:
    phase: str
    iteration: int
    trial: int | None
    filename: str
    start_row: int         # inclusive, 0-based index among camera-log data rows
    end_row: int | None    # exclusive; None means "through end of file"


def parse_flash_event_filename(fname: str) -> FlashEvent | None:
    m = FNAME_RE.match(fname)
    if not m:
        return None
    ms = m.group("ms") or "000"
    dt = datetime.strptime(
        m.group("date") + m.group("time") + ms, "%Y%m%d%H%M%S%f"
    )
    trial = m.group("trial")
    return FlashEvent(
        phase=m.group("phase"),
        iteration=int(m.group("iter")),
        trial=int(trial) if trial is not None else None,
        filename=fname,
        approx_dt=dt,
    )


def collect_flash_events(flash_dir: Path) -> list[FlashEvent]:
    """Every flash-event file for this acquisition, of any phase, in
    chronological order by the (approximate) start time in its filename.

    Every phase is included here even though only training/probing get
    written out later: each one still corresponds to exactly one teleport, so
    dropping them here would desynchronize the ordinal pairing against the
    teleports ``detect_teleport_rows`` finds in the camera log.
    """
    events = []
    for p in sorted(flash_dir.iterdir()):
        if not p.is_file():
            continue
        ev = parse_flash_event_filename(p.name)
        if ev is not None:
            events.append(ev)
    events.sort(key=lambda e: e.approx_dt)
    return events


def _camera_log_header(camera_log_path: Path) -> list[str]:
    with open(camera_log_path, newline="") as fh:
        return next(csv.reader(fh))


def _iter_camera_rows(camera_log_path: Path):
    """Yield ``(row_index, row, pos)`` for every data row (header excluded),
    0-based. ``pos`` is ``None`` for a malformed or unparseable row -- but the
    row still gets an index, so numbering stays identical across every pass
    over this file, which is what lets the detection pass and the write pass
    agree on exactly where a trial starts and ends.
    """
    with open(camera_log_path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        expected_cols = len(header)
        row_index = -1
        for row in reader:
            if not row:
                continue
            row_index += 1
            pos = None
            if len(row) == expected_cols and len(row) > 1:
                try:
                    pos = float(row[1])
                except ValueError:
                    pos = None
            yield row_index, row, pos


def detect_teleport_rows(
    camera_log_path: Path,
    reset_from_pos: float = 90.0,
    reset_to_pos: float = 25.0,
    min_reset_drop: float = 50.0,
) -> list[int]:
    """Row indices where the corridor position physically resets (a teleport).

    Found directly in the camera log's own position column -- the one signal
    immune to clock skew between calc_path/trial_coordinator/Unity, because it
    doesn't involve comparing timestamps from different processes at all.

    A teleport is a position drop, between one row and the very next, from
    >= ``reset_from_pos`` to <= ``reset_to_pos``, of at least
    ``min_reset_drop``. Real fly motion can't produce this: it would require
    walking backward across most of the corridor between two consecutive
    samples. Thresholds default to values with real headroom around observed
    production data (resets have landed as high as position ~11.5 and as low
    as ~0.1 after the drop; corridor far-end approach starts around ~100+).
    """
    resets = []
    prev_pos = None
    for row_index, _row, pos in _iter_camera_rows(camera_log_path):
        if pos is None:
            continue
        if (
            prev_pos is not None
            and prev_pos >= reset_from_pos
            and pos <= reset_to_pos
            and (prev_pos - pos) >= min_reset_drop
        ):
            resets.append(row_index)
        prev_pos = pos
    return resets


def build_windows(
    events: list[FlashEvent], teleport_rows: list[int], verbose: bool = True
) -> list[TrialWindow]:
    """Pair each flash event with a teleport-bounded row range, by ORDER.

    Never by matching timestamps across processes -- that's what produced the
    leading-leftover-rows bug in the first place. The first event starts at
    row 0 (the fly is already at ``trial_start_z`` from process startup);
    event i>0 starts at the (i-1)-th detected teleport; each ends at the next
    teleport, or at end of file for the very last event.
    """
    n_expected = len(events) - 1
    if len(teleport_rows) != n_expected and verbose:
        print(
            f"[warn] {len(events)} flash events but {len(teleport_rows)} "
            f"teleport(s) detected in the camera log (expected {n_expected}). "
            "Likely a dropped UDP boundary event or a session that ended "
            "mid-trial -- trial boundaries past the mismatch may be wrong; "
            "check the affected trial(s) by hand.",
            file=sys.stderr,
        )

    windows = []
    prev_end = 0
    for i, ev in enumerate(events):
        is_last = i == len(events) - 1
        start_row = 0 if i == 0 else (teleport_rows[i - 1] if i - 1 < len(teleport_rows) else prev_end)
        end_row = teleport_rows[i] if (not is_last and i < len(teleport_rows)) else None
        windows.append(
            TrialWindow(ev.phase, ev.iteration, ev.trial, ev.filename, start_row, end_row)
        )
        prev_end = end_row if end_row is not None else start_row
    return windows


def collect_windows(flash_dir: Path, camera_log_path: Path, verbose: bool = True) -> list[TrialWindow]:
    """Convenience wrapper: flash events + detected teleports -> windows."""
    events = collect_flash_events(flash_dir)
    teleport_rows = detect_teleport_rows(camera_log_path)
    return build_windows(events, teleport_rows, verbose=verbose)


def slice_camera_log(
    camera_log_path: Path,
    windows: list[TrialWindow],
    out_dirs: dict[str, Path],
    verbose: bool = True,
) -> dict[str, int]:
    """Write each window to ``out_dirs[window.phase]``.

    A phase with no entry in ``out_dirs`` is skipped entirely -- it still
    contributed to the ordinal alignment in ``build_windows``, it just isn't
    persisted. This is what lets a caller choose which phases to keep (e.g.
    training/probing/openloop_training/baseline, but never initial_training)
    without slicer.py hard-coding that choice itself.
    """
    for d in out_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    to_write = [w for w in windows if w.phase in out_dirs]
    row_counts: dict[str, int] = {w.filename: 0 for w in to_write}
    if not to_write:
        return row_counts

    header = _camera_log_header(camera_log_path)

    writers: dict[str, csv.writer] = {}
    files: dict[str, object] = {}

    def writer_for(window: TrialWindow) -> csv.writer:
        if window.filename in writers:
            return writers[window.filename]
        out_dir = out_dirs[window.phase]
        f = open(out_dir / window.filename, "w", newline="")
        w = csv.writer(f)
        w.writerow(header)
        files[window.filename] = f
        writers[window.filename] = w
        return w

    idx = 0
    matched_rows = 0
    total_rows = 0
    try:
        for row_index, row, _pos in _iter_camera_rows(camera_log_path):
            total_rows += 1
            while (
                idx < len(to_write)
                and to_write[idx].end_row is not None
                and row_index >= to_write[idx].end_row
            ):
                idx += 1
            if idx >= len(to_write):
                break
            w = to_write[idx]
            if row_index < w.start_row:
                continue
            writer_for(w).writerow(row)
            row_counts[w.filename] += 1
            matched_rows += 1
            if verbose and total_rows % 500_000 == 0:
                print(
                    f"  scanned {total_rows:>10,} rows, matched {matched_rows:>10,}",
                    file=sys.stderr,
                )
    finally:
        for f in files.values():
            f.close()

    return row_counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/home/kazama/Raw_data/2026-04-17"),
        help="Root data directory (default: %(default)s).",
    )
    ap.add_argument("--flash-subdir", default="flash_events")
    ap.add_argument("--unity-subdir", default="unity")
    ap.add_argument("--training-subdir", default="training")
    ap.add_argument("--probing-subdir", default="probing")
    ap.add_argument("--openloop-subdir", default="openloop_training")
    ap.add_argument("--baseline-subdir", default="baseline")
    ap.add_argument("--camera-log", type=Path, default=None,
                    help="Explicit camera log path (default: auto-detect CameraLog_*.csv).")
    ap.add_argument("--reset-from-pos", type=float, default=90.0,
                    help="Previous position must be >= this to count as a teleport (default: %(default)s).")
    ap.add_argument("--reset-to-pos", type=float, default=25.0,
                    help="Position right after the drop must be <= this (default: %(default)s).")
    ap.add_argument("--min-reset-drop", type=float, default=50.0,
                    help="Minimum position drop, row to row, to count as a teleport (default: %(default)s).")
    args = ap.parse_args()

    data_dir: Path = args.data_dir
    flash_dir = data_dir / args.flash_subdir
    unity_dir = data_dir / args.unity_subdir
    out_dirs = {
        "training": data_dir / args.training_subdir,
        "probing": data_dir / args.probing_subdir,
        "openloop_training": data_dir / args.openloop_subdir,
        "baseline": data_dir / args.baseline_subdir,
    }

    if args.camera_log is not None:
        camera_log = args.camera_log
    else:
        candidates = sorted(unity_dir.glob("CameraLog_*.csv"))
        if not candidates:
            print(f"No CameraLog_*.csv found in {unity_dir}", file=sys.stderr)
            return 1
        if len(candidates) > 1:
            print(f"Multiple camera logs found; using the first: {candidates[0].name}", file=sys.stderr)
        camera_log = candidates[0]

    print(f"Data dir         : {data_dir}")
    print(f"Flash events dir : {flash_dir}")
    print(f"Camera log       : {camera_log}")

    events = collect_flash_events(flash_dir)
    print(f"Found {len(events)} flash event(s) (all phases).")

    print("Scanning camera log for teleports...")
    teleport_rows = detect_teleport_rows(
        camera_log, args.reset_from_pos, args.reset_to_pos, args.min_reset_drop
    )
    print(f"Detected {len(teleport_rows)} teleport(s); expected {len(events) - 1}.")

    windows = build_windows(events, teleport_rows)
    for w in windows:
        end = w.end_row if w.end_row is not None else "EOF"
        print(f"  {w.phase:<18} iter {w.iteration} trial {w.trial}  rows [{w.start_row}, {end})  -> {w.filename}")

    print(f"\nSlicing camera log ({camera_log.stat().st_size / 1e6:.1f} MB)...")
    counts = slice_camera_log(camera_log_path=camera_log, windows=windows, out_dirs=out_dirs)

    print("\nPer-trial camera-log row counts:")
    for w in windows:
        if w.phase not in out_dirs:
            continue
        print(f"  {w.phase:<18} iter {w.iteration} trial {w.trial}:  "
              f"{counts[w.filename]:>8,} rows -> {out_dirs[w.phase] / w.filename}")
    print(f"\nTotal rows written: {sum(counts.values()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
