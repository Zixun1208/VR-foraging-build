#!/bin/bash

# Default values for parameters
INTER_SESSION_TIME=10
ITERATIONS=15
TRAINING_TRIALS_PER_ITERATION=1
PROBING_TRIALS_PER_ITERATION=1
TRAINING_SESSION_TIME=300
PROBING_SESSION_TIME=300
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
        --training-session-time) TRAINING_SESSION_TIME="$2"; shift ;;
        --probing-session-time) PROBING_SESSION_TIME="$2"; shift ;;
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
calc_path_exe="${CALC_PATH:-/home/kazama/Experiment_builds/time-based-trial-foraging/calc_path.py}"
con_led_exe="${CON_LED:-/home/kazama/Experiment_builds/turning_foraging/con_led_exp.py}"
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
FLASH_CSV_DIR="$RAW_CSV_MAIN_DIR/${TIMESTAMP}/flash_events"

# Log subdirectories mirroring raw-data layout
LOG_BASELINE_DIR="$LOG_DIR/baseline"
LOG_TRAINING_DIR="$LOG_DIR/training"
LOG_PROBING_DIR="$LOG_DIR/probing"
LOG_OPENLOOP_TRAINING_DIR="$LOG_DIR/openloop_training"

mkdir -p "$WORKING_DIR" "$FICTRAC_WORKING_DIR" \
         "$LOG_BASELINE_DIR" "$LOG_TRAINING_DIR" \
         "$LOG_PROBING_DIR" "$LOG_OPENLOOP_TRAINING_DIR" \
         "$BASELINE_CSV_DIR" "$TRAINING_CSV_DIR" "$PROBING_CSV_DIR" "$OPENLOOP_TRAINING_CSV_DIR" \
         "$FLASH_CSV_DIR"

# Main script log (session-level)
SCRIPT_LOG="$LOG_DIR/run_experiment_${TIMESTAMP}.log"

# Track background process IDs
PIDS=()

terminate_pid() {
    local pid=$1
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM -"$pid" 2>/dev/null || true
        kill -TERM "$pid" 2>/dev/null || true
    fi
}

force_kill_pid() {
    local pid=$1
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL -"$pid" 2>/dev/null || true
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

wait_for_exit() {
    local pid=$1
    local timeout=$2
    local elapsed=0
    while kill -0 "$pid" 2>/dev/null && [ "$elapsed" -lt "$timeout" ]; do
        sleep 0.1
        elapsed=$((elapsed + 1))
    done
}

terminate_all_processes() {
    local context=$1
    echo "$context" | tee -a "$SCRIPT_LOG"
    for pid in "${PIDS[@]}"; do
        terminate_pid "$pid"
    done
    for pid in "${PIDS[@]}"; do
        wait_for_exit "$pid" 30
    done
    for pid in "${PIDS[@]}"; do
        force_kill_pid "$pid"
    done
}

cleanup() {
    terminate_all_processes "Terminating all running processes..."
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
    terminate_all_processes "Stopping all running processes..."
    PIDS=()
    if command -v pkill &>/dev/null; then
        pkill -TERM -f "calc_path" 2>/dev/null || true
        sleep 0.2
        pkill -KILL -f "calc_path" 2>/dev/null || true
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

        OL_LOG_DIR="$LOG_OPENLOOP_TRAINING_DIR/iter_${i}"
        mkdir -p "$OL_LOG_DIR"
        ITER_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$OL_LOG_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)
        
        echo "Running openloop_sim.py..." | tee -a "$SCRIPT_LOG"
        python3 "$openloop_sim_exe" >> "$OL_LOG_DIR/openloop_sim_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)
        
        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:150,1:300" \
            --csv-output "$FLASH_CSV_DIR/openloop_training_iter_${i}_${ITER_TIMESTAMP}.csv" \
            >> "$OL_LOG_DIR/con_led_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)
        
        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$OPENLOOP_TRAINING_CSV_DIR" >> "$OL_LOG_DIR/unity_${ITER_TIMESTAMP}.log" 2>&1 &
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

        BL_LOG_DIR="$LOG_BASELINE_DIR/iter_${i}"
        mkdir -p "$BL_LOG_DIR"
        ITER_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$BL_LOG_DIR/calc_path_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:none,1:none" \
            --csv-output "$FLASH_CSV_DIR/baseline_iter_${i}_${ITER_TIMESTAMP}.csv" \
            >> "$BL_LOG_DIR/con_led_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$BL_LOG_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$BASELINE_CSV_DIR" >> "$BL_LOG_DIR/unity_${ITER_TIMESTAMP}.log" 2>&1 &
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

        TR_LOG_DIR="$LOG_TRAINING_DIR/iter_${iter}_trial_${t}"
        mkdir -p "$TR_LOG_DIR"
        ITER_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$TR_LOG_DIR/calc_path_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:100,1:20" \
            --csv-output "$FLASH_CSV_DIR/training_iter_${iter}_trial_${t}_${ITER_TIMESTAMP}.csv" \
            >> "$TR_LOG_DIR/con_led_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$TR_LOG_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$TRAINING_CSV_DIR" >> "$TR_LOG_DIR/unity_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        echo "Training trial: running for ${TRAINING_SESSION_TIME}s (session time)..." | tee -a "$SCRIPT_LOG"
        countdown "$TRAINING_SESSION_TIME"
        echo "Training session time elapsed. Stopping trial." | tee -a "$SCRIPT_LOG"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next trial..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done

    # ---- Probing trials in this iteration ----
    for ((p=1; p<=PROBING_TRIALS_PER_ITERATION; p++)); do
        echo "--- Iteration $iter: Probing trial $p of $PROBING_TRIALS_PER_ITERATION ---" | tee -a "$SCRIPT_LOG"
        activate_conda

        PR_LOG_DIR="$LOG_PROBING_DIR/iter_${iter}_trial_${p}"
        mkdir -p "$PR_LOG_DIR"
        ITER_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        echo "Running calc_path.py..." | tee -a "$SCRIPT_LOG"
        python3 "$calc_path_exe" >> "$PR_LOG_DIR/calc_path_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        echo "Running con_led.py..." | tee -a "$SCRIPT_LOG"
        python3 "$con_led_exe" --zones "0:none,1:none" \
            --csv-output "$FLASH_CSV_DIR/probing_iter_${iter}_trial_${p}_${ITER_TIMESTAMP}.csv" \
            >> "$PR_LOG_DIR/con_led_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$FICTRAC_WORKING_DIR" || exit 1
        "$FICTRAC_EXE" "$FICTRAC_CONFIG" >> "$PR_LOG_DIR/fictrac_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        cd "$WORKING_DIR" || exit 1
        "$UNITY_EXE" --csvDirectory "$PROBING_CSV_DIR" >> "$PR_LOG_DIR/unity_${ITER_TIMESTAMP}.log" 2>&1 &
        PIDS+=($!)

        echo "Probing trial: running for ${PROBING_SESSION_TIME}s (session time)..." | tee -a "$SCRIPT_LOG"
        countdown "$PROBING_SESSION_TIME"
        echo "Probing session time elapsed. Stopping trial." | tee -a "$SCRIPT_LOG"
        stop_processes
        echo "Waiting for $INTER_SESSION_TIME seconds before next trial..." | tee -a "$SCRIPT_LOG"
        countdown "$INTER_SESSION_TIME"
    done
done

echo "All iterations completed." | tee -a "$SCRIPT_LOG"
cleanup

