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
    "zone0_max_volts": "5.0",
    "zone0_min_volts": "0.2",
    "zone1_max_volts": "5.0",
    "zone1_min_volts": "0.2",
    "flash_frequency_hz": "50.0",
    "decay_mode": "exp",
    "trial_start_z": "",
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
    ("Zone 0 max amplitude (V):", "zone0_max_volts"),
    ("Zone 0 min amplitude (V):", "zone0_min_volts"),
    ("Zone 1 max amplitude (V):", "zone1_max_volts"),
    ("Zone 1 min amplitude (V):", "zone1_min_volts"),
    ("Flash frequency (Hz):", "flash_frequency_hz"),
    ("Decay mode (exp|linear):", "decay_mode"),
    ("Trial start z (blank=default):", "trial_start_z"),
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


def _default_config_path() -> str:
    return str(Path(__file__).resolve().parent / "experiment_config.json")


def resolve_config_path(raw: str) -> str:
    """Resolve config file path; relative paths are taken from this script's directory."""
    s = (raw or "").strip()
    if not s:
        return _default_config_path()
    p = Path(s).expanduser()
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    return str(p.resolve())


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

    def apply_saved_json(saved: dict[str, Any]) -> None:
        for key in paths:
            if key in saved:
                paths[key] = str(saved[key])
        if "zone0_max_volts" not in saved and "max_amplitude_volts" in saved:
            m = str(saved["max_amplitude_volts"])
            paths["zone0_max_volts"] = m
            paths["zone1_max_volts"] = m
        if "zone0_min_volts" not in saved and "min_amplitude_volts" in saved:
            m = str(saved["min_amplitude_volts"])
            paths["zone0_min_volts"] = m
            paths["zone1_min_volts"] = m
        paths["iterations"] = str(
            saved.get("iterations", saved.get("training_iterations", paths["iterations"]))
        )
        for key, inp in field_inputs.items():
            inp.value = str(paths.get(key, ""))

    def load_config_from_disk(*, silent: bool = False) -> None:
        path = resolve_config_path(config_path_input.value)
        config_path_input.value = path
        if not os.path.isfile(path):
            if not silent:
                ui.notify(f"No file at {path}", type="warning")
            return
        with open(path, encoding="utf-8") as f:
            saved: dict[str, Any] = json.load(f)
        apply_saved_json(saved)
        if not silent:
            ui.notify(f"Loaded config from {path}", type="positive")

    def save_config_to_disk() -> None:
        _sync_paths_from_ui()
        path = resolve_config_path(config_path_input.value)
        config_path_input.value = path
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(paths, f, indent=2)
        ui.notify(f"Saved config to {path}", type="positive")

    with ui.splitter(value=58).classes("w-full").style("height: calc(100vh - 120px)") as splitter:
        with splitter.before:
            with ui.scroll_area().classes("w-full h-full"):
                with ui.column().classes("w-full q-gutter-y-sm q-pa-sm"):
                    with ui.card().classes("w-full"):
                        ui.label("Config file").classes("text-subtitle1 text-weight-medium")
                        with ui.row().classes("w-full items-center no-wrap q-gutter-x-sm"):
                            ui.label("JSON path").classes("w-48 shrink-0 text-right")
                            config_path_input = (
                                ui.input(value=_default_config_path())
                                .props("dense outlined")
                                .classes("flex-grow min-w-0")
                                .tooltip("Relative paths are resolved from the folder containing exp_gui.py")
                            )

                            async def _browse_config() -> None:
                                start = _picker_start_dir(config_path_input.value or "")
                                picker = local_file_picker(str(start), pick_directory=False, upper_limit=None)
                                result = await picker
                                if result:
                                    config_path_input.value = result[0]

                            ui.button("Browse", on_click=_browse_config).props("dense flat")
                            ui.button("Load", on_click=lambda: load_config_from_disk(silent=False)).props(
                                "dense flat"
                            )

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
                        ui.button("Save config", color="primary", on_click=save_config_to_disk)
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
        z0_max = paths["zone0_max_volts"]
        z0_min = paths["zone0_min_volts"]
        z1_max = paths["zone1_max_volts"]
        z1_min = paths["zone1_min_volts"]
        flash_frequency_hz = paths["flash_frequency_hz"]
        decay_mode = paths["decay_mode"].strip().lower()
        trial_start_z = paths["trial_start_z"].strip()

        if decay_mode not in {"exp", "linear"}:
            ui.notify("Decay mode must be 'exp' or 'linear'.", type="negative")
            return
        try:
            z0_max_f = float(z0_max)
            z0_min_f = float(z0_min)
            z1_max_f = float(z1_max)
            z1_min_f = float(z1_min)
        except ValueError:
            ui.notify("Zone amplitude fields must be numeric.", type="negative")
            return
        if z0_min_f <= 0 or z1_min_f <= 0:
            ui.notify("Zone min amplitude must be greater than 0.", type="negative")
            return
        if z0_max_f <= z0_min_f or z1_max_f <= z1_min_f:
            ui.notify("Each zone max amplitude must be greater than that zone's min.", type="negative")
            return
        max_amplitude_volts = str(max(z0_max_f, z1_max_f))
        min_amplitude_volts = str(min(z0_min_f, z1_min_f))
        max_amplitude_volts_by_zone = f"0:{z0_max},1:{z1_max}"
        min_amplitude_volts_by_zone = f"0:{z0_min},1:{z1_min}"
        if trial_start_z:
            try:
                float(trial_start_z)
            except ValueError:
                ui.notify("Trial start z must be numeric or blank.", type="negative")
                return

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
            "--max-amplitude-volts-by-zone",
            max_amplitude_volts_by_zone,
            "--min-amplitude-volts-by-zone",
            min_amplitude_volts_by_zone,
            "--max-amplitude-volts",
            max_amplitude_volts,
            "--min-amplitude-volts",
            min_amplitude_volts,
            "--flash-frequency-hz",
            flash_frequency_hz,
            "--decay-mode",
            decay_mode,
        ]
        if trial_start_z:
            command.extend(["--trial-start-z", trial_start_z])

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

    load_config_from_disk(silent=True)


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
