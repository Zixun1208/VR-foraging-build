import argparse
import csv
import os
import socket
import subprocess
import threading
import time
from math import exp, log
import shlex


DEFAULT_IP = "127.0.0.1"
DEFAULT_PORT = 1319
DEFAULT_FLASH_FREQUENCY_HZ = 50.0
DEFAULT_FLASH_ON_DURATION_SEC = 0.001


def parse_zone_decay_rates(zones_str, max_amp, min_amp):
    zone_decay_constants = {}
    for zone_pair in zones_str.split(","):
        zone_text, decay_spec = zone_pair.split(":")
        zone = int(zone_text)
        if decay_spec.lower() == "none":
            zone_decay_constants[zone] = None
            continue
        decay_time = float(decay_spec)
        if decay_time == 0.0:
            zone_decay_constants[zone] = 0.0
        else:
            zone_decay_constants[zone] = log(max_amp / min_amp) / decay_time
    return zone_decay_constants


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Standalone flash logic timing test. "
            "Consumes coordinate packets over UDP, infers active zone, "
            "and logs flash timing delay metrics to CSV."
        )
    )
    parser.add_argument("--ip", type=str, default=DEFAULT_IP)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--zones", type=str, default="0:150,1:20")
    parser.add_argument("--zone-boundary-z", type=float, default=50.0)
    parser.add_argument("--flash-frequency-hz", type=float, default=DEFAULT_FLASH_FREQUENCY_HZ)
    parser.add_argument("--flash-on-duration-sec", type=float, default=DEFAULT_FLASH_ON_DURATION_SEC)
    parser.add_argument("--max-amplitude-volts", type=float, default=5.0)
    parser.add_argument("--min-amplitude-volts", type=float, default=0.2)
    parser.add_argument("--runtime-sec", type=float, default=20.0)
    parser.add_argument("--csv-output", type=str, default="flash_logic_test.csv")
    parser.add_argument("--sleep-sec", type=float, default=0.001)
    parser.add_argument(
        "--self-stimulus",
        action="store_true",
        help="Generate alternating-zone coordinate packets to this socket.",
    )
    parser.add_argument("--self-stimulus-hz", type=float, default=120.0)
    parser.add_argument("--self-zone-hold-sec", type=float, default=3.0)
    parser.add_argument("--self-zone0-z", type=float, default=10.0)
    parser.add_argument("--self-zone1-z", type=float, default=90.0)
    parser.add_argument(
        "--unity-forward",
        action="store_true",
        help="Forward received coordinates to Unity for visual validation.",
    )
    parser.add_argument("--unity-ip", type=str, default="127.0.0.1")
    parser.add_argument("--unity-port", type=int, default=1318)
    parser.add_argument(
        "--auto-launch-unity",
        action="store_true",
        help="Launch Unity executable automatically for this test run.",
    )
    parser.add_argument(
        "--unity-exe",
        type=str,
        default="/home/kazama/Unity_Builds/foraging-no-interval/foraging-no-interval.x86_64",
        help="Unity executable path used with --auto-launch-unity.",
    )
    parser.add_argument(
        "--unity-csv-dir",
        type=str,
        default="test_tools/unity_csv",
        help="CSV directory passed to Unity when --auto-launch-unity is enabled.",
    )
    parser.add_argument(
        "--auto-launch-cmd",
        action="append",
        default=[],
        help=(
            "Additional command to launch before test loop starts. "
            "Repeat this flag for multiple commands."
        ),
    )
    parser.add_argument(
        "--auto-launch-calc-pipeline",
        action="store_true",
        help=(
            "Launch calc_path and FicTrac stub so Unity receives motion through "
            "the normal pipeline (1317 -> calc_path -> 1318)."
        ),
    )
    parser.add_argument(
        "--calc-path-cmd",
        type=str,
        default="python3 calc_path.py --path-length 130",
        help="Command used to launch calc_path with --auto-launch-calc-pipeline.",
    )
    parser.add_argument(
        "--fictrac-stub-cmd",
        type=str,
        default="python3 test_tools/fictrac_socket_stub.py --profile forward --hz 120 --df 0.03",
        help="Command used to launch FicTrac stub with --auto-launch-calc-pipeline.",
    )
    return parser.parse_args()


def start_self_stimulus(args, stop_event):
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (args.ip, args.port)
    period = 1.0 / args.self_stimulus_hz
    switch_period = args.self_zone_hold_sec
    next_switch = time.monotonic() + switch_period
    zone = 0
    while not stop_event.is_set():
        now = time.monotonic()
        if now >= next_switch:
            zone = 1 - zone
            next_switch = now + switch_period
        z = args.self_zone0_z if zone == 0 else args.self_zone1_z
        payload = f"{z:.4f},0.0,0.0".encode("utf-8")
        send_sock.sendto(payload, addr)
        time.sleep(period)
    send_sock.close()


def launch_process(command, name):
    print(f"Launching {name}: {command}")
    return subprocess.Popen(
        shlex.split(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def terminate_process(proc, name):
    if proc.poll() is not None:
        return
    print(f"Stopping {name} (pid={proc.pid})")
    try:
        os.killpg(proc.pid, 15)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            return
    try:
        proc.wait(timeout=3.0)
    except Exception:
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main():
    args = parse_args()
    if args.min_amplitude_volts <= 0.0:
        raise ValueError("--min-amplitude-volts must be > 0")
    if args.max_amplitude_volts <= args.min_amplitude_volts:
        raise ValueError("--max-amplitude-volts must be greater than --min-amplitude-volts")
    if args.flash_frequency_hz <= 0.0:
        raise ValueError("--flash-frequency-hz must be > 0")

    zone_decay_constants = parse_zone_decay_rates(
        args.zones, args.max_amplitude_volts, args.min_amplitude_volts
    )
    flash_period_sec = 1.0 / args.flash_frequency_hz

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.ip, args.port))
    sock.setblocking(False)
    print(f"Listening on {args.ip}:{args.port}")
    print(f"Zones decay map: {zone_decay_constants}")

    unity_sock = None
    unity_addr = None
    if args.unity_forward:
        unity_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        unity_addr = (args.unity_ip, args.unity_port)
        print(f"Unity forwarding enabled -> {args.unity_ip}:{args.unity_port}")

    launched_processes = []
    if args.auto_launch_unity:
        os.makedirs(args.unity_csv_dir, exist_ok=True)
        unity_cmd = f"{args.unity_exe} --csvDirectory {args.unity_csv_dir}"
        unity_proc = launch_process(unity_cmd, "unity")
        launched_processes.append((unity_proc, "unity"))
        time.sleep(0.5)

    if args.auto_launch_calc_pipeline:
        calc_proc = launch_process(args.calc_path_cmd, "calc_path")
        launched_processes.append((calc_proc, "calc_path"))
        time.sleep(0.2)
        stub_proc = launch_process(args.fictrac_stub_cmd, "fictrac_stub")
        launched_processes.append((stub_proc, "fictrac_stub"))
        time.sleep(0.2)

    for idx, cmd in enumerate(args.auto_launch_cmd):
        proc = launch_process(cmd, f"extra_cmd_{idx + 1}")
        launched_processes.append((proc, f"extra_cmd_{idx + 1}"))
        time.sleep(0.1)

    stop_event = threading.Event()
    stimulus_thread = None
    if args.self_stimulus:
        stimulus_thread = threading.Thread(
            target=start_self_stimulus, args=(args, stop_event), daemon=True
        )
        stimulus_thread.start()
        print("Self stimulus enabled: alternating packet stream across both zones.")

    with open(args.csv_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "wall_timestamp",
                "zone",
                "elapsed_time_sec",
                "amplitude_volts",
                "scheduled_flash_time",
                "actual_flash_time",
                "flash_delay_ms",
                "period_ms",
                "period_error_ms",
            ]
        )

        trial_start_wall_time = time.time()
        output_state = False
        pulse_end_time = None
        next_flash_time = trial_start_wall_time
        last_flash_time = None
        zone = -1
        first_packet_seen = False

        delay_values_ms = []
        period_error_ms_values = []
        emitted_flashes = 0
        loop_start = time.time()

        try:
            while (time.time() - loop_start) < args.runtime_sec:
                now = time.time()

                try:
                    while True:
                        data, _addr = sock.recvfrom(512)
                        values = list(map(float, data.decode().strip().split(",")))
                        if len(values) < 1:
                            continue
                        z = values[0]
                        x = values[1] if len(values) > 1 else 0.0
                        r = values[2] if len(values) > 2 else 0.0
                        zone = 0 if z < args.zone_boundary_z else 1
                        if unity_sock is not None and unity_addr is not None:
                            unity_payload = f"{z:.4f},{x:.4f},{r:.6f}".encode("utf-8")
                            unity_sock.sendto(unity_payload, unity_addr)
                        if not first_packet_seen:
                            first_packet_seen = True
                            trial_start_wall_time = now
                            output_state = False
                            pulse_end_time = None
                            next_flash_time = now
                            print("First coordinate packet received; test timing window started.")
                except BlockingIOError:
                    pass
                except (ValueError, IndexError):
                    continue

                if not first_packet_seen:
                    time.sleep(args.sleep_sec)
                    continue

                if zone not in zone_decay_constants:
                    output_state = False
                    pulse_end_time = None
                    next_flash_time = now
                    time.sleep(args.sleep_sec)
                    continue

                decay_constant = zone_decay_constants[zone]
                if decay_constant is None:
                    output_state = False
                    pulse_end_time = None
                    next_flash_time = now
                    time.sleep(args.sleep_sec)
                    continue

                elapsed_time_sec = max(0.0, now - trial_start_wall_time)
                if decay_constant == 0.0:
                    amplitude = args.max_amplitude_volts
                else:
                    amplitude = args.max_amplitude_volts * exp(-decay_constant * elapsed_time_sec)
                    amplitude = max(args.min_amplitude_volts, amplitude)

                if output_state and pulse_end_time is not None and now >= pulse_end_time:
                    output_state = False
                    pulse_end_time = None

                if (not output_state) and now >= next_flash_time:
                    scheduled_flash_time = next_flash_time
                    actual_flash_time = now
                    delay_ms = (actual_flash_time - scheduled_flash_time) * 1000.0
                    delay_values_ms.append(delay_ms)

                    if last_flash_time is None:
                        period_ms = 0.0
                        period_error_ms = 0.0
                    else:
                        period_sec = actual_flash_time - last_flash_time
                        period_ms = period_sec * 1000.0
                        period_error_ms = (period_sec - flash_period_sec) * 1000.0
                        period_error_ms_values.append(period_error_ms)

                    output_state = True
                    pulse_end_time = actual_flash_time + args.flash_on_duration_sec
                    next_flash_time = actual_flash_time + flash_period_sec
                    last_flash_time = actual_flash_time
                    emitted_flashes += 1

                    writer.writerow(
                        [
                            f"{actual_flash_time:.6f}",
                            zone,
                            f"{elapsed_time_sec:.4f}",
                            f"{amplitude:.6f}",
                            f"{scheduled_flash_time:.6f}",
                            f"{actual_flash_time:.6f}",
                            f"{delay_ms:.4f}",
                            f"{period_ms:.4f}",
                            f"{period_error_ms:.4f}",
                        ]
                    )
                    f.flush()

                time.sleep(args.sleep_sec)
        finally:
            stop_event.set()
            if stimulus_thread is not None:
                stimulus_thread.join(timeout=1.0)
            sock.close()
            if unity_sock is not None:
                unity_sock.close()
            for proc, name in reversed(launched_processes):
                terminate_process(proc, name)

    if emitted_flashes == 0:
        print("No flash events emitted. Check if coordinate packets were received in valid zones.")
        return

    mean_delay = sum(delay_values_ms) / len(delay_values_ms)
    max_delay = max(delay_values_ms)
    min_delay = min(delay_values_ms)
    if period_error_ms_values:
        mean_period_error = sum(period_error_ms_values) / len(period_error_ms_values)
        max_period_error = max(period_error_ms_values)
        min_period_error = min(period_error_ms_values)
    else:
        mean_period_error = 0.0
        max_period_error = 0.0
        min_period_error = 0.0

    print(f"Flash events logged: {emitted_flashes}")
    print(f"CSV output: {args.csv_output}")
    print(
        "Delay stats (ms): "
        f"mean={mean_delay:.4f}, min={min_delay:.4f}, max={max_delay:.4f}"
    )
    print(
        "Period error stats (ms): "
        f"mean={mean_period_error:.4f}, min={min_period_error:.4f}, max={max_period_error:.4f}"
    )


if __name__ == "__main__":
    main()
