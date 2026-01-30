
#!/usr/bin/env python3
"""
Single Python entry point for the foraging experiment.
Ensures conda environment (daqcon) is active, then orchestrates all processes.
Optionally pass --config experiment_config.json to use paths from the GUI config.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import signal
from pathlib import Path

# Conda environment name required for nidaqmx and other packages
REQUIRED_CONDA_ENV = "daqcon"
CONDA_BASE = os.path.expanduser("~/miniconda3")

def ensure_conda_env():
    """
    Ensure we're running in the required conda environment.
    If not, re-execute this script with conda activated.
    Returns True if already in conda, False if we're re-executing.
    """
    # Check if we're already in the right conda env
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if conda_env == REQUIRED_CONDA_ENV:
        return True
    
    # Try importing nidaqmx as a test (only works in conda env)
    try:
        import nidaqmx
        # If import works, we're probably in the right env even if CONDA_DEFAULT_ENV isn't set
        return True
    except ImportError:
        pass
    
    # Not in conda - re-execute with conda activation
    conda_activate = os.path.join(CONDA_BASE, "bin", "activate")
    if not os.path.exists(conda_activate):
        print(f"ERROR: Conda not found at {CONDA_BASE}", file=sys.stderr)
        print(f"Please activate conda environment '{REQUIRED_CONDA_ENV}' before running.", file=sys.stderr)
        sys.exit(1)
    
    # Re-execute with conda activated
    script_path = os.path.abspath(__file__)
    args_str = ' '.join(shlex.quote(arg) for arg in sys.argv[1:])
    cmd = f"source {shlex.quote(conda_activate)} {REQUIRED_CONDA_ENV} && exec python3 {shlex.quote(script_path)} {args_str}"
    os.execv("/bin/bash", ["/bin/bash", "-c", cmd])
    return False  # Never reached

def parse_args():
    p = argparse.ArgumentParser(description="Run foraging experiment sequence.")
    p.add_argument("--config", type=str, default=None, help="Path to experiment_config.json for paths (GUI config).")
    p.add_argument("--baseline-session-time", type=int, default=300)
    p.add_argument("--baseline-iterations", type=int, default=0)
    p.add_argument("--training-session-time", type=int, default=300)
    p.add_argument("--probing-session-time", type=int, default=300)
    p.add_argument("--inter-session-time", type=int, default=10)
    p.add_argument("--openloop-training-session-time", type=int, default=300)
    p.add_argument("--openloop-training-iterations", type=int, default=10)
    # Same semantics as run_experiment.sh: total iterations, each with N training + M probing trials
    p.add_argument("--total-iterations", type=int, default=1)
    p.add_argument("--training-trials", type=int, default=15)
    p.add_argument("--probing-trials", type=int, default=15)
    return p.parse_args()

def load_config_paths(config_path):
    """Load path keys from experiment_config.json; return dict or None if file missing."""
    if not config_path or not os.path.isfile(config_path):
        return None
    with open(config_path, "r") as f:
        data = json.load(f)
    return data

def make_dirs(timestamp, config_paths=None):
    """
    Create the directory tree. Paths from config_paths (GUI config), else from env.
    Returns a dict with all paths for logs and CSVs.
    """
    def get(key, env_var, default):
        if config_paths and key in config_paths and config_paths[key]:
            return config_paths[key]
        return os.environ.get(env_var, default)

    unity_exe = get("unity_exe", "UNITY_EXE", "/home/kazama/Unity_Builds/turning_foraging/turning_foraging.x86_64")
    fictrac_exe = get("fictrac_exe", "FICTRAC_EXE", "/home/kazama/fictrac/bin/fictrac")
    fictrac_cfg = get("fictrac_config", "FICTRAC_CONFIG", "/home/kazama/fictrac/fictrac_config/config.txt")
    calc_path_py = get("calc_path_py", "CALC_PATH", "/home/kazama/Experiment_builds/turning_foraging/calc_path_closed_end.py")
    con_led_py = get("con_led_py", "CON_LED", "/home/kazama/Experiment_builds/turning_foraging/con_led.py")
    openloop_sim_py = get("openloop_sim_py", "OPENLOOP_SIM", "/home/kazama/Experiment_builds/openloop_sim.py")
    working_main = get("working_dir", "WORKING_DIR", "/home/kazama/Experiment_log/foraging")
    fictrac_main = os.environ.get("FICTRAC_WORKING_DIR", str(Path(working_main).parent / "fictrac") if working_main else "/home/kazama/fictrac/foraging")
    raw_csv_main = get("csv_main_dir", "CSV_MAIN_DIR", "/home/kazama/Raw_data/foraging")

    # Compose timestamped subdirectories (working_main/csv_main_dir may be full paths from config)
    working_dir = Path(working_main.rstrip("/")) / timestamp
    fictrac_dir = Path(fictrac_main.rstrip("/")) / timestamp
    raw_csv_root = Path(raw_csv_main.rstrip("/"))

    # CSV directories for each phase
    baseline_csv = raw_csv_root / timestamp / "baseline"
    training_csv = raw_csv_root / timestamp / "training"
    probing_csv = raw_csv_root / timestamp / "probing"
    openloop_csv = raw_csv_root / timestamp / "openloop_training"

    log_dir = working_dir / "logs"
    for d in (working_dir, fictrac_dir, log_dir,
              baseline_csv, training_csv, probing_csv, openloop_csv):
        d.mkdir(parents=True, exist_ok=True)

    # Paths for each log file
    ts = timestamp.replace(":", "").replace(" ", "_")
    script_log = log_dir / f"run_experiment_{ts}.log"
    calc_log   = log_dir / f"calc_path_{ts}.log"
    con_led_log= log_dir / f"con_led_{ts}.log"
    fictrac_log= log_dir / f"fictrac_{ts}.log"
    unity_base_log = log_dir / f"unity_baseline_{ts}.log"
    unity_train_log= log_dir / f"unity_training_{ts}.log"
    unity_probe_log= log_dir / f"unity_probing_{ts}.log"
    unity_openloop_log = log_dir / f"unity_openloop_training_{ts}.log"
    openloop_sim_log   = log_dir / f"openloop_sim_{ts}.log"

    return {
        "unity_exe": unity_exe,
        "fictrac_exe": fictrac_exe,
        "fictrac_cfg": fictrac_cfg,
        "calc_path_py": calc_path_py,
        "con_led_py": con_led_py,
        "openloop_sim_py": openloop_sim_py,
        "working_dir": str(working_dir),
        "fictrac_dir": str(fictrac_dir),
        "baseline_csv": str(baseline_csv),
        "training_csv": str(training_csv),
        "probing_csv": str(probing_csv),
        "openloop_csv": str(openloop_csv),
        "logs": {
            "script": str(script_log),
            "calc_path": str(calc_log),
            "con_led": str(con_led_log),
            "fictrac": str(fictrac_log),
            "unity_baseline": str(unity_base_log),
            "unity_training": str(unity_train_log),
            "unity_probing": str(unity_probe_log),
            "unity_openloop": str(unity_openloop_log),
            "openloop_sim": str(openloop_sim_log),
        }
    }

def countdown(seconds):
    """
    Simple countdown that prints remaining time in seconds.
    """
    end_time = time.time() + seconds
    while True:
        remaining = int(end_time - time.time())
        if remaining <= 0:
            print("\r✅ Countdown finished.         ")
            break
        sys.stdout.write(f"\r⏳ Time remaining: {remaining}s ")
        sys.stdout.flush()
        time.sleep(1)

def run_process(cmd_list, cwd=None, stdout_path=None, stderr_path=None):
    """
    Start a subprocess and return its Popen object.
    """
    stdout = open(stdout_path, "a") if stdout_path else subprocess.DEVNULL
    stderr = open(stderr_path, "a") if stderr_path else subprocess.DEVNULL
    # IMPORTANT:
    # Do NOT start a new session/process-group per subprocess.
    # We want all children (fictrac, unity, python helpers) to remain in the same
    # process group as this runner, so a single killpg can reliably stop everything.
    proc = subprocess.Popen(cmd_list, cwd=cwd, stdout=stdout, stderr=stderr)
    return proc

def stop_processes(proc_list, log_path=None):
    """
    Kill each process in proc_list (a list of Popen objects). Clear list afterward.
    """
    if log_path:
        with open(log_path, "a") as f:
            f.write("Stopping processes...\n")

    # Prefer stopping the whole process group once (all children inherit it).
    pgid = None
    for proc in proc_list:
        try:
            pgid = os.getpgid(proc.pid)
            break
        except Exception:
            continue

    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
            if log_path:
                with open(log_path, "a") as f:
                    f.write(f"Sent SIGTERM to process group {pgid}\n")
        except Exception:
            pass

        # Give processes time to exit cleanly
        deadline = time.time() + 3.0
        while time.time() < deadline:
            still_running = False
            for proc in proc_list:
                try:
                    if proc.poll() is None:
                        still_running = True
                        break
                except Exception:
                    continue
            if not still_running:
                break
            time.sleep(0.1)

        # Force kill remaining
        try:
            os.killpg(pgid, signal.SIGKILL)
            if log_path:
                with open(log_path, "a") as f:
                    f.write(f"Sent SIGKILL to process group {pgid}\n")
        except Exception:
            pass
    else:
        # Fallback: kill individual PIDs if we couldn't determine a group
        for proc in proc_list:
            try:
                os.kill(proc.pid, signal.SIGKILL)
            except Exception:
                pass

    proc_list.clear()

def run_openloop_training(cfg):
    ps = []
    n_iters = int(cfg["args"].openloop_training_iterations)
    session_time = int(cfg["args"].openloop_training_session_time)
    inter_time = int(cfg["args"].inter_session_time)
    for i in range(1, n_iters + 1):
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"--- Openloop iteration {i}/{n_iters} ---\n")
        # launch fictrac
        p1 = run_process(
            [cfg["fictrac_exe"], cfg["fictrac_cfg"]],
            cwd=cfg["fictrac_dir"],
            stdout_path=cfg["logs"]["fictrac"],
            stderr_path=cfg["logs"]["fictrac"]
        )
        ps.append(p1)

        # launch openloop_sim.py (use same interpreter as this script, e.g. conda)
        p2 = run_process(
            [sys.executable, cfg["openloop_sim_py"]],
            stdout_path=cfg["logs"]["openloop_sim"],
            stderr_path=cfg["logs"]["openloop_sim"]
        )
        ps.append(p2)

        # launch con_led.py
        p3 = run_process(
            [sys.executable, cfg["con_led_py"], "--zones", "0:150,1:300"],
            stdout_path=cfg["logs"]["con_led"],
            stderr_path=cfg["logs"]["con_led"]
        )
        ps.append(p3)

        # launch Unity
        p4 = run_process(
            [cfg["unity_exe"], "--csvDirectory", cfg["openloop_csv"]],
            cwd=cfg["working_dir"],
            stdout_path=cfg["logs"]["unity_openloop"],
            stderr_path=cfg["logs"]["unity_openloop"]
        )
        ps.append(p4)

        countdown(session_time)
        stop_processes(ps, log_path=cfg["logs"]["script"])
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"Waiting {inter_time}s before next openloop session\n")
        countdown(inter_time)

def run_baseline(cfg):
    ps = []
    n_iters = int(cfg["args"].baseline_iterations)
    session_time = int(cfg["args"].baseline_session_time)
    inter_time = int(cfg["args"].inter_session_time)
    for i in range(1, n_iters + 1):
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"--- Baseline iteration {i}/{n_iters} ---\n")

        # calc_path.py
        p1 = run_process(
            [sys.executable, cfg["calc_path_py"]],
            stdout_path=cfg["logs"]["calc_path"],
            stderr_path=cfg["logs"]["calc_path"]
        )
        ps.append(p1)

        # con_led.py with no zones
        p2 = run_process(
            [sys.executable, cfg["con_led_py"], "--zones", "0:none,1:none"],
            stdout_path=cfg["logs"]["con_led"],
            stderr_path=cfg["logs"]["con_led"]
        )
        ps.append(p2)

        # fictrac
        p3 = run_process(
            [cfg["fictrac_exe"], cfg["fictrac_cfg"]],
            cwd=cfg["fictrac_dir"],
            stdout_path=cfg["logs"]["fictrac"],
            stderr_path=cfg["logs"]["fictrac"]
        )
        ps.append(p3)

        # Unity baseline
        p4 = run_process(
            [cfg["unity_exe"], "--csvDirectory", cfg["baseline_csv"]],
            cwd=cfg["working_dir"],
            stdout_path=cfg["logs"]["unity_baseline"],
            stderr_path=cfg["logs"]["unity_baseline"]
        )
        ps.append(p4)

        countdown(session_time)
        stop_processes(ps, log_path=cfg["logs"]["script"])
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"Waiting {inter_time}s before next baseline session\n")
        countdown(inter_time)

def run_one_training_session(cfg):
    """Launch calc_path, con_led, fictrac, Unity for one training session; countdown; stop all."""
    ps = []
    session_time = int(cfg["args"].training_session_time)
    inter_time = int(cfg["args"].inter_session_time)
    if session_time <= 0:
        return
    p1 = run_process(
        [sys.executable, cfg["calc_path_py"]],
        stdout_path=cfg["logs"]["calc_path"],
        stderr_path=cfg["logs"]["calc_path"]
    )
    ps.append(p1)
    p2 = run_process(
        [sys.executable, cfg["con_led_py"], "--zones", "0:120,1:240"],
        stdout_path=cfg["logs"]["con_led"],
        stderr_path=cfg["logs"]["con_led"]
    )
    ps.append(p2)
    p3 = run_process(
        [cfg["fictrac_exe"], cfg["fictrac_cfg"]],
        cwd=cfg["fictrac_dir"],
        stdout_path=cfg["logs"]["fictrac"],
        stderr_path=cfg["logs"]["fictrac"]
    )
    ps.append(p3)
    p4 = run_process(
        [cfg["unity_exe"], "--csvDirectory", cfg["training_csv"]],
        cwd=cfg["working_dir"],
        stdout_path=cfg["logs"]["unity_training"],
        stderr_path=cfg["logs"]["unity_training"]
    )
    ps.append(p4)
    countdown(session_time)
    stop_processes(ps, log_path=cfg["logs"]["script"])
    with open(cfg["logs"]["script"], "a") as f:
        f.write(f"Waiting {inter_time}s before next session\n")
    countdown(inter_time)

def run_one_probing_session(cfg):
    """Launch calc_path, con_led, fictrac, Unity for one probing session; countdown; stop all."""
    ps = []
    session_time = int(cfg["args"].probing_session_time)
    inter_time = int(cfg["args"].inter_session_time)
    if session_time <= 0:
        return
    p1 = run_process(
        [sys.executable, cfg["calc_path_py"]],
        stdout_path=cfg["logs"]["calc_path"],
        stderr_path=cfg["logs"]["calc_path"]
    )
    ps.append(p1)
    p2 = run_process(
        [sys.executable, cfg["con_led_py"], "--zones", "0:60,1:120"],
        stdout_path=cfg["logs"]["con_led"],
        stderr_path=cfg["logs"]["con_led"]
    )
    ps.append(p2)
    p3 = run_process(
        [cfg["fictrac_exe"], cfg["fictrac_cfg"]],
        cwd=cfg["fictrac_dir"],
        stdout_path=cfg["logs"]["fictrac"],
        stderr_path=cfg["logs"]["fictrac"]
    )
    ps.append(p3)
    p4 = run_process(
        [cfg["unity_exe"], "--csvDirectory", cfg["probing_csv"]],
        cwd=cfg["working_dir"],
        stdout_path=cfg["logs"]["unity_probing"],
        stderr_path=cfg["logs"]["unity_probing"]
    )
    ps.append(p4)
    countdown(session_time)
    stop_processes(ps, log_path=cfg["logs"]["script"])
    with open(cfg["logs"]["script"], "a") as f:
        f.write(f"Waiting {inter_time}s before next session\n")
    countdown(inter_time)

def run_main_iteration_loop(cfg):
    """Same as bash: total_iterations, each with training_trials then probing_trials."""
    total = int(cfg["args"].total_iterations)
    n_train = int(cfg["args"].training_trials)
    n_probe = int(cfg["args"].probing_trials)
    with open(cfg["logs"]["script"], "a") as f:
        f.write(f"Running {total} iteration(s) with {n_train} training trial(s) and {n_probe} probing trial(s) per iteration.\n")
    for iter_num in range(1, total + 1):
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"==== Starting iteration {iter_num}/{total} ====\n")
        for t in range(1, n_train + 1):
            with open(cfg["logs"]["script"], "a") as f:
                f.write(f"--- Training trial {t}/{n_train} in iteration {iter_num} ---\n")
            run_one_training_session(cfg)
        for p in range(1, n_probe + 1):
            with open(cfg["logs"]["script"], "a") as f:
                f.write(f"--- Probing trial {p}/{n_probe} in iteration {iter_num} ---\n")
            run_one_probing_session(cfg)
        with open(cfg["logs"]["script"], "a") as f:
            f.write(f"==== Finished iteration {iter_num}/{total} ====\n")

def main():
    # Ensure conda environment is active before doing anything
    ensure_conda_env()
    
    args = parse_args()
    config_paths = load_config_paths(args.config) if args.config else None
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    paths = make_dirs(timestamp, config_paths)
    cfg = {
        "args": args,
        "unity_exe": paths["unity_exe"],
        "fictrac_exe": paths["fictrac_exe"],
        "fictrac_cfg": paths["fictrac_cfg"],
        "calc_path_py": paths["calc_path_py"],
        "con_led_py": paths["con_led_py"],
        "openloop_sim_py": paths["openloop_sim_py"],
        "working_dir": paths["working_dir"],
        "fictrac_dir": paths["fictrac_dir"],
        "baseline_csv": paths["baseline_csv"],
        "training_csv": paths["training_csv"],
        "probing_csv": paths["probing_csv"],
        "openloop_csv": paths["openloop_csv"],
        "logs": paths["logs"]
    }

    if args.openloop_training_session_time > 0:
        run_openloop_training(cfg)
    if args.baseline_session_time > 0:
        run_baseline(cfg)
    run_main_iteration_loop(cfg)

    with open(cfg["logs"]["script"], "a") as f:
        f.write("All iterations completed.\n")

if __name__ == "__main__":
    main()
