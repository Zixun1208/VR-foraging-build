#!/usr/bin/env bash
# Rerun the analysis + deck update chain after new sessions are copied into a source folder.
# See analysis/RUN_FULL_ANALYSIS.md. Each stage is idempotent; start later with --from STAGE.
#
#   bash run_update.sh                 # all stages (~25 min)
#   bash run_update.sh --from fictrac  # skip the per-dataset pipeline
#   bash run_update.sh --from deck     # only redraw slides, render, validate
#
# Stages: pipeline -> inventory -> fictrac -> bursts -> deck -> render
set -euo pipefail

REPO=${REPO:-/home/kazama/Experiment_builds/VR-foraging-build}      # checkout whose analysis/ holds data + deck
CODE=${CODE:-$(cd "$(dirname "$0")/../../.." && pwd)}                # checkout holding this script (versioned code)
DECK=${DECK:-$REPO/analysis/reports/2026-11-09-gr64f-split-only}
SPLIT=$REPO/analysis/split_line_20261106
FT=$DECK/fictrac_speed_20261110
export MPLCONFIGDIR=${MPLCONFIGDIR:-${TMPDIR:-/tmp}/mpl-$USER}

FROM=pipeline
[[ "${1:-}" == "--from" ]] && FROM=$2
STAGES=(pipeline inventory fictrac bursts deck render)
run=0
want() { [[ $run == 1 || $1 == "$FROM" ]] && run=1; [[ $run == 1 ]]; }
say() { printf '\n=== %s ===\n' "$*"; }

# Install the versioned scripts into the (untracked) data/deck folders so every stage runs the reviewed code.
cp "$CODE"/analysis/fictrac_speed_profile/split_line/make_report.py "$SPLIT"/make_report.py
for f in fictrac_speed_profile.py trial_list.py burst_enrichment.py burst_detail.py; do
  cp "$CODE"/analysis/fictrac_speed_profile/$f "$FT"/$f
done
for f in add_reversed_sessions.py reversed_v_counts.py fictrac_slides.py burst_slides.py zone_time_slides.py validate_report.py; do
  cp "$CODE"/analysis/fictrac_speed_profile/deck/$f "$DECK"/$f
done

if want pipeline; then
  say "per-dataset pipeline: split line reward type 3 (reversed V)"
  # Add the other reward types / run sets here when they get new sessions (see RUN_FULL_ANALYSIS.md, step 2).
  (cd "$CODE" && PYTHONPATH=analysis python3 -m selected_analysis.per_dataset.pipeline \
     --raw-root "$SPLIT/source/reward type 3" --name reward_type_3 --out-root "$SPLIT/results") > "$SPLIT/type3.log" 2>&1
  grep -v -i matplotlib "$SPLIT/type3.log" | head -5
  python3 "$SPLIT"/make_report.py
fi
if want inventory; then
  say "deck inventory"
  python3 "$DECK"/add_reversed_sessions.py
fi
if want fictrac; then
  say "FicTrac speed profiles (~10 min)"
  python3 "$FT"/trial_list.py --inventory "$DECK"/session_inventory.csv --out "$FT"/trial_list.csv \
    --check "$DECK"/speed_trajectory_review/trial_audit.csv
  python3 "$FT"/fictrac_speed_profile.py --audit "$FT"/trial_list.csv --out "$FT" > "$FT"/fictrac_speed_profile.log 2>&1
  tail -3 "$FT"/fictrac_speed_profile.log
fi
if want bursts; then
  say "burst enrichment + burst detail (~8 min)"
  python3 "$FT"/burst_enrichment.py > "$FT"/burst_enrichment.log 2>&1
  python3 "$FT"/burst_detail.py > "$FT"/burst_detail/run.log 2>&1
fi
if want deck; then
  say "deck slides"
  python3 "$DECK"/fictrac_slides.py
  python3 "$DECK"/burst_slides.py
  python3 "$DECK"/zone_time_slides.py
  python3 "$DECK"/reversed_v_counts.py
fi
if want render; then
  say "render + validate"
  python3 "$DECK"/render_decks.py --deck foraging_progress_report
  python3 "$DECK"/validate_report.py > /dev/null && echo "validate_report.py: passed"
fi
