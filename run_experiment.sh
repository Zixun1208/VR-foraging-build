#!/bin/bash
# Unset variables and failing pipeline stages are bugs, not silent no-ops.
# `errexit` is deliberately omitted: the cleanup trap and explicit checks
# below handle failures, and background job management interacts badly with it.
set -uo pipefail

# Parameter defaults come from experiment_defaults.json via experiment_defaults.py,
# so the shell script, the GUI and con_led cannot drift apart. CLI flags below
# override them.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
defaults_shell=$(python3 "$SCRIPT_DIR/experiment_defaults.py" --shell) || {
    echo "[PREFLIGHT ERROR] Could not load experiment_defaults.json — aborting." >&2
    exit 1
}
eval "$defaults_shell"
unset defaults_shell

USE_FICTRAC_SIM=0
ABORT_ON_COMPONENT_FAILURE=1

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --iterations) ITERATIONS="$2"; shift ;;
        --training-trials-per-iteration) TRAINING_TRIALS_PER_ITERATION="$2"; shift ;;
        --probing-trials-per-iteration) PROBING_TRIALS_PER_ITERATION="$2"; shift ;;
        --baseline-iterations) BASELINE_ITERATIONS="$2"; shift ;;
        --openloop-training-iterations) OPENLOOP_TRAINING_ITERATIONS="$2"; shift ;;
        --path-length) PATH_LENGTH="$2"; shift ;;
        --openloop-zones) OPENLOOP_ZONES="$2"; shift ;;
        --baseline-zones) BASELINE_ZONES="$2"; shift ;;
        --training-zones) TRAINING_ZONES="$2"; shift ;;
        --probing-zones) PROBING_ZONES="$2"; shift ;;
        --ao-channel) AO_CHANNEL="$2"; shift ;;
        --max-amplitude-volts-by-zone) MAX_AMPLITUDE_VOLTS_BY_ZONE="$2"; shift ;;
        --min-amplitude-volts-by-zone) MIN_AMPLITUDE_VOLTS_BY_ZONE="$2"; shift ;;
        --max-amplitude-volts) MAX_AMPLITUDE_VOLTS="$2"; shift ;;
        --min-amplitude-volts) MIN_AMPLITUDE_VOLTS="$2"; shift ;;
        --flash-frequency-hz) FLASH_FREQUENCY_HZ="$2"; shift ;;
        --decay-mode) DECAY_MODE="$2"; shift ;;
        --trial-start-z) TRIAL_START_Z="$2"; shift ;;
        --use-fictrac-sim) USE_FICTRAC_SIM="$2"; shift ;;
        --abort-on-component-failure) ABORT_ON_COMPONENT_FAILURE="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
UNITY_EXE="${UNITY_EXE:-/home/kazama/Unity_Builds/turning_foraging/turning_foraging.x86_64}"
FICTRAC_EXE="${FICTRAC_EXE:-/home/kazama/fictrac/bin/fictrac}"
FICTRAC_CONFIG="${FICTRAC_CONFIG:-/home/kazama/fictrac/fictrac_config/config.txt}"
FICTRAC_SIM_EXE="${FICTRAC_SIM_EXE:-/home/kazama/Experiment_builds/VR-foraging-build/test_tools/fictrac_socket_stub.py}"
calc_path_exe="${CALC_PATH:-/home/kazama/Experiment_builds/VR-foraging-build/calc_path.py}"
con_led_exe="${CON_LED:-/home/kazama/Experiment_builds/VR-foraging-build/con_led.py}"
coordinator_exe="${TRIAL_COORDINATOR:-/home/kazama/Experiment_builds/VR-foraging-build/trial_coordinator.py}"
WORKING_MAIN_DIR="${WORKING_DIR:-/home/kazama/Experiment_log/foraging}"
RAW_CSV_MAIN_DIR="${CSV_MAIN_DIR:-/home/kazama/Raw_data/foraging}"
FICTRAC_WORKING_MAIN_DIR="${FICTRAC_WORKING_DIR:-/home/kazama/fictrac/foraging}"

WORKING_DIR="$WORKING_MAIN_DIR/${TIMESTAMP}"
FICTRAC_WORKING_DIR="$FICTRAC_WORKING_MAIN_DIR/${TIMESTAMP}"
LOG_DIR="$WORKING_DIR/logs"
FLASH_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/flash_events"
UNITY_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/unity"

LOG_BASELINE_DIR="$LOG_DIR/baseline"
LOG_TRAINING_DIR="$LOG_DIR/training"
LOG_PROBING_DIR="$LOG_DIR/probing"
LOG_OPENLOOP_TRAINING_DIR="$LOG_DIR/openloop_training"
LOG_CONTINUOUS_DIR="$LOG_DIR/continuous"

mkdir -p "$WORKING_DIR" "$FICTRAC_WORKING_DIR" \
         "$LOG_BASELINE_DIR" "$LOG_TRAINING_DIR" "$LOG_PROBING_DIR" "$LOG_OPENLOOP_TRAINING_DIR" "$LOG_CONTINUOUS_DIR" \
         "$FLASH_CSV_DIR" "$UNITY_CSV_DIR"

for ((i=1; i<=OPENLOOP_TRAINING_ITERATIONS; i++)); do mkdir -p "$LOG_OPENLOOP_TRAINING_DIR/iter_${i}"; done
for ((i=1; i<=BASELINE_ITERATIONS; i++)); do mkdir -p "$LOG_BASELINE_DIR/iter_${i}"; done
for ((iter=1; iter<=ITERATIONS; iter++)); do
    for ((t=1; t<=TRAINING_TRIALS_PER_ITERATION; t++)); do mkdir -p "$LOG_TRAINING_DIR/iter_${iter}_trial_${t}"; done
    for ((p=1; p<=PROBING_TRIALS_PER_ITERATION; p++)); do mkdir -p "$LOG_PROBING_DIR/iter_${iter}_trial_${p}"; done
done

SCRIPT_LOG="$LOG_DIR/run_experiment_${TIMESTAMP}.log"
PIDS=()

activate_conda() {
    echo "Activating conda environment 'daqcon'..." | tee -a "$SCRIPT_LOG"
    source ~/miniconda3/bin/activate daqcon || {
        echo "Error: Failed to activate Conda environment 'daqcon'" | tee -a "$SCRIPT_LOG"
        exit 1
    }
}

terminate_pid() {
    local pid=$1
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM -"$pid" 2>/dev/null || true
        kill -TERM "$pid" 2>/dev/null || true
    fi
}

cleanup() {
    echo "Terminating all running processes..." | tee -a "$SCRIPT_LOG"
    for pid in "${PIDS[@]}"; do
        terminate_pid "$pid"
    done
    sleep 0.5
    for pid in "${PIDS[@]}"; do
        kill -KILL -"$pid" 2>/dev/null || true
        kill -KILL "$pid" 2>/dev/null || true
    done
    echo "All processes terminated." | tee -a "$SCRIPT_LOG"
}
trap cleanup EXIT

activate_conda

# ── Pre-flight checks ──────────────────────────────────────────────
preflight_ok=1

check_file() {
    local label="$1" path="$2"
    if [[ ! -f "$path" ]]; then
        echo "[PREFLIGHT ERROR] $label not found: $path" | tee -a "$SCRIPT_LOG"
        preflight_ok=0
    fi
}

check_exe() {
    local label="$1" path="$2"
    if [[ ! -x "$path" ]]; then
        echo "[PREFLIGHT ERROR] $label not found or not executable: $path" | tee -a "$SCRIPT_LOG"
        preflight_ok=0
    fi
}

check_exe  "Unity executable"    "$UNITY_EXE"
check_file "calc_path.py"        "$calc_path_exe"
check_file "con_led.py"          "$con_led_exe"
check_file "trial_coordinator"   "$coordinator_exe"

if [[ "$USE_FICTRAC_SIM" == "1" ]]; then
    check_file "FicTrac sim stub" "$FICTRAC_SIM_EXE"
else
    check_exe  "FicTrac executable" "$FICTRAC_EXE"
    check_file "FicTrac config"     "$FICTRAC_CONFIG"
fi

if [[ "$preflight_ok" -eq 0 ]]; then
    echo "[PREFLIGHT ERROR] One or more required files are missing — aborting." | tee -a "$SCRIPT_LOG"
    exit 1
fi

# A port still bound means a process from a previous run survived; it would eat
# the packets this run expects and the session would record nothing.
echo "Checking UDP ports are free..." | tee -a "$SCRIPT_LOG"
if ! python3 "$SCRIPT_DIR/ports.py" 2>&1 | tee -a "$SCRIPT_LOG"; then
    echo "[PREFLIGHT ERROR] UDP ports unavailable — aborting." | tee -a "$SCRIPT_LOG"
    exit 1
fi

echo "Running DAQ pre-flight probe for AO channel '$AO_CHANNEL'..." | tee -a "$SCRIPT_LOG"
daq_probe_output=$(python3 "$con_led_exe" --check-daq \
    --ao-channel "$AO_CHANNEL" \
    --max-amplitude-volts-by-zone "$MAX_AMPLITUDE_VOLTS_BY_ZONE" \
    --min-amplitude-volts-by-zone "$MIN_AMPLITUDE_VOLTS_BY_ZONE" \
    --max-amplitude-volts "$MAX_AMPLITUDE_VOLTS" \
    --min-amplitude-volts "$MIN_AMPLITUDE_VOLTS" \
    --zones "$TRAINING_ZONES" \
    --decay-mode "$DECAY_MODE" 2>&1)
daq_probe_rc=$?
echo "$daq_probe_output" | tee -a "$SCRIPT_LOG"
case "$daq_probe_rc" in
    0) ;;
    2)  echo "[PREFLIGHT ERROR] con_led rejected the experiment parameters — aborting." | tee -a "$SCRIPT_LOG"
        exit 1 ;;
    *)  echo "[PREFLIGHT ERROR] DAQ/AO device unavailable for $AO_CHANNEL — aborting." | tee -a "$SCRIPT_LOG"
        exit 1 ;;
esac
echo "Pre-flight checks passed." | tee -a "$SCRIPT_LOG"
# ── End pre-flight ─────────────────────────────────────────────────

ITER_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "Starting continuous teleport-driven experiment..." | tee -a "$SCRIPT_LOG"

cd "$FICTRAC_WORKING_DIR" || exit 1
if [[ "$USE_FICTRAC_SIM" == "1" ]]; then
    python3 "$FICTRAC_SIM_EXE" >> "$LOG_CONTINUOUS_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
else
    "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$LOG_CONTINUOUS_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
fi
FICTRAC_PID=$!
PIDS+=($FICTRAC_PID)

cd "$WORKING_DIR" || exit 1
# Coordinator started first so con_led is guaranteed trial meta before the first flash fires.
# Tee coordinator stdout so iteration/trial state appears in the experiment driver log (e.g. NiceGUI).
# Coordinator exits after the last trial; we wait on it so the driver tears down Unity and other children.
python3 "$coordinator_exe" \
    --iterations "$ITERATIONS" \
    --training-trials-per-iteration "$TRAINING_TRIALS_PER_ITERATION" \
    --probing-trials-per-iteration "$PROBING_TRIALS_PER_ITERATION" \
    --openloop-training-iterations "$OPENLOOP_TRAINING_ITERATIONS" \
    --baseline-iterations "$BASELINE_ITERATIONS" \
    --openloop-zones "$OPENLOOP_ZONES" \
    --baseline-zones "$BASELINE_ZONES" \
    --training-zones "$TRAINING_ZONES" \
    --probing-zones "$PROBING_ZONES" \
    --flash-csv-dir "$FLASH_CSV_DIR" \
    --log-file "$LOG_CONTINUOUS_DIR/trial_coordinator_${ITER_TIMESTAMP}.log" \
    > >(tee -a "$LOG_CONTINUOUS_DIR/trial_coordinator_stdout_${ITER_TIMESTAMP}.log") 2>&1 &
COORDINATOR_PID=$!
PIDS+=($COORDINATOR_PID)

sleep 0.1

calc_path_cmd=(python3 "$calc_path_exe" --path-length "$PATH_LENGTH")
if [[ -n "$TRIAL_START_Z" ]]; then
    calc_path_cmd+=(--trial-start-z "$TRIAL_START_Z")
fi
"${calc_path_cmd[@]}" > >(tee -a "$LOG_CONTINUOUS_DIR/calc_path_${ITER_TIMESTAMP}.log") 2>&1 &
CALC_PATH_PID=$!
PIDS+=($CALC_PATH_PID)

python3 "$con_led_exe" \
    --zones "$TRAINING_ZONES" \
    --ao-channel "$AO_CHANNEL" \
    --max-amplitude-volts-by-zone "$MAX_AMPLITUDE_VOLTS_BY_ZONE" \
    --min-amplitude-volts-by-zone "$MIN_AMPLITUDE_VOLTS_BY_ZONE" \
    --max-amplitude-volts "$MAX_AMPLITUDE_VOLTS" \
    --min-amplitude-volts "$MIN_AMPLITUDE_VOLTS" \
    --flash-frequency-hz "$FLASH_FREQUENCY_HZ" \
    --decay-mode "$DECAY_MODE" \
    --csv-output "$FLASH_CSV_DIR/initial_training_iter_1_trial_1_${ITER_TIMESTAMP}.csv" \
    > >(tee -a "$LOG_CONTINUOUS_DIR/con_led_${ITER_TIMESTAMP}.log") 2>&1 &
CON_LED_PID=$!
PIDS+=($CON_LED_PID)

"$UNITY_EXE" --csvDirectory "$UNITY_CSV_DIR" >> "$LOG_CONTINUOUS_DIR/unity_${ITER_TIMESTAMP}.log" 2>&1 &
UNITY_PID=$!
PIDS+=($UNITY_PID)

echo "Continuous run active. Trials advance on teleport boundaries; run ends when all trials complete." | tee -a "$SCRIPT_LOG"

# ── Runtime component monitor ──────────────────────────────────────
# Components are polled rather than waited on because the run ends with the
# coordinator; any other component dying means the remaining trials would
# record data with a missing signal chain, so by default we abort.
declare -A COMPONENT_PIDS=(
    [FicTrac]="$FICTRAC_PID"
    [calc_path]="$CALC_PATH_PID"
    [con_led]="$CON_LED_PID"
    [Unity]="$UNITY_PID"
)
declare -A COMPONENT_DESC=(
    [FicTrac]="ball tracking stopped"
    [calc_path]="path integration stopped"
    [con_led]="DAQ/LED output stopped"
    [Unity]="VR rendering stopped"
)
declare -A COMPONENT_REPORTED=()

run_status=0
while kill -0 "$COORDINATOR_PID" 2>/dev/null; do
    for name in "${!COMPONENT_PIDS[@]}"; do
        [[ -n "${COMPONENT_REPORTED[$name]:-}" ]] && continue
        kill -0 "${COMPONENT_PIDS[$name]}" 2>/dev/null && continue

        COMPONENT_REPORTED[$name]=1
        wait "${COMPONENT_PIDS[$name]}" 2>/dev/null
        component_rc=$?
        echo "[COMPONENT ERROR] $name exited unexpectedly with status $component_rc (${COMPONENT_DESC[$name]})." \
            | tee -a "$SCRIPT_LOG"
        if [[ "$ABORT_ON_COMPONENT_FAILURE" == "1" ]]; then
            echo "[COMPONENT ERROR] Aborting run: remaining trials would be recorded without $name." \
                | tee -a "$SCRIPT_LOG"
            run_status=1
        fi
    done
    [[ "$run_status" -ne 0 ]] && break
    sleep 1
done

if [[ "$run_status" -eq 0 ]]; then
    wait "$COORDINATOR_PID"
    run_status=$?
    if [[ "$run_status" -ne 0 ]]; then
        echo "[COMPONENT ERROR] Trial coordinator exited with status $run_status." | tee -a "$SCRIPT_LOG"
    fi
fi
# ── End runtime monitor ────────────────────────────────────────────

exit "$run_status"
