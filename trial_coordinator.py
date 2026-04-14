import argparse
import json
import os
import socket
import time


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
    parser.add_argument("--loop-sequence", action="store_true", default=False)
    return parser.parse_args()


def build_trial_sequence(args):
    trials = []
    for i in range(1, args.openloop_training_iterations + 1):
        trials.append({
            "phase": "openloop_training",
            "iteration": i,
            "trial": 1,
            "zones": args.openloop_zones,
            "flash_csv_name": f"openloop_training_iter_{i}",
        })

    for i in range(1, args.baseline_iterations + 1):
        trials.append({
            "phase": "baseline",
            "iteration": i,
            "trial": 1,
            "zones": args.baseline_zones,
            "flash_csv_name": f"baseline_iter_{i}",
        })

    for i in range(1, args.iterations + 1):
        for t in range(1, args.training_trials_per_iteration + 1):
            trials.append({
                "phase": "training",
                "iteration": i,
                "trial": t,
                "zones": args.training_zones,
                "flash_csv_name": f"training_iter_{i}_trial_{t}",
            })
        for p in range(1, args.probing_trials_per_iteration + 1):
            trials.append({
                "phase": "probing",
                "iteration": i,
                "trial": p,
                "zones": args.probing_zones,
                "flash_csv_name": f"probing_iter_{i}_trial_{p}",
            })
    return trials


def maybe_log(log_file, message):
    print(message, flush=True)
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def format_trial_status(meta, cycle=0, note=""):
    """Single-line status for human-readable logs (GUI + files)."""
    parts = [
        f"phase={meta['phase']}",
        f"iteration={meta['iteration']}",
        f"trial={meta['trial']}",
    ]
    if note:
        parts.append(note)
    return "[trial] " + ", ".join(parts)


def build_metadata(trial_spec, trial_global_index, trial_start_wall_time, teleport_count, flash_csv_dir):
    timestamp = time.strftime("%Y%m%d_%H%M%S")
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
    trials = build_trial_sequence(args)
    if not trials:
        raise ValueError("No trials configured. Increase iterations/trials in config.")

    os.makedirs(args.flash_csv_dir, exist_ok=True)
    if args.log_file:
        os.makedirs(os.path.dirname(os.path.abspath(args.log_file)), exist_ok=True)

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind((UDP_IP, BOUNDARY_PORT))
    recv_sock.setblocking(False)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_addr = (UDP_IP, TRIAL_META_PORT)

    seq_idx = 0
    cycle = 0
    teleport_count = 0
    trial_start_wall_time = time.time()
    trial_global_index = 1
    active_meta = build_metadata(
        trials[seq_idx], trial_global_index, trial_start_wall_time, teleport_count, args.flash_csv_dir
    )
    last_sent = 0.0

    maybe_log(args.log_file, f"Coordinator started with {len(trials)} trial specs.")
    maybe_log(args.log_file, format_trial_status(active_meta, cycle, note="(initial)"))

    while True:
        now = time.time()

        try:
            while True:
                data, _addr = recv_sock.recvfrom(4096)
                event = json.loads(data.decode("utf-8"))
                if event.get("event") != "teleport_boundary":
                    continue

                teleport_count = int(event.get("teleport_count", teleport_count + 1))
                seq_idx += 1
                if seq_idx >= len(trials):
                    if args.loop_sequence:
                        seq_idx = 0
                        cycle += 1
                    else:
                        seq_idx = len(trials) - 1

                trial_global_index += 1
                trial_start_wall_time = time.time()
                active_meta = build_metadata(
                    trials[seq_idx], trial_global_index, trial_start_wall_time, teleport_count, args.flash_csv_dir
                )
                active_meta["cycle"] = cycle
                send_sock.sendto(json.dumps(active_meta).encode("utf-8"), send_addr)
                last_sent = now
        except BlockingIOError:
            pass

        if (now - last_sent) >= args.meta_interval_sec:
            send_sock.sendto(json.dumps(active_meta).encode("utf-8"), send_addr)
            last_sent = now

        time.sleep(0.01)


if __name__ == "__main__":
    main()
