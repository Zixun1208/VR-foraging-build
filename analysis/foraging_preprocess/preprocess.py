#!/usr/bin/env python3
"""Entry point. Run it directly from wherever this directory happens to live:

    python preprocess.py --acquisition 20260810_153938

or, for a whole day at once:

    python preprocess.py --batch --date 2026-09-11

Needs only Python >=3.9, numpy and matplotlib (plus pandas, optionally, to build
the FicTrac turn cache). Nothing else in this directory imports anything outside
it, so copying the directory to another machine is the whole install.
"""
from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import os
import shutil
import sys
from datetime import datetime

import config as cfgmod
import expconfig
from config import Geometry, Roots, Thresholds
from ingest import ingest
from qc import apply_rules, print_table, qc_trials, trailing_dropoff, write_recommendation
from tasks import infer_task  # used only to cross-check the config against the data

VERSION = "0.1.0"
STEPS = ("ingest", "qc", "recommend", "figures")
ACQ_ID_FMT = "%Y%m%d_%H%M%S"


# ---------------------------------------------------------------------------
# --batch: discover a whole day's acquisitions, archive the short ones, and
# run the single-acquisition pipeline below over the rest as sub-1, sub-2, ...
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Acquisition:
    acq_id: str
    path: str
    start: datetime
    n_trial_files: int
    duration_sec: float
    has_unity: bool


def discover_acquisitions(acq_root: str, date: str) -> list[Acquisition]:
    """Every acquisition folder under ``acq_root`` that started on ``date``."""
    compact = date.replace("-", "")
    out = []
    for path in sorted(glob.glob(os.path.join(acq_root, f"{compact}_*"))):
        acq_id = os.path.basename(path)
        try:
            start = datetime.strptime(acq_id, ACQ_ID_FMT)
        except ValueError:
            print(f"  [skip] {acq_id}: not an acquisition folder (name doesn't "
                  "look like YYYYMMDD_HHMMSS)")
            continue
        out.append(_probe_acquisition(acq_id, path, start))
    return out


def _probe_acquisition(acq_id: str, path: str, start: datetime) -> Acquisition:
    """Cheap triage without a full ingest: file counts and mtimes only.

    Duration is approximated as the latest file mtime in the acquisition minus
    the start time encoded in its own folder name -- good enough to catch a
    run that was aborted seconds after it began, which is the failure mode
    this is triaging for.
    """
    flash_dir = os.path.join(path, "flash_events")
    trial_files = glob.glob(os.path.join(flash_dir, "*.csv"))
    unity_dir = os.path.join(path, "unity")
    unity_files = glob.glob(os.path.join(unity_dir, "*.csv"))
    mtimes = [os.path.getmtime(p) for p in (*trial_files, *unity_files)]
    duration = (max(mtimes) - start.timestamp()) if mtimes else 0.0
    return Acquisition(acq_id=acq_id, path=path, start=start,
                       n_trial_files=len(trial_files),
                       duration_sec=max(duration, 0.0),
                       has_unity=os.path.isdir(unity_dir))


def _flag_reason(acq: Acquisition, min_trial_files: int,
                 min_duration_sec: float) -> str | None:
    if not acq.has_unity:
        return "no unity/ camera log"
    if acq.n_trial_files < min_trial_files:
        return f"only {acq.n_trial_files} flash-event file(s) (< {min_trial_files})"
    if acq.duration_sec < min_duration_sec:
        return f"lasted {acq.duration_sec:.0f}s (< {min_duration_sec:.0f}s)"
    return None


def _print_acquisition_table(acqs: list[Acquisition], reasons: dict) -> None:
    print(f"\n  {'#':>3} {'acquisition':<16} {'started':<9} {'trials':>6} "
          f"{'dur(s)':>7}  status")
    for i, a in enumerate(acqs):
        reason = reasons[a.acq_id]
        status = f"flagged: {reason}" if reason else "looks fine"
        print(f"  {i:>3} {a.acq_id:<16} {a.start.strftime('%H:%M:%S'):<9} "
              f"{a.n_trial_files:>6} {a.duration_sec:>7.0f}  {status}")


def _parse_row_numbers(text: str, n: int) -> set[int]:
    out = set()
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit() or not (0 <= int(chunk) < n):
            raise SystemExit(f"'{chunk}' is not a valid row number (0-{n - 1})")
        out.add(int(chunk))
    return out


def choose_archive_set(acqs: list[Acquisition], min_trial_files: int,
                       min_duration_sec: float, assume_yes: bool) -> set[str]:
    """Interactively settle which acquisitions get archived before processing."""
    reasons = {a.acq_id: _flag_reason(a, min_trial_files, min_duration_sec)
              for a in acqs}
    _print_acquisition_table(acqs, reasons)
    flagged = {a.acq_id for a in acqs if reasons[a.acq_id]}

    if flagged and not assume_yes:
        print(f"\n{len(flagged)} run(s) above look too short to be a real session.")
        resp = input("Archive them before preprocessing the rest? [Y/n] ").strip().lower()
        if resp.startswith("n"):
            flagged = set()
    elif flagged:
        print(f"\n[--yes] archiving {len(flagged)} flagged run(s) automatically")

    if not assume_yes:
        resp = input("\nAny other runs to archive? Row numbers, comma-separated, "
                     "or blank for none: ").strip()
        if resp:
            flagged |= {acqs[i].acq_id for i in _parse_row_numbers(resp, len(acqs))}

    return flagged


def archive_acquisitions(acqs: list[Acquisition], archive_ids: set,
                         archive_dir: str, dry_run: bool) -> list[Acquisition]:
    kept = []
    for a in acqs:
        if a.acq_id not in archive_ids:
            kept.append(a)
            continue
        dest = os.path.join(archive_dir, a.acq_id)
        print(f"  [archive] {a.acq_id} -> {dest}")
        if not dry_run:
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(a.path, dest)
    return kept


def _manifest_path(raw_root: str, date: str) -> str:
    return os.path.join(raw_root, date, ".run_day_manifest.json")


def _load_manifest(raw_root: str, date: str) -> dict:
    path = _manifest_path(raw_root, date)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save_manifest(raw_root: str, date: str, manifest: dict) -> None:
    path = _manifest_path(raw_root, date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def assign_subs(acq_ids: list[str], raw_root: str, date: str,
                start_sub: int) -> dict:
    """acq_id -> 'sub-N', stable across re-runs and across single vs. --batch use.

    A sub number, once assigned, is never reused -- even for an acquisition
    later archived by hand -- so a re-run cannot silently point an existing
    ``sub-N`` directory at a different acquisition's data. ``acq_ids`` should
    be in chronological (start-time) order; anything already in the manifest
    keeps its existing number regardless of where it falls in the list.
    """
    manifest = _load_manifest(raw_root, date)
    used = {int(v["sub"].split("-")[1]) for v in manifest.values()}
    next_n = max(used, default=start_sub - 1) + 1

    for acq_id in acq_ids:
        if acq_id not in manifest:
            manifest[acq_id] = {"sub": f"sub-{next_n}"}
            next_n += 1

    _save_manifest(raw_root, date, manifest)
    return {acq_id: manifest[acq_id]["sub"] for acq_id in acq_ids}


def run_batch_day(args, roots: Roots) -> int:
    archive_dir = (os.path.abspath(os.path.expanduser(args.archive_dir))
                  if args.archive_dir else os.path.join(roots.acq_root, "_archived"))

    print(f"[scan] {roots.acq_root} for {args.date}")
    acqs = discover_acquisitions(roots.acq_root, args.date)
    if not acqs:
        print(f"no acquisitions found for {args.date}")
        return 1

    to_archive = choose_archive_set(acqs, args.min_session_trial_files,
                                    args.min_session_duration_sec, args.yes)
    kept = archive_acquisitions(acqs, to_archive, archive_dir, args.dry_run)
    if not kept:
        print("\nnothing left to preprocess.")
        return 0

    if args.dry_run:
        manifest = _load_manifest(roots.raw_root, args.date)
        used = {int(v["sub"].split("-")[1]) for v in manifest.values()}
        next_n = max(used, default=args.start_sub - 1) + 1
        print("\n[dry-run] would preprocess, in order:")
        for a in kept:
            sub = manifest.get(a.acq_id, {}).get("sub")
            if sub is None:
                sub = f"sub-{next_n}"
                next_n += 1
            print(f"  {a.acq_id} -> {sub}")
        return 0

    subs = assign_subs([a.acq_id for a in kept], roots.raw_root, args.date,
                       args.start_sub)

    failures = []
    for a in kept:
        sub = subs[a.acq_id]
        print(f"\n{'=' * 70}\n[{sub}] {a.acq_id}\n{'=' * 70}")
        one = argparse.Namespace(**vars(args))
        one.acquisition, one.sub, one.date = a.acq_id, sub, args.date
        try:
            process_one(one, roots)
        except SystemExit as e:
            print(f"[error] {a.acq_id} ({sub}): {e}")
            failures.append((a.acq_id, sub))

    print(f"\n{'=' * 70}")
    print(f"done: {len(kept) - len(failures)}/{len(kept)} succeeded")
    if failures:
        print("failed: " + ", ".join(f"{acq_id} ({sub})" for acq_id, sub in failures))
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# One acquisition, start to finish.
# ---------------------------------------------------------------------------

def process_one(args, roots: Roots) -> int:
    th = Thresholds(**{
        f.name: (getattr(args, f.name) == "yes" if isinstance(f.default, bool)
                 else getattr(args, f.name))
        for f in dataclasses.fields(Thresholds)})
    steps = {s.strip() for s in args.steps.split(",") if s.strip()}
    unknown = steps - set(STEPS)
    if unknown:
        raise SystemExit(f"unknown step(s): {', '.join(sorted(unknown))}; "
                         f"choose from {', '.join(STEPS)}")
    atr = {"yes": True, "no": False, "unknown": None}[args.atr]

    def _band(text, flag):
        try:
            lo, hi = (float(v) for v in text.split("-"))
        except ValueError:
            raise SystemExit(f"{flag} must look like LO-HI, e.g. 20-40 (got {text!r})")
        if hi <= lo:
            raise SystemExit(f"{flag}: HI must exceed LO (got {text!r})")
        return (lo, hi)

    patch1 = _band(args.patch1, "--patch1")
    patch2 = _band(args.patch2, "--patch2")

    date = args.date
    if date is None and args.acquisition:
        date = datetime.strptime(args.acquisition, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d")
    if date is None:
        raise SystemExit("need --date or --acquisition")

    # --sub is optional: an acquisition gets its number from the same
    # per-date manifest --batch uses, so repeated plain
    # `--acquisition xxx` calls land on sub-1, sub-2, ... instead of all
    # overwriting sub-1. Re-running the same acquisition returns its
    # existing number rather than minting a new one. An explicit --sub
    # always wins and never touches the manifest.
    if args.sub is None:
        if args.acquisition:
            args.sub = assign_subs([args.acquisition], roots.raw_root, date,
                                   args.start_sub)[args.acquisition]
            print(f"[sub] {args.acquisition} -> {args.sub} "
                  f"(auto-assigned; pass --sub to pick one yourself)")
        else:
            args.sub = "sub-1"

    # --- the task ---------------------------------------------------------
    # Order of authority: what you said, then what the session already is, then
    # the rig's config. The middle case matters: experiment_config.json describes
    # the build as it is now, so re-processing an old session against it would
    # rename that session to whatever the rig does today.
    exp_cfg = None
    task = args.task
    task_details = None

    if task is None and not args.acquisition:
        existing = sorted(glob.glob(os.path.join(roots.raw_root, date, "*", args.sub)))
        if existing:
            task = os.path.basename(os.path.dirname(existing[0]))
            print(f"[task] from the existing session directory: {task}")

    if task is None:
        exp_cfg = expconfig.load(args.experiment_config)
        task, task_details = expconfig.task_from_config(exp_cfg, atr, patch1, patch2)
        print(f"[task] from {task_details['config_path']}")
        print(f"       {task}")
        print(f"       zone0 {task_details['zone0']['max_v']}->"
              f"{task_details['zone0']['min_v']} V over "
              f"{task_details['zone0']['decay_s']}s | "
              f"zone1 {task_details['zone1']['max_v']}->"
              f"{task_details['zone1']['min_v']} V over "
              f"{task_details['zone1']['decay_s']}s | "
              f"corridor {task_details['corridor']}")
        if atr is None:
            print("       [warn] --atr unknown, so the name carries no _non-atr "
                  "suffix. If this was a control, the task name is wrong.")
        cfgmod.GEOM = Geometry(corridor=float(task_details["corridor"]),
                               patch1=patch1, patch2=patch2)
    else:
        cfgmod.GEOM = Geometry(patch1=patch1, patch2=patch2)

    if task is not None:
        # An explicit --task is used verbatim, so it must agree with --atr.
        # Filing a control under the ATR task name is unrecoverable later:
        # nothing in the raw files records which arm a fly belonged to.
        says_non_atr = task.endswith("_non-atr") or task.endswith("_non_atr")
        if atr is False and not says_non_atr:
            raise SystemExit(
                f"--atr no, but --task {task} has no _non-atr suffix.\n"
                "An explicit --task is used as given, so this would file a control "
                f"under the reward-active task.\nUse --task {task}_non-atr, or drop "
                "--task and let the LED logs name it.")
        if atr is True and says_non_atr:
            raise SystemExit(
                f"--atr yes, but --task {task} is a non-ATR task name.\n"
                "Pass --atr no, or use the task name without the suffix.")
    if task is None:
        if args.acquisition:
            flash_dir = os.path.join(roots.acq_root, args.acquisition, "flash_events")
        else:
            found = glob.glob(os.path.join(roots.raw_root, date, "*", args.sub,
                                           "flash_events"))
            flash_dir = found[0] if found else None
        if not (flash_dir and os.path.isdir(flash_dir)):
            raise SystemExit(
                "cannot infer the task: no flash_events found.\n"
                f"roots in use:\n{roots.describe()}\n"
                "Pass --task, or point --raw-root / --acq-root at this machine's layout.")
        task, evidence = infer_task(flash_dir, atr)
        print(f"[task] inferred from the LED logs: {task}")
        print(f"       {evidence}")
        if task is None:
            starts = {k: v for k, v in evidence.items() if k.endswith("_start_v")}
            raise SystemExit(
                "could not infer the task: the LED never reached its 0.1 V floor in "
                "any trial, so the decay duration is not in the data (the fly always "
                "left early).\n"
                f"The start voltages are recoverable: {starts}\n"
                "Supply the decay durations from your protocol and pass the name, e.g.\n"
                "  --task foraging_non-iti_130_20-40_100-120_"
                "1.0v-0.1v_2.5v-0.1v_50_50"
                + ("_non-atr" if atr is False else "") + "\n"
                "Format: foraging_non-iti_<corridor>_<p1lo>-<p1hi>_<p2lo>-<p2hi>"
                "_<v1>v-0.1v_<v2>v-0.1v_<decay1_s>_<decay2_s>[_non-atr]")
        if atr is None:
            print("       [warn] --atr unknown, so the name carries no _non-atr "
                  "suffix. If this was a control, the task name is wrong.")

    session_dir = os.path.join(roots.raw_root, date, task, args.sub)

    if "ingest" in steps:
        if not args.acquisition:
            raise SystemExit("--acquisition is required for the ingest step")
        session_dir = ingest(args.acquisition, task, date, args.sub, roots,
                             skip_fictrac=args.skip_fictrac)

    if not os.path.isdir(session_dir):
        raise SystemExit(f"no session at {session_dir}\nroots in use:\n{roots.describe()}")

    # The config describes the build as it is now; the flash logs describe what this
    # session actually did. Disagreement means the config moved on -- say so loudly
    # rather than filing the session under a name its own data contradicts.
    if task_details is not None:
        flash_dir = os.path.join(session_dir, "flash_events")
        if os.path.isdir(flash_dir):
            _, evidence = infer_task(flash_dir, atr)
            for problem in expconfig.cross_check(task_details, evidence):
                print(f"[warn] config vs recorded data: {problem}")

    if exp_cfg is not None:
        want = expconfig.expected_trial_counts(exp_cfg)
        for phase in ("training", "probing", "openloop_training", "baseline"):
            have = len(glob.glob(os.path.join(session_dir, phase, "*.csv")))
            if want[phase] and have != want[phase]:
                print(f"[warn] {phase}: {have} trials on disk, config expects "
                      f"{want[phase]} — the session was cut short or restarted")

    rows = []
    if steps & {"qc", "recommend", "figures"}:
        rows = qc_trials(session_dir, th)
        if not rows:
            raise SystemExit(f"no trials found under {session_dir}")
        apply_rules(rows, th)
        print(f"\n[qc] {session_dir}")
        print_table(rows)
        for phase in ("training", "probing"):
            cut = trailing_dropoff(rows, phase)
            if cut is not None:
                print(f"\n  [hint] {phase}: every trial from index {cut} on was "
                      "rejected — the fly probably stopped there.")

    if "recommend" in steps:
        write_recommendation(session_dir, date, task, args.sub, rows, th, atr,
                             roots.raw_root, apply=args.apply)

    if "figures" in steps:
        from plots import make_figures
        out_dir = args.out_dir or os.path.join(session_dir, "qc")
        print(f"\n[figures] -> {out_dir}")
        make_figures(session_dir, out_dir, f"{date} {args.sub}", rows,
                     kept_only=not args.figures_all_trials,
                     backend=args.plots, analysis_root=roots.analysis_root)

    print("\ndone.")
    return 0


def _add_threshold_args(ap):
    for f in dataclasses.fields(Thresholds):
        flag = "--" + f.name.replace("_", "-")
        if f.type is bool or isinstance(f.default, bool):
            ap.add_argument(flag, choices=("yes", "no"),
                            default="yes" if f.default else "no")
        else:
            ap.add_argument(flag, type=float, default=f.default)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="preprocess.py",
        description="Take one fly-foraging session off the rig, format it, QC it, "
                    "and recommend which trials to keep.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  # a session that just finished, ATR-fed (the default)
  python preprocess.py --acquisition 20260810_153938

  # a non-ATR control
  python preprocess.py --acquisition 20260810_153938 --atr no

  # re-check an already-formatted session, no re-ingest
  python preprocess.py --date 2026-07-23 --sub sub-1 --steps qc,recommend,figures

  # accept the recommendation (backs up any existing selection first)
  python preprocess.py --date 2026-08-10 --steps recommend --apply

  # a whole day at once: discover every acquisition, archive the ones that
  # look too short, preprocess the rest as sub-1, sub-2, ... in start order
  python preprocess.py --batch --date 2026-09-11

  # a machine with a different layout
  python preprocess.py --acquisition 20260810_153938 \\
      --raw-root /data/Raw_data --fictrac-root /data/fictrac/foraging
""")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    ap.add_argument("--acquisition",
                    help="acquisition id under the acquisition root, "
                         "e.g. 20260810_153938 (required for the ingest step)")
    ap.add_argument("--date", help="session date YYYY-MM-DD (default: from --acquisition)")
    ap.add_argument("--sub",
                    help="subject label, e.g. sub-2. Default: auto-assigned from "
                         "the per-date manifest when --acquisition is given "
                         "(so repeated calls land on sub-1, sub-2, ... instead of "
                         "each overwriting sub-1); plain 'sub-1' otherwise.")
    ap.add_argument("--task",
                    help="task folder name. Default: read from the rig's "
                         "experiment_config.json; for a session that is already "
                         "formatted, taken from its own directory name.")
    ap.add_argument("--experiment-config",
                    help="the rig's experiment_config.json — the authority on the "
                         f"task (default: {expconfig.DEFAULT_CONFIG}, or "
                         f"${expconfig.ENV_VAR})")
    ap.add_argument("--patch1", default="20-40",
                    help="patch 1 band as LO-HI. Not in experiment_config.json — it "
                         "is in the Unity scene (default: %(default)s)")
    ap.add_argument("--patch2", default="100-120",
                    help="patch 2 band as LO-HI (default: %(default)s)")
    ap.add_argument("--atr", choices=("yes", "no", "unknown"), default="yes",
                    help="whether this fly was fed all-trans-retinal. Not recorded in "
                         "any file, so it has to be stated; it is written into the "
                         "recommendation with its provenance. 'no' adds the _non-atr "
                         "suffix to the inferred task name. (default: %(default)s)")
    ap.add_argument("--steps", default=",".join(STEPS),
                    help=f"comma-separated subset of {','.join(STEPS)} "
                         "(default: all of them)")
    ap.add_argument("--apply", action="store_true",
                    help="also write the recommendation to the live session_selection "
                         "json, backing up any existing one")
    ap.add_argument("--figures-all-trials", action="store_true",
                    help="plot every trial, not just the recommended ones")
    ap.add_argument("--plots", choices=("builtin", "analysis"), default="builtin",
                    help="'analysis' reuses ~/Analysis/foraging so figures match the "
                         "notebook; needs that package present (default: %(default)s)")
    ap.add_argument("--out-dir", help="where figures go (default: <session>/qc/)")
    ap.add_argument("--skip-fictrac", action="store_true",
                    help="do not copy the FicTrac recording (it is often several GB)")

    g = ap.add_argument_group(
        "filesystem roots",
        "Each also reads an environment variable (FORAGING_RAW_ROOT, "
        "FORAGING_ACQ_ROOT, FORAGING_FICTRAC_ROOT, FORAGING_EXPLOG_ROOT, "
        "FORAGING_ANALYSIS_ROOT), so a machine can be configured once in a shell "
        "profile instead of on every command.")
    for name, help_text in (
            ("raw-root", "formatted sessions: <root>/<date>/<task>/<sub>/"),
            ("acq-root", "acquisition folders written by the rig"),
            ("fictrac-root", "FicTrac run directories"),
            ("explog-root", "experiment logs"),
            ("analysis-root", "the ~/Analysis tree, only needed for --plots analysis")):
        g.add_argument(f"--{name}", help=help_text)

    _add_threshold_args(ap.add_argument_group(
        "QC thresholds",
        "Recorded in the recommendation, so a selection can always be traced "
        "back to the rule that produced it."))

    b = ap.add_argument_group(
        "batch (whole day)",
        "With --batch, --date names a day rather than one session: every "
        "acquisition that started on it is discovered, the short ones are "
        "offered up for archiving, and the rest are preprocessed as sub-1, "
        "sub-2, ... in start order. --acquisition and --sub are ignored.")
    b.add_argument("--batch", action="store_true",
                   help="preprocess a whole day instead of one acquisition")
    b.add_argument("--min-session-trial-files", type=int, default=1,
                   help="flag an acquisition with fewer flash-event files than "
                        "this (default: %(default)s)")
    b.add_argument("--min-session-duration-sec", type=float, default=30.0,
                   help="flag an acquisition that lasted less than this "
                        "(default: %(default)s)")
    b.add_argument("--archive-dir", help="where archived acquisitions go "
                   "(default: <acq-root>/_archived)")
    b.add_argument("--start-sub", type=int, default=1,
                   help="first sub number to use when nothing for this date "
                        "has been processed yet (default: %(default)s)")
    b.add_argument("--yes", action="store_true",
                   help="archive flagged runs automatically and skip both prompts")
    b.add_argument("--dry-run", action="store_true",
                   help="show the plan (archive + sub assignment) and stop")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # The rig config already records where it writes, so use it for any root the
    # user did not set. Missing config is not fatal here -- only the task needs it.
    from_cfg = {}
    try:
        from_cfg = expconfig.roots_from_config(expconfig.load(args.experiment_config))
    except SystemExit:
        pass
    roots = Roots.resolve(
        raw_root=args.raw_root,
        acq_root=args.acq_root or (None if os.environ.get("FORAGING_ACQ_ROOT")
                                   else from_cfg.get("acq_root")),
        fictrac_root=args.fictrac_root,
        explog_root=args.explog_root or (None if os.environ.get("FORAGING_EXPLOG_ROOT")
                                         else from_cfg.get("explog_root")),
        analysis_root=args.analysis_root)

    if args.batch:
        if not args.date:
            raise SystemExit("--batch needs --date")
        if args.acquisition:
            raise SystemExit("--batch scans a whole day; drop --acquisition")
        return run_batch_day(args, roots)

    return process_one(args, roots)


if __name__ == "__main__":
    sys.exit(main())
