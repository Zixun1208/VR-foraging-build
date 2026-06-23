#!/bin/bash

ITERATIONS=15
TRAINING_TRIALS_PER_ITERATION=1
PROBING_TRIALS_PER_ITERATION=1
OPENLOOP_TRAINING_ITERATIONS=0
BASELINE_ITERATIONS=0
PATH_LENGTH=130
OPENLOOP_ZONES="0:150,1:300"
BASELINE_ZONES="0:none,1:none"
TRAINING_ZONES="0:100,1:20"
PROBING_ZONES="0:none,1:none"
AO_CHANNEL="cDAQ1Mod2/ao0"
MAX_AMPLITUDE_VOLTS_BY_ZONE="0:5.0,1:5.0"
MIN_AMPLITUDE_VOLTS_BY_ZONE="0:0.2,1:0.2"
MAX_AMPLITUDE_VOLTS=5.0
MIN_AMPLITUDE_VOLTS=0.2
FLASH_FREQUENCY_HZ=50.0
DECAY_MODE="exp"
TRIAL_START_Z=""
USE_FICTRAC_SIM=0

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

check_file "Unity executable"    "$UNITY_EXE"
check_file "calc_path.py"        "$calc_path_exe"
check_file "con_led.py"          "$con_led_exe"
check_file "trial_coordinator"   "$coordinator_exe"

if [[ "$USE_FICTRAC_SIM" == "1" ]]; then
    check_file "FicTrac sim stub" "$FICTRAC_SIM_EXE"
else
    check_file "FicTrac executable" "$FICTRAC_EXE"
    check_file "FicTrac config"     "$FICTRAC_CONFIG"
fi

if [[ "$preflight_ok" -eq 0 ]]; then
    echo "[PREFLIGHT ERROR] One or more required files are missing — aborting." | tee -a "$SCRIPT_LOG"
    exit 1
fi

echo "Running DAQ pre-flight probe for AO channel '$AO_CHANNEL'..." | tee -a "$SCRIPT_LOG"
daq_probe_output=$(python3 "$con_led_exe" --check-daq --ao-channel "$AO_CHANNEL" 2>&1)
daq_probe_rc=$?
echo "$daq_probe_output" | tee -a "$SCRIPT_LOG"
if [[ "$daq_probe_rc" -ne 0 ]]; then
    echo "[PREFLIGHT ERROR] DAQ/AO device unavailable for $AO_CHANNEL — aborting." | tee -a "$SCRIPT_LOG"
    exit 1
fi
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
WARNED_FICTRAC=0
WARNED_CALC_PATH=0
WARNED_CON_LED=0
WARNED_UNITY=0

while kill -0 "$COORDINATOR_PID" 2>/dev/null; do
    if [[ "$WARNED_FICTRAC" -eq 0 ]] && ! kill -0 "$FICTRAC_PID" 2>/dev/null; then
        echo "[COMPONENT ERROR] FicTrac exited unexpectedly (ball tracking stopped)." | tee -a "$SCRIPT_LOG"
        WARNED_FICTRAC=1
    fi
    if [[ "$WARNED_CALC_PATH" -eq 0 ]] && ! kill -0 "$CALC_PATH_PID" 2>/dev/null; then
        echo "[COMPONENT ERROR] calc_path exited unexpectedly (path integration stopped)." | tee -a "$SCRIPT_LOG"
        WARNED_CALC_PATH=1
    fi
    if [[ "$WARNED_CON_LED" -eq 0 ]] && ! kill -0 "$CON_LED_PID" 2>/dev/null; then
        echo "[COMPONENT ERROR] con_led exited unexpectedly (DAQ/LED output stopped)." | tee -a "$SCRIPT_LOG"
        WARNED_CON_LED=1
    fi
    if [[ "$WARNED_UNITY" -eq 0 ]] && ! kill -0 "$UNITY_PID" 2>/dev/null; then
        echo "[COMPONENT ERROR] Unity exited unexpectedly (VR rendering stopped)." | tee -a "$SCRIPT_LOG"
        WARNED_UNITY=1
    fi
    sleep 1
done
wait "$COORDINATOR_PID"
# ── End runtime monitor ────────────────────────────────────────────

