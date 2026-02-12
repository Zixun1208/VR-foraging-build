#!/bin/bash

# Default values for parameters
INTER_SESSION_TIME=10
ITERATIONS=15
TRAINING_TRIALS_PER_ITERATION=1
PROBING_TRIALS_PER_ITERATION=1
OPENLOOP_TRAINING_ITERATIONS=10
OPENLOOP_TRAINING_SESSION_TIME=300
BASELINE_ITERATIONS=0
BASELINE_SESSION_TIME=300

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --iterations) ITERATIONS="$2"; shift ;;
        --training-trials-per-iteration) TRAINING_TRIALS_PER_ITERATION="$2"; shift ;;
        --probing-trials-per-iteration) PROBING_TRIALS_PER_ITERATION="$2"; shift ;;
        --inter-session-time) INTER_SESSION_TIME="$2"; shift ;;
        --baseline-session-time) BASELINE_SESSION_TIME="$2"; shift ;;
        --baseline-iterations) BASELINE_ITERATIONS="$2"; shift ;;
        --openloop-training-session-time) OPENLOOP_TRAINING_SESSION_TIME="$2"; shift ;;
        --openloop-training-iterations) OPENLOOP_TRAINING_ITERATIONS="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done


# Timestamp for log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE=$(date)

# Environment override-able paths
UNITY_EXE="${UNITY_EXE:-/home/kazama/Unity_Builds/turning_foraging/turning_foraging.x86_64}"
FICTRAC_EXE="${FICTRAC_EXE:-/home/kazama/fictrac/bin/fictrac}"
FICTRAC_CONFIG="${FICTRAC_CONFIG:-/home/kazama/fictrac/fictrac_config/config.txt}"
calc_path_exe="${CALC_PATH:-/home/kazama/Experiment_builds/turning_foraging/calc_path_closed_end.py}"
con_led_exe="${CON_LED:-/home/kazama/Experiment_builds/turning_foraging/con_led.py}"
openloop_sim_exe="${OPENLOOP_SIM:-/home/kazama/Experiment_builds/openloop_sim.py}"
WORKING_MAIN_DIR="${WORKING_DIR:-/home/kazama/Experiment_log/foraging}"
RAW_CSV_MAIN_DIR="${CSV_MAIN_DIR:-/home/kazama/Raw_data/foraging}"
FICTRAC_WORKING_MAIN_DIR="${FICTRAC_WORKING_DIR:-/home/kazama/fictrac/foraging}"

# Directories
WORKING_DIR="$WORKING_MAIN_DIR/${TIMESTAMP}"
FICTRAC_WORKING_DIR="$FICTRAC_WORKING_MAIN_DIR/${TIMESTAMP}"
LOG_DIR="$WORKING_DIR/logs"
BASELINE_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/baseline"
TRAINING_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/training"
PROBING_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/probing"
OPENLOOP_TRAINING_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/openloop_training"

mkdir -p "$LOG_DIR" "$WORKING_DIR" "$FICTRAC_WORKING_DIR" \
         "$BASELINE_CSV_DIR" "$TRAINING_CSV_DIR" "$PROBING_CSV_DIR" "$OPENLOOP_TRAINING_CSV_DIR"

# Log file paths
SCRIPT_LOG="$LOG_DIR/run_experiment_${TIMESTAMP}.log"
CALC_PATH_LOG="$LOG_DIR/calc_path_${TIMESTAMP}.log"
CON_LED_LOG="$LOG_DIR/con_led_${TIMESTAMP}.log"
FICTRAC_LOG="$LOG_DIR/fictrac_${TIMESTAMP}.log"
UNITY_BASELINE_LOG="$LOG_DIR/unity_baseline_${TIMESTAMP}.log"
UNITY_TRAINING_LOG="$LOG_DIR/unity_training_${TIMESTAMP}.log"
UNITY_PROBING_LOG="$LOG_DIR/unity_probing_${TIMESTAMP}.log"
OPENLOOP_SIM_LOG="$LOG_DIR/openloop_sim_${TIMESTAMP}.log"
UNITY_OPENLOOP_TRAINING_LOG="$LOG_DIR/unity_openloop_training_${TIMESTAMP}.log"

# Track background process IDs
PIDS=()

cleanup() {
    echo "Terminating all running processes..." | tee -a "$SCRIPT_LOG"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 -"$pid" 2>/dev/null
            kill -9 "$pid" 2>/dev/null
        fi
    done
    echo "All processes terminated." | tee -a "$SCRIPT_LOG"
}
trap cleanup EXIT

countdown() {
    local duration=$1
    local start_time=$(date +%s)
    while [ $duration -gt 0 ]; do
        local now=$(date +%s)
        local remaining=$((start_time + duration - now))
        if [ $remaining -le 0 ]; then break; fi
        echo -ne "\r⏳ Time remaining: ${remaining}s "
        sleep 1
    done
    echo -e "\r✅ Countdown finished.         "
}

stop_processes() {
    echo "Stopping all running processes..." | tee -a "$SCRIPT_LOG"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 -"$pid" 2>/dev/null
            kill -9 "$pid" 2>/dev/null
        fi
    done
    PIDS=()
    if command -v pkill &>/dev/null; then
        pkill -9 -f "calc_path" 2>/dev/null && echo "Killed orphan calc_path (port 1317)" | tee -a "$SCRIPT_LOG"
    fi
    sleep 0.5
}

activate_conda() {
    echo "Activating conda environment 'daqcon'..." | tee -a "$SCRIPT_LOG"
    source ~/miniconda3/bin/activate daqcon || {
        echo "Error: Failed to activate Conda environment 'daqcon'" | tee -a "$SCRIPT_LOG"
        exit 1
    }
}

# ----------------- OPENLOOP TRAINING ITERATIONS -----------------
if (( OPENLOOP_TRAINING_SESSION_TIME > 0 )); then
    for ((i=1; i<=OPENLOOP_TRAINING_ITERATIONS; i++)); do
        echo "Starting openloop training iteration $i of $OPENLOOP_TRAINING_ITERATIONS" | tee -a "$SCRIPT_LOG"
        activate_conda
        
        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$FICTRAC_LOG" 2>&1 &
        PIDS+=($!)
        
        echo "Running openloop_sim.py..." | tee -a "$SCRIPT_LOG"
        python3 "$openloop_sim_exe" >> "$OPENLOOP_SIM_LOG" 2>&1 &
        PIDS+=($!)
        
        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:150,1:300" >> "$CON_LED_LOG" 2>&1 &
        PIDS+=($!)
        
        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$OPENLOOP_TRAINING_CSV_DIR" >> "$UNITY_OPENLOOP_TRAINING_LOG" 2>&1 &
        PIDS+=($!)
        
        countdown "$OPENLOOP_TRAINING_SESSION_TIME"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next session..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done
fi

# ----------------- BASELINE ITERATIONS -----------------
if (( BASELINE_SESSION_TIME > 0 )); then
    for ((i=1; i<=BASELINE_ITERATIONS; i++)); do
        echo "Starting baseline iteration $i of $BASELINE_ITERATIONS" | tee -a "$SCRIPT_LOG"
        activate_conda

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$CALC_PATH_LOG" 2>&1 &
        PIDS+=($!)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:none,1:none" >> "$CON_LED_LOG" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$FICTRAC_LOG" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$BASELINE_CSV_DIR" >> "$UNITY_BASELINE_LOG" 2>&1 &
        PIDS+=($!)

        countdown "$BASELINE_SESSION_TIME"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next session..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done
fi

# ----------------- MAIN ITERATIONS (training + probing per iteration) -----------------
for ((iter=1; iter<=ITERATIONS; iter++)); do
    echo "========== Iteration $iter of $ITERATIONS ==========" | tee -a "$SCRIPT_LOG"

    # ---- Training trials in this iteration ----
    for ((t=1; t<=TRAINING_TRIALS_PER_ITERATION; t++)); do
        echo "--- Iteration $iter: Training trial $t of $TRAINING_TRIALS_PER_ITERATION ---" | tee -a "$SCRIPT_LOG"
        activate_conda

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$CALC_PATH_LOG" 2>&1 &
        CALC_PATH_PID=$!
        PIDS+=($CALC_PATH_PID)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:20,1:100" >> "$CON_LED_LOG" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$FICTRAC_LOG" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$TRAINING_CSV_DIR" >> "$UNITY_TRAINING_LOG" 2>&1 &
        PIDS+=($!)

        echo "Training trial: waiting for fly to reach end (coordination > 99)..." | tee -a "$SCRIPT_LOG"
        wait "$CALC_PATH_PID" 2>/dev/null || true
        echo "Fly reached end. Stopping trial." | tee -a "$SCRIPT_LOG"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next trial..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done

    # ---- Probing trials in this iteration ----
    for ((p=1; p<=PROBING_TRIALS_PER_ITERATION; p++)); do
        echo "--- Iteration $iter: Probing trial $p of $PROBING_TRIALS_PER_ITERATION ---" | tee -a "$SCRIPT_LOG"
        activate_conda

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$CALC_PATH_LOG" 2>&1 &
        CALC_PATH_PID=$!
        PIDS+=($CALC_PATH_PID)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:none,1:none" >> "$CON_LED_LOG" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$FICTRAC_LOG" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$PROBING_CSV_DIR" >> "$UNITY_PROBING_LOG" 2>&1 &
        PIDS+=($!)

        echo "Probing trial: waiting for fly to reach end (coordination > 99)..." | tee -a "$SCRIPT_LOG"
        wait "$CALC_PATH_PID" 2>/dev/null || true
        echo "Fly reached end. Stopping trial." | tee -a "$SCRIPT_LOG"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next trial..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done
done

echo "All iterations completed." | tee -a "$SCRIPT_LOG"
cleanup

