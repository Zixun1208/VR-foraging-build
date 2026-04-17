import argparse
import json
import os
import socket
import time
from datetime import datetime


UDP_IP = "127.0.0.1"
BOUNDARY_PORT = 1321
TRIAL_META_PORT = 1320


def parse_args():
    parser = argparse.ArgumentParser(
        description="Advance trial state on teleport boundaries and broadcast active trial metadata."
    )
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--training-trials-per-iteration", type=int, default=1)
    parser.add_argument("--probing-trials-per-iteration", type=int, default=1)
    parser.add_argument("--openloop-training-iterations", type=int, default=0)
    parser.add_argument("--baseline-iterations", type=int, default=0)
    parser.add_argument("--openloop-zones", type=str, default="0:150,1:300")
    parser.add_argument("--baseline-zones", type=str, default="0:none,1:none")
    parser.add_argument("--training-zones", type=str, default="0:100,1:20")
    parser.add_argument("--probing-zones", type=str, default="0:none,1:none")
    parser.add_argument("--flash-csv-dir", type=str, required=True)
    parser.add_argument("--log-file", type=str, default=None)
    parser.add_argument("--meta-interval-sec", type=float, default=0.25)
    return parser.parse_args()


def main_block_has_trials(args) -> bool:
    return args.iterations > 0 and (
        args.training_trials_per_iteration > 0 or args.probing_trials_per_iteration > 0
    )


def total_scheduled_trials(args) -> int:
    n = args.openloop_training_iterations + args.baseline_iterations
    if main_block_has_trials(args):
        n += args.iterations * (
            args.training_trials_per_iteration + args.probing_trials_per_iteration
        )
    return n


class TrialSchedule:
    """Explicit schedule: open-loop / baseline iteration counts, then per-iteration training vs probing."""

    __slots__ = ("args", "block", "openloop_i", "baseline_i", "iteration", "in_training", "trial")

    def __init__(self, args):
        self.args = args
        self.block = ""
        self.openloop_i = 1
        self.baseline_i = 1
        self.iteration = 1
        self.in_training = True
        self.trial = 1
        if not self._seek_first_trial():
            raise ValueError("No trials configured. Increase iterations/trials in config.")

    def _seek_first_trial(self) -> bool:
        if self.args.openloop_training_iterations > 0:
            self.block = "openloop"
            self.openloop_i = 1
            return True
        return self._enter_baseline_or_main_after_openloop()

    def _enter_baseline_or_main_after_openloop(self) -> bool:
        if self.args.baseline_iterations > 0:
            self.block = "baseline"
            self.baseline_i = 1
            return True
        return self._enter_main_or_done()

    def _enter_main_or_done(self) -> bool:
        if not main_block_has_trials(self.args):
            return False
        self.block = "main"
        self.iteration = 1
        if self.args.training_trials_per_iteration > 0:
            self.in_training = True
            self.trial = 1
        else:
            self.in_training = False
            self.trial = 1
        return True

    def current_spec(self) -> dict:
        a = self.args
        if self.block == "openloop":
            i = self.openloop_i
            return {
                "phase": "openloop_training",
                "iteration": i,
                "trial": 1,
                "zones": a.openloop_zones,
                "flash_csv_name": f"openloop_training_iter_{i}",
            }
        if self.block == "baseline":
            i = self.baseline_i
            return {
                "phase": "baseline",
                "iteration": i,
                "trial": 1,
                "zones": a.baseline_zones,
                "flash_csv_name": f"baseline_iter_{i}",
            }
        it = self.iteration
        t = self.trial
        if self.in_training:
            return {
                "phase": "training",
                "iteration": it,
                "trial": t,
                "zones": a.training_zones,
                "flash_csv_name": f"training_iter_{it}_trial_{t}",
            }
        return {
            "phase": "probing",
            "iteration": it,
            "trial": t,
            "zones": a.probing_zones,
            "flash_csv_name": f"probing_iter_{it}_trial_{t}",
        }

    def advance_after_boundary(self) -> bool:
        """Advance to the next trial. Returns False if the schedule is finished."""
        a = self.args
        if self.block == "openloop":
            if self.openloop_i < a.openloop_training_iterations:
                self.openloop_i += 1
                return True
            if a.baseline_iterations > 0:
                self.block = "baseline"
                self.baseline_i = 1
                return True
            return self._enter_main_or_done()

        if self.block == "baseline":
            if self.baseline_i < a.baseline_iterations:
                self.baseline_i += 1
                return True
            return self._enter_main_or_done()

        if self.in_training:
            if self.trial < a.training_trials_per_iteration:
                self.trial += 1
                return True
            if a.probing_trials_per_iteration > 0:
                self.in_training = False
                self.trial = 1
                return True
            return self._advance_main_iteration()

        if self.trial < a.probing_trials_per_iteration:
            self.trial += 1
            return True
        return self._advance_main_iteration()

    def _advance_main_iteration(self) -> bool:
        a = self.args
        if self.iteration < a.iterations:
            self.iteration += 1
            if a.training_trials_per_iteration > 0:
                self.in_training = True
                self.trial = 1
            else:
                self.in_training = False
                self.trial = 1
            return True
        return False


def maybe_log(log_file, message):
    print(message, flush=True)
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def format_trial_status(meta, note=""):
    """Single-line status for human-readable logs (GUI + files)."""
    parts = [
        f"phase={meta['phase']}",
        f"iteration={meta['iteration']}",
        f"trial={meta['trial']}",
    ]
    if note:
        parts.append(note)
    return "[trial] " + ", ".join(parts)


def trial_progress_note(trial_global_index, teleport_count, initial=False):
    note = f"global_trial_index={trial_global_index}, teleport_count={teleport_count}"
    if initial:
        return f"(initial, {note})"
    return f"({note})"


def build_metadata(trial_spec, trial_global_index, trial_start_wall_time, teleport_count, flash_csv_dir, args):
    # Millisecond-precision timestamp so the flash CSV filename itself
    # uniquely identifies the trial start and can be used to slice the
    # Unity path log by [trial_start, next_trial_start) wall-time windows.
    timestamp = datetime.fromtimestamp(trial_start_wall_time).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    csv_path = os.path.join(flash_csv_dir, f"{trial_spec['flash_csv_name']}_{timestamp}.csv")
    return {
        "event": "active_trial",
        "phase": trial_spec["phase"],
        "iteration": trial_spec["iteration"],
        "trial": trial_spec["trial"],
        "global_trial_index": trial_global_index,
        "zones": trial_spec["zones"],
        "trial_start_wall_time": trial_start_wall_time,
        "teleport_count": teleport_count,
        "flash_csv_output": csv_path,
    }


def main():
    args = parse_args()
    schedule = TrialSchedule(args)
    n_trials = total_scheduled_trials(args)

    os.makedirs(args.flash_csv_dir, exist_ok=True)
    if args.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind((UDP_IP, BOUNDARY_PORT))
    recv_sock.setblocking(False)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_addr = (UDP_IP, TRIAL_META_PORT)

    teleport_count = 0
    trial_start_wall_time = time.time()
    trial_global_index = 1
    spec = schedule.current_spec()
    active_meta = build_metadata(
        spec, trial_global_index, trial_start_wall_time, teleport_count, args.flash_csv_dir, args
    )

    maybe_log(args.log_file, f"Coordinator started; {n_trials} trials scheduled.")
    maybe_log(
        args.log_file,
        format_trial_status(
            active_meta,
            note=trial_progress_note(trial_global_index, teleport_count, initial=True),
        ),
    )

    payload0 = json.dumps(active_meta).encode("utf-8")
    send_sock.sendto(payload0, send_addr)
    last_sent = time.time()

    finished = False
    while not finished:
        now = time.time()

        try:
            while True:
                data, _addr = recv_sock.recvfrom(4096)
                event = json.loads(data.decode("utf-8"))
                if event.get("event") != "teleport_boundary":
                    continue

                teleport_count = int(event.get("teleport_count", teleport_count + 1))
                if not schedule.advance_after_boundary():
                    maybe_log(
                        args.log_file,
                        f"Schedule complete after {n_trials} trials "
                        f"(final teleport_count={teleport_count}); exiting.",
                    )
                    finished = True
                    break

                trial_global_index += 1
                trial_start_wall_time = time.time()
                spec = schedule.current_spec()
                active_meta = build_metadata(
                    spec, trial_global_index, trial_start_wall_time, teleport_count, args.flash_csv_dir, args
                )
                maybe_log(
                    args.log_file,
                    format_trial_status(
                        active_meta,
                        note=trial_progress_note(trial_global_index, teleport_count),
                    ),
                )
                payload = json.dumps(active_meta).encode("utf-8")
                send_sock.sendto(payload, send_addr)
                last_sent = now
        except BlockingIOError:
            pass

        if finished:
            break

        if (now - last_sent) >= args.meta_interval_sec:
            payload = json.dumps(active_meta).encode("utf-8")
            send_sock.sendto(payload, send_addr)
            last_sent = now

        time.sleep(0.01)

    recv_sock.close()
    send_sock.close()


if __name__ == "__main__":
    main()
