"""Marker strings shared between the experiment processes and the GUI.

run_experiment.sh and con_led.py prefix diagnostic lines with these markers;
exp_gui.py matches on them to raise notifications. Keeping them in one place
stops the producer and consumer from drifting apart. The bash script carries
literal copies — change both together.
"""

PREFLIGHT_ERROR = "[PREFLIGHT ERROR]"
PREFLIGHT_WARNING = "[PREFLIGHT WARNING]"
PREFLIGHT_OK = "[PREFLIGHT OK]"
COMPONENT_ERROR = "[COMPONENT ERROR]"
COMPONENT_WARNING = "[COMPONENT WARNING]"

ERROR_MARKERS = (PREFLIGHT_ERROR, COMPONENT_ERROR)
WARNING_MARKERS = (PREFLIGHT_WARNING, COMPONENT_WARNING)
