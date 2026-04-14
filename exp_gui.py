"""Experiment launcher GUI (NiceGUI): edit paths and parameters, run bash driver, stream logs."""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
from pathlib import Path
from time import monotonic
from typing import Any

from local_file_picker import local_file_picker
from nicegui import app, ui

CONFIG_FILE = "experiment_config.json"
process: subprocess.Popen[str] | None = None

paths: dict[str, str] = {
    "bash_script": "",
    "unity_exe": "",
    "fictrac_exe": "",
    "fictrac_config": "",
    "calc_path_py": "",
    "con_led_py": "",
    "openloop_sim_py": "",
    "working_dir": "",
    "csv_main_dir": "",
    "openloop_training_iterations": "0",
    "baseline_iterations": "0",
    "iterations": "15",
    "training_trials_per_iteration": "1",
    "probing_trials_per_iteration": "1",
    "path_length": "100",
    "openloop_zones": "0:150,1:300",
    "baseline_zones": "0:none,1:none",
    "training_zones": "0:100,1:20",
    "probing_zones": "0:none,1:none",
    "ao_channel": "cDAQ1Mod2/ao0",
    "max_amplitude_volts": "5.0",
    "min_amplitude_volts": "0.2",
    "flash_frequency_hz": "50.0",
    "loop_sequence": "1",
}

FILE_FIELDS: list[tuple[str, str, bool]] = [
    ("Bash Script", "bash_script", False),
    ("Unity Executable", "unity_exe", False),
    ("FicTrac Executable", "fictrac_exe", False),
    ("FicTrac Config", "fictrac_config", False),
    ("calc_path.py", "calc_path_py", False),
    ("con_led.py", "con_led_py", False),
    ("Working Directory", "working_dir", True),
    ("CSV Main Directory", "csv_main_dir", True),
    ("openloop_sim.py", "openloop_sim_py", False),
]

PARAM_FIELDS: list[tuple[str, str]] = [
    ("Openloop Training Iterations:", "openloop_training_iterations"),
    ("Baseline Iterations:", "baseline_iterations"),
    ("Iterations:", "iterations"),
    ("Training trials per iteration:", "training_trials_per_iteration"),
    ("Probing trials per iteration:", "probing_trials_per_iteration"),
    ("Path length (z units):", "path_length"),
    ("Openloop zones (zone:decay,...):", "openloop_zones"),
    ("Baseline zones (zone:decay,...):", "baseline_zones"),
    ("Training zones (zone:decay,...):", "training_zones"),
    ("Probing zones (zone:decay,...):", "probing_zones"),
    ("AO channel:", "ao_channel"),
    ("Max amplitude (V):", "max_amplitude_volts"),
    ("Min amplitude (V):", "min_amplitude_volts"),
    ("Flash frequency (Hz):", "flash_frequency_hz"),
    ("Loop sequence (1=yes,0=no):", "loop_sequence"),
]

field_inputs: dict[str, ui.input] = {}
_LOG_DONE = object()


def _terminate_experiment_if_running() -> None:
    """Kill bash experiment process group so child processes exit when the GUI server stops."""
    global process
    p = process
    if not p or p.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        p.wait(timeout=8.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


app.on_shutdown(_terminate_experiment_if_running)


def _sync_paths_from_ui() -> None:
    for key, inp in field_inputs.items():
        paths[key] = (inp.value or "").strip()


def load_config() -> None:
    if not os.path.exists(CONFIG_FILE):
        return
    with open(CONFIG_FILE, encoding="utf-8") as f:
        saved: dict[str, Any] = json.load(f)
    for key in paths:
        if key in saved:
            paths[key] = str(saved[key])
    paths["iterations"] = str(
        saved.get("iterations", saved.get("training_iterations", paths["iterations"]))
    )
    for key, inp in field_inputs.items():
        inp.value = str(paths.get(key, ""))


def save_config() -> None:
    _sync_paths_from_ui()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(paths, f, indent=2)
    ui.notify("Default paths and parameters saved.", type="positive")


def _picker_start_dir(raw: str) -> Path:
    """Best-effort starting directory for the in-browser picker (server-side paths)."""
    if raw.strip():
        p = Path(raw).expanduser()
        if p.is_dir():
            try:
                return p.resolve()
            except OSError:
                return p
        if p.is_file():
            try:
                return p.resolve().parent
            except OSError:
                return p.parent
        parent = p.parent
        if parent.is_dir():
            try:
                return parent.resolve()
            except OSError:
                return parent
    return Path.cwd()


async def browse_path(key: str, is_dir: bool) -> None:
    """Server-side filesystem picker (NiceGUI local_file_picker example)."""
    start = _picker_start_dir(field_inputs[key].value or "")
    picker = local_file_picker(str(start), pick_directory=is_dir, upper_limit=None)
    result = await picker
    if result:
        field_inputs[key].value = result[0]


@ui.page("/")
def main_page() -> None:
    log_queue: queue.Queue[str | object] = queue.Queue()
    start_btn: ui.button
    stop_btn: ui.button
    pos_line_re = re.compile(r"\[pos\]\s*(.+)")
    raw_pos_re = re.compile(r"^\s*-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?\s*$")
    latest_pos_text = "waiting for stream..."
    last_pos_ui_update = 0.0

    ui.label("Foraging Experiment").classes("text-h5 q-mt-sm q-mb-sm")

    with ui.splitter(value=58).classes("w-full").style("height: calc(100vh - 120px)") as splitter:
        with splitter.before:
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full q-gutter-y-sm q-pa-sm"):
                    with ui.card().classes("w-full"):
                        ui.label("Paths").classes("text-subtitle1 text-weight-medium")
                        for label, key, is_dir in FILE_FIELDS:
                            with ui.row().classes("w-full items-center no-wrap q-gutter-x-sm"):
                                ui.label(label).classes("w-48 shrink-0 text-right")
                                inp = (
                                    ui.input(value=paths[key])
                                    .props("dense outlined")
                                    .classes("flex-grow min-w-0")
                                )
                                field_inputs[key] = inp

                                async def _browse(k: str = key, directory: bool = is_dir) -> None:
                                    await browse_path(k, directory)

                                ui.button("Browse", on_click=_browse).props("dense flat")

                    with ui.card().classes("w-full"):
                        ui.label("Session parameters").classes("text-subtitle1 text-weight-medium")
                        for label, key in PARAM_FIELDS:
                            with ui.row().classes("w-full items-center no-wrap q-gutter-x-sm"):
                                ui.label(label).classes("w-48 shrink-0 text-right")
                                field_inputs[key] = (
                                    ui.input(value=paths[key])
                                    .props("dense outlined")
                                    .classes("flex-grow min-w-0")
                                )

                    with ui.row().classes("w-full q-gutter-sm q-pb-md"):
                        start_btn = ui.button("Start Experiment", color="positive")
                        ui.button("Save as Default", color="primary", on_click=save_config)
                        stop_btn = ui.button("Stop Experiment", color="negative")
                        stop_btn.disable()
                        ui.button("Quit GUI", on_click=app.shutdown).props("outline")

        with splitter.after:
            ui.label("Log").classes("text-subtitle2 q-ml-sm")
            with ui.card().classes("w-full h-full").style("min-height: 0"):
                position_status = ui.label("Position: waiting for stream...").classes(
                    "w-full q-pa-sm font-mono text-sm"
                )
                experiment_log = ui.log(max_lines=2000).classes("w-full font-mono text-sm")

    def finish_run() -> None:
        start_btn.enable()
        stop_btn.disable()

    def drain_log() -> None:
        nonlocal latest_pos_text, last_pos_ui_update
        try:
            while True:
                item = log_queue.get_nowait()
                if item is _LOG_DONE:
                    experiment_log.push("\nExperiment finished.\n")
                    position_status.set_text("Position: stopped")
                    finish_run()
                else:
                    text = str(item)
                    # Treat any line containing "[pos]" as a live status update, never a log line.
                    if "[pos]" in text:
                        pos_match = pos_line_re.search(text)
                        if pos_match:
                            latest_pos_text = pos_match.group(1).strip()
                        continue

                    if raw_pos_re.match(text):
                        z_val, x_val, r_val = [v.strip() for v in text.split(",")]
                        latest_pos_text = f"z={z_val} x={x_val} r={r_val}"
                        continue

                    experiment_log.push(text)
        except queue.Empty:
            pass
        now = monotonic()
        if now - last_pos_ui_update >= 0.1:
            position_status.set_text(f"Position: {latest_pos_text}")
            last_pos_ui_update = now

    ui.timer(0.05, drain_log)

    def run_experiment() -> None:
        global process
        nonlocal latest_pos_text, last_pos_ui_update
        _sync_paths_from_ui()
        baseline_iterations = paths["baseline_iterations"]
        iterations = paths["iterations"]
        training_trials_per_iter = paths["training_trials_per_iteration"]
        probing_trials_per_iter = paths["probing_trials_per_iteration"]
        openloop_training_iterations = paths["openloop_training_iterations"]
        path_length = paths["path_length"]
        openloop_zones = paths["openloop_zones"]
        baseline_zones = paths["baseline_zones"]
        training_zones = paths["training_zones"]
        probing_zones = paths["probing_zones"]
        ao_channel = paths["ao_channel"]
        max_amplitude_volts = paths["max_amplitude_volts"]
        min_amplitude_volts = paths["min_amplitude_volts"]
        flash_frequency_hz = paths["flash_frequency_hz"]
        loop_sequence = paths["loop_sequence"]

        if not os.path.isfile(paths["bash_script"]):
            ui.notify(f"Bash script not found: {paths['bash_script']}", type="negative")
            return

        env = os.environ.copy()
        env.update(
            {
                "UNITY_EXE": paths["unity_exe"],
                "FICTRAC_EXE": paths["fictrac_exe"],
                "FICTRAC_CONFIG": paths["fictrac_config"],
                "CALC_PATH": paths["calc_path_py"],
                "CON_LED": paths["con_led_py"],
                "WORKING_DIR": paths["working_dir"],
                "CSV_MAIN_DIR": paths["csv_main_dir"],
                "OPENLOOP_SIM": paths["openloop_sim_py"],
            }
        )

        command = [
            "bash",
            paths["bash_script"],
            "--baseline-iterations",
            baseline_iterations,
            "--iterations",
            iterations,
            "--training-trials-per-iteration",
            training_trials_per_iter,
            "--probing-trials-per-iteration",
            probing_trials_per_iter,
            "--openloop-training-iterations",
            openloop_training_iterations,
            "--path-length",
            path_length,
            "--openloop-zones",
            openloop_zones,
            "--baseline-zones",
            baseline_zones,
            "--training-zones",
            training_zones,
            "--probing-zones",
            probing_zones,
            "--ao-channel",
            ao_channel,
            "--max-amplitude-volts",
            max_amplitude_volts,
            "--min-amplitude-volts",
            min_amplitude_volts,
            "--flash-frequency-hz",
            flash_frequency_hz,
            "--loop-sequence",
            loop_sequence,
        ]

        start_btn.disable()
        stop_btn.enable()
        experiment_log.clear()
        latest_pos_text = "waiting for stream..."
        last_pos_ui_update = 0.0
        position_status.set_text("Position: waiting for stream...")
        experiment_log.push("Starting experiment...\n")

        def target() -> None:
            global process
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                preexec_fn=os.setsid,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log_queue.put(line.rstrip("\n"))
            process.wait()
            log_queue.put(_LOG_DONE)

        threading.Thread(target=target, daemon=True).start()

    def stop_experiment() -> None:
        global process
        if process and process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            log_queue.put("\nExperiment stopped by user.\n")
            log_queue.put("[pos] stopped")

    start_btn.on_click(run_experiment)
    stop_btn.on_click(stop_experiment)

    load_config()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Foraging Experiment GUI",
        dark=True,
        host="127.0.0.1",
        port=8080,
        reload=False,
        show=True,
        show_welcome_message=False,
    )
