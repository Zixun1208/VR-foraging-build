"""Find sessions and their trial selection under an acquisition tree.

Layout read: ``<raw-root>/<date>/<task>/<sub>/`` holding ``training/``, ``probing/``,
``flash_events/`` and a selection json. ``--selection recommended`` (default) reads
``session_selection_recommended_<date>_<sub>.json`` written by foraging_preprocess;
``applied`` reads the live ``session_selection_<date>_<sub>.json``.

Only trials listed in the selection's ``training_basenames`` / ``probing_basenames`` are
kept. Nothing here applies or promotes a recommendation.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

from .. import config

RAW_ROOT = config.RAW_ROOT


@dataclass(frozen=True)
class SelectedSession:
    date: str
    sub: str
    task: str
    sub_dir: str
    atr: bool | None           # from the recommendation block when present
    kept: dict                 # {"training": frozenset(basenames), "probing": ...}

    @property
    def fly_id(self) -> str:
        return f"{self.date}_{self.sub}"


def _pattern(kind: str) -> str:
    return ("session_selection_recommended_*.json" if kind == "recommended"
            else "session_selection_[0-9]*.json")


def load_selection(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def iter_selected(raw_root: str = RAW_ROOT, kind: str = "recommended",
                  task: str | None = None, dates: set[str] | None = None):
    """Yield a SelectedSession per session directory that has the requested selection."""
    for sel_path in sorted(glob.glob(os.path.join(raw_root, "*", "*", "*", _pattern(kind)))):
        sub_dir = os.path.dirname(sel_path)
        sub = os.path.basename(sub_dir)
        task_name = os.path.basename(os.path.dirname(sub_dir))
        date = os.path.basename(os.path.dirname(os.path.dirname(sub_dir)))
        if task and task_name != task:
            continue
        if dates and date not in dates:
            continue
        sel = load_selection(sel_path)
        rec = sel.get("recommendation") or {}
        yield SelectedSession(
            date=date, sub=sub, task=task_name, sub_dir=sub_dir,
            atr=rec.get("atr"),
            kept={"training": frozenset(sel.get("training_basenames") or ()),
                  "probing": frozenset(sel.get("probing_basenames") or ())},
        )
