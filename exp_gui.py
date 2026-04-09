import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, scrolledtext
from ttkbootstrap import Style, Button
from ttkbootstrap.constants import *
import subprocess
import threading
import os
import json
import signal

CONFIG_FILE = "experiment_config.json"
process = None  # Track running experiment process

paths = {
    "bash_script": "",
    "unity_exe": "",
    "fictrac_exe": "",
    "fictrac_config": "",
    "calc_path_py": "",
    "con_led_py": "",
    "openloop_sim_py": "",
    "working_dir": "",
    "csv_main_dir": "",
    "openloop_training_time": "0",
    "baseline_time": "300",
    "inter_session_time": "60",
    "openloop_training_iterations": "0",
    "baseline_iterations": "0",
    "iterations": "15",
    "training_session_time": "300",
    "probing_session_time": "300",
    "training_trials_per_iteration": "1",
    "probing_trials_per_iteration": "1",
    "path_length": "100",
    "openloop_zones": "0:150,1:300",
    "baseline_zones": "0:none,1:none",
    "training_zones": "0:100,1:20",
    "probing_zones": "0:none,1:none"
}

# Setup dark style
style = Style("darkly")
root = style.master
root.title("Foraging Experiment GUI")
entry_vars = {}

# Use a larger, cleaner default UI font for readability.
UI_FONT = ("Noto Sans", 12)
LOG_FONT = ("JetBrains Mono", 11)
default_font = tkfont.nametofont("TkDefaultFont")
default_font.configure(family=UI_FONT[0], size=UI_FONT[1])
root.option_add("*Font", default_font)
style.configure("TButton", font=UI_FONT)

def browse_path(key, is_dir=False):
    path = (
        filedialog.askdirectory(title=f"Select {key.replace('_', ' ').title()}")
        if is_dir else
        filedialog.askopenfilename(title=f"Select {key.replace('_', ' ').title()}")
    )
    if path:
        paths[key] = path
        entry_vars[key].set(path)

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            saved = json.load(f)
            for key in paths:
                paths[key] = saved.get(key, paths[key])
                if key in entry_vars:
                    entry_vars[key].set(paths[key])
        baseline_time_var.set(saved.get("baseline_time", "300"))
        inter_time_var.set(saved.get("inter_session_time", "60"))
        baseline_iterations_var.set(saved.get("baseline_iterations", "0"))
        iterations_var.set(saved.get("iterations", saved.get("training_iterations", "15")))
        training_session_time_var.set(saved.get("training_session_time", "300"))
        probing_session_time_var.set(saved.get("probing_session_time", "300"))
        training_trials_per_iter_var.set(saved.get("training_trials_per_iteration", "1"))
        probing_trials_per_iter_var.set(saved.get("probing_trials_per_iteration", "1"))
        openloop_training_time_var.set(saved.get("openloop_training_time", "0"))
        openloop_training_iterations_var.set(saved.get("openloop_training_iterations", "0"))
        path_length_var.set(saved.get("path_length", "100"))
        openloop_zones_var.set(saved.get("openloop_zones", "0:150,1:300"))
        baseline_zones_var.set(saved.get("baseline_zones", "0:none,1:none"))
        training_zones_var.set(saved.get("training_zones", "0:100,1:20"))
        probing_zones_var.set(saved.get("probing_zones", "0:none,1:none"))

def save_config():
    for key in entry_vars:
        paths[key] = entry_vars[key].get()
    paths["baseline_time"] = baseline_time_var.get()
    paths["inter_session_time"] = inter_time_var.get()
    paths["baseline_iterations"] = baseline_iterations_var.get()
    paths["iterations"] = iterations_var.get()
    paths["training_session_time"] = training_session_time_var.get()
    paths["probing_session_time"] = probing_session_time_var.get()
    paths["training_trials_per_iteration"] = training_trials_per_iter_var.get()
    paths["probing_trials_per_iteration"] = probing_trials_per_iter_var.get()
    paths["openloop_training_time"] = openloop_training_time_var.get()
    paths["openloop_training_iterations"] = openloop_training_iterations_var.get()
    paths["path_length"] = path_length_var.get()
    paths["openloop_zones"] = openloop_zones_var.get()
    paths["baseline_zones"] = baseline_zones_var.get()
    paths["training_zones"] = training_zones_var.get()
    paths["probing_zones"] = probing_zones_var.get()
    with open(CONFIG_FILE, "w") as f:
        json.dump(paths, f, indent=2)
    messagebox.showinfo("Saved", "Default paths saved!")

# File path inputs
file_fields = [
    ("Bash Script", "bash_script", False),
    ("Unity Executable", "unity_exe", False),
    ("FicTrac Executable", "fictrac_exe", False),
    ("FicTrac Config", "fictrac_config", False),
    ("calc_path.py", "calc_path_py", False),
    ("con_led.py", "con_led_py", False),
    ("Working Directory", "working_dir", True),
    ("CSV Main Directory", "csv_main_dir", True),
    ("openloop_sim.py", "openloop_sim_py", False)
]

row = 0
for label, key, is_dir in file_fields:
    tk.Label(root, text=f"{label}:", font=UI_FONT).grid(row=row, column=0, sticky="e", padx=5, pady=2)
    var = tk.StringVar()
    entry_vars[key] = var
    tk.Entry(root, textvariable=var, width=60, font=UI_FONT).grid(row=row, column=1, padx=5, pady=2)
    Button(root, text="Browse", command=lambda k=key, d=is_dir: browse_path(k, d)).grid(row=row, column=2, padx=5)
    row += 1

# Time/iteration parameters
def add_param(label, var, default):
    global row
    tk.Label(root, text=label, font=UI_FONT).grid(row=row, column=0, sticky="e", padx=5, pady=2)
    var.set(default)
    tk.Entry(root, textvariable=var, font=UI_FONT).grid(row=row, column=1, padx=5)
    row += 1

baseline_time_var = tk.StringVar()
inter_time_var = tk.StringVar()
baseline_iterations_var = tk.StringVar()
iterations_var = tk.StringVar()
training_trials_per_iter_var = tk.StringVar()
probing_trials_per_iter_var = tk.StringVar()
training_session_time_var = tk.StringVar()
probing_session_time_var = tk.StringVar()
openloop_training_time_var = tk.StringVar()
openloop_training_iterations_var = tk.StringVar()
path_length_var = tk.StringVar()
openloop_zones_var = tk.StringVar()
baseline_zones_var = tk.StringVar()
training_zones_var = tk.StringVar()
probing_zones_var = tk.StringVar()

add_param("Openloop Training Session Time (s):", openloop_training_time_var, "0")
add_param("Openloop Training Iterations:", openloop_training_iterations_var, "0")
add_param("Baseline Session Time (s):", baseline_time_var, "300")
add_param("Baseline Iterations:", baseline_iterations_var, "0")
add_param("Iterations:", iterations_var, "15")
add_param("Training session time (s):", training_session_time_var, "300")
add_param("Probing session time (s):", probing_session_time_var, "300")
add_param("Training trials per iteration:", training_trials_per_iter_var, "1")
add_param("Probing trials per iteration:", probing_trials_per_iter_var, "1")
add_param("Inter-session Time (s):", inter_time_var, "60")
add_param("Path length (z units):", path_length_var, "100")
add_param("Openloop zones (zone:decay,...):", openloop_zones_var, "0:150,1:300")
add_param("Baseline zones (zone:decay,...):", baseline_zones_var, "0:none,1:none")
add_param("Training zones (zone:decay,...):", training_zones_var, "0:100,1:20")
add_param("Probing zones (zone:decay,...):", probing_zones_var, "0:none,1:none")

# Buttons
start_button = Button(root, text="Start Experiment", bootstyle=SUCCESS)
stop_button = Button(root, text="Stop Experiment", bootstyle=DANGER)
save_button = Button(root, text="Save as Default", command=save_config, bootstyle=INFO)

start_button.grid(row=row, column=0, pady=10)
save_button.grid(row=row, column=1, pady=10)
stop_button.grid(row=row, column=2, pady=10)
row += 1

# Log output
log_output = scrolledtext.ScrolledText(root, width=100, height=25, font=LOG_FONT)
log_output.grid(row=row, column=0, columnspan=3, padx=10, pady=10)

def run_experiment():
    global process
    baseline_time = baseline_time_var.get()
    baseline_iterations = baseline_iterations_var.get()
    inter_session_time = inter_time_var.get()
    iterations = iterations_var.get()
    training_trials_per_iter = training_trials_per_iter_var.get()
    probing_trials_per_iter = probing_trials_per_iter_var.get()
    openloop_training_time = openloop_training_time_var.get()
    openloop_training_iterations = openloop_training_iterations_var.get()
    training_session_time = training_session_time_var.get()
    probing_session_time = probing_session_time_var.get()
    path_length = path_length_var.get()
    openloop_zones = openloop_zones_var.get()
    baseline_zones = baseline_zones_var.get()
    training_zones = training_zones_var.get()
    probing_zones = probing_zones_var.get()

    if not os.path.isfile(paths["bash_script"]):
        messagebox.showerror("Error", f"Bash script not found: {paths['bash_script']}")
        return

    env = os.environ.copy()
    env.update({
        "UNITY_EXE": paths["unity_exe"],
        "FICTRAC_EXE": paths["fictrac_exe"],
        "FICTRAC_CONFIG": paths["fictrac_config"],
        "CALC_PATH": paths["calc_path_py"],
        "CON_LED": paths["con_led_py"],
        "WORKING_DIR": paths["working_dir"],
        "CSV_MAIN_DIR": paths["csv_main_dir"],
        "OPENLOOP_SIM": paths["openloop_sim_py"]
    })

    command = [
        "bash", paths["bash_script"],
        "--baseline-session-time", baseline_time,
        "--baseline-iterations", baseline_iterations,
        "--iterations", iterations,
        "--training-trials-per-iteration", training_trials_per_iter,
        "--probing-trials-per-iteration", probing_trials_per_iter,
        "--inter-session-time", inter_session_time,
        "--openloop-training-session-time", openloop_training_time,
        "--openloop-training-iterations", openloop_training_iterations,
        "--training-session-time", training_session_time,
        "--probing-session-time", probing_session_time,
        "--path-length", path_length,
        "--openloop-zones", openloop_zones,
        "--baseline-zones", baseline_zones,
        "--training-zones", training_zones,
        "--probing-zones", probing_zones
    ]

    start_button.config(state="disabled")
    stop_button.config(state="normal")
    log_output.delete(1.0, tk.END)
    log_output.insert(tk.END, "Starting experiment...\n")

    def target():
        global process
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            preexec_fn=os.setsid  # Allows killing the whole process group
        )
        for line in process.stdout:
            log_output.insert(tk.END, line)
            log_output.see(tk.END)
        process.wait()
        log_output.insert(tk.END, "\nExperiment finished.\n")
        start_button.config(state="normal")
        stop_button.config(state="disabled")

    threading.Thread(target=target, daemon=True).start()

def stop_experiment():
    global process
    if process and process.poll() is None:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        log_output.insert(tk.END, "\nExperiment stopped by user.\n")
        start_button.config(state="normal")
        stop_button.config(state="disabled")

start_button.config(command=run_experiment)
stop_button.config(command=stop_experiment)
stop_button.config(state="disabled")

load_config()
root.mainloop()

