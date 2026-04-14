import csv
import nidaqmx
import os
import socket
import logging
import warnings
import argparse
import signal
from time import sleep, time
from math import log, exp
import json
from nidaqmx.system import System

# Constants
FLASH_FREQUENCY = 50.0
FLASH_ON_DURATION_SEC = 0.001
DEFAULT_DAQ_AO_CHANNEL = "cDAQ1Mod2/ao0"
UDP_IP = "127.0.0.1"
UDP_PORT = 1319
TRIAL_META_PORT = 1320

def parse_zone_decay_rates(zones_str, max_amp, min_amp, decay_mode):
    """
    Parses a string of zone:decay_duration pairs (e.g., "0:150,1:none") into a dict.
    Each value is the time in seconds for amplitude to decay from max_amp to min_amp.
    'none' disables reward output for that zone.
    """
    zone_decay_constants = {}
    for zone_pair in zones_str.split(','):
        try:
            zone, decay_spec = zone_pair.split(':')
            if decay_spec.lower() == 'none':
                zone_decay_constants[int(zone)] = None
            else:
                decay_time = float(decay_spec)
                if decay_time == 0.0:
                    zone_decay_constants[int(zone)] = 0.0
                else:
                    if decay_mode == "exp":
                        k = log(max_amp / min_amp) / decay_time
                        zone_decay_constants[int(zone)] = k
                    else:
                        slope = (max_amp - min_amp) / decay_time
                        zone_decay_constants[int(zone)] = slope
        except ValueError:
            logging.error(f"Invalid format for '{zone_pair}'. Expected 'zone:seconds' or 'zone:none'")
    return zone_decay_constants

# Argument parser
parser = argparse.ArgumentParser(
    description="UDP to DAQ control with fixed-frequency pulses and exponential amplitude decay."
)
parser.add_argument(
    "--zones",
    type=str,
    default="0:150,1:none",
    help=("Comma-separated list of zone:decay_seconds pairs (e.g., '0:150,1:none'). "
          "Defines how long (in seconds) it takes to decay from max amplitude to min amplitude. "
          "Use 'none' to disable reward output for a zone. Use '0' to disable decay and keep constant max amplitude.")
)
parser.add_argument(
    "--csv-output",
    type=str,
    default=None,
    help="Path to a CSV file where flash-ON events will be recorded. If omitted, no CSV is written."
)
parser.add_argument("--ao-channel", type=str, default=DEFAULT_DAQ_AO_CHANNEL, help="DAQ analog output channel.")
parser.add_argument("--max-amplitude-volts", type=float, default=5.0, help="Pulse amplitude at trial start.")
parser.add_argument("--min-amplitude-volts", type=float, default=0.2, help="Minimum pulse amplitude after decay.")
parser.add_argument("--flash-frequency-hz", type=float, default=FLASH_FREQUENCY, help="Fixed pulse frequency.")
parser.add_argument(
    "--decay-mode",
    type=str,
    default="exp",
    choices=["exp", "linear"],
    help="Decay profile for amplitude vs elapsed time in zone.",
)
args = parser.parse_args()

if args.min_amplitude_volts <= 0.0:
    raise ValueError("--min-amplitude-volts must be > 0")
if args.max_amplitude_volts <= args.min_amplitude_volts:
    raise ValueError("--max-amplitude-volts must be greater than --min-amplitude-volts")

default_zone_decay_constants = parse_zone_decay_rates(
    args.zones,
    args.max_amplitude_volts,
    args.min_amplitude_volts,
    args.decay_mode,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
warnings.filterwarnings("ignore", category=UserWarning, module="nidaqmx")

shutdown_requested = False

def request_shutdown(signum, _frame):
    global shutdown_requested
    shutdown_requested = True
    logging.info(f"Received signal {signum}. Requesting shutdown and driving output to 0V.")

def write_zero(task):
    try:
        task.write(0.0)
    except Exception as exc:
        logging.warning(f"Failed to drive analog output to 0V: {exc}")


def get_available_ao_channels():
    channels = []
    try:
        system = System.local()
        for device in system.devices:
            for ao_chan in device.ao_physical_chans:
                channels.append(ao_chan.name)
    except Exception as exc:
        logging.warning(f"Unable to query NI-DAQmx AO channels: {exc}")
    return channels


def resolve_ao_channel(requested_channel):
    available_channels = get_available_ao_channels()
    logging.info(
        "Detected AO channels: %s",
        ", ".join(available_channels) if available_channels else "(none)",
    )

    if requested_channel in available_channels:
        return requested_channel

    if available_channels:
        fallback_channel = available_channels[0]
        logging.warning(
            "Requested AO channel '%s' not found. Falling back to '%s'.",
            requested_channel,
            fallback_channel,
        )
        return fallback_channel

    raise RuntimeError(
        "No NI-DAQmx AO channels detected. Ensure the AO module is powered, seated, "
        "and visible in NI-DAQmx before starting."
    )

def reset_flash_state(current_time):
    return False, current_time, None, current_time

def open_csv(csv_output_path):
    if not csv_output_path:
        return None, None
    os.makedirs(os.path.dirname(os.path.abspath(csv_output_path)), exist_ok=True)
    csv_file = open(csv_output_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow([
        "wall_timestamp",
        "phase",
        "iteration",
        "trial",
        "global_trial_index",
        "zone",
        "elapsed_time_sec",
        "amplitude_volts",
        "flash_frequency_hz",
    ])
    logging.info(f"Flash-ON events will be recorded to: {csv_output_path}")
    return csv_file, csv_writer

def udp_daq_control():
    unity_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    unity_sock.bind((UDP_IP, UDP_PORT))
    unity_sock.setblocking(False)
    logging.info(f"Unity socket bound on {UDP_IP}:{UDP_PORT}")

    trial_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    trial_sock.bind((UDP_IP, TRIAL_META_PORT))
    trial_sock.setblocking(False)
    logging.info(f"Trial metadata socket bound on {UDP_IP}:{TRIAL_META_PORT}")

    logging.info("Waiting for UDP traffic to establish runtime state...")
    connected = False
    while not connected:
        try:
            data, addr = unity_sock.recvfrom(512)
            if data:
                logging.info(f"Unity stream established from {addr}")
                connected = True
        except BlockingIOError:
            sleep(0.01)
        except Exception as e:
            logging.warning(f"Error while waiting for connection: {e}")
            sleep(0.01)

    output_state = False
    next_flash_time = time()
    pulse_end_time = None
    zone = -1
    trial_start_wall_time = time()
    zone_elapsed_time_sec: dict[int, float] = {}
    zone_accum_last_wall_time = trial_start_wall_time
    zone_accum_last_zone: int | None = None
    active_phase = "unassigned"
    active_iteration = 0
    active_trial = 0
    active_global_trial_index = 0
    last_reset_trial_key: tuple[str, int, int, int] | None = None
    active_csv_path = args.csv_output
    zone_decay_constants = dict(default_zone_decay_constants)
    flash_period_sec = 1.0 / args.flash_frequency_hz

    csv_file, csv_writer = open_csv(active_csv_path)

    resolved_ao_channel = resolve_ao_channel(args.ao_channel)

    with nidaqmx.Task() as task:
        task.ao_channels.add_ao_voltage_chan(
            resolved_ao_channel,
            min_val=0.0,
            max_val=args.max_amplitude_volts,
        )
        task.start()
        write_zero(task)

        try:
            while not shutdown_requested:
                current_time = time()
                try:
                    while True:
                        data, addr = unity_sock.recvfrom(512)
                        message = data.decode().strip()
                        values = list(map(float, message.split(',')))
                        zone = int(values[1])
                except BlockingIOError:
                    pass
                except (ValueError, IndexError):
                    logging.warning(f"Invalid message received: {data}")
                    continue

                try:
                    while True:
                        trial_data, _ = trial_sock.recvfrom(8192)
                        meta = json.loads(trial_data.decode("utf-8"))
                        if meta.get("event") != "active_trial":
                            continue
                        new_phase = meta.get("phase", active_phase)
                        new_iteration = int(meta.get("iteration", active_iteration))
                        new_trial = int(meta.get("trial", active_trial))
                        new_global_trial_index = int(
                            meta.get("global_trial_index", active_global_trial_index)
                        )
                        new_trial_key = (
                            str(new_phase),
                            new_iteration,
                            new_trial,
                            new_global_trial_index,
                        )

                        # Coordinator rebroadcasts active trial metadata periodically.
                        # Reset decay/flash state only when trial identity actually changes.
                        is_new_trial = new_trial_key != last_reset_trial_key

                        active_phase = new_phase
                        active_iteration = new_iteration
                        active_trial = new_trial
                        active_global_trial_index = new_global_trial_index

                        if is_new_trial:
                            trial_start_wall_time = float(meta.get("trial_start_wall_time", current_time))
                            zone_elapsed_time_sec = {}
                            zone_accum_last_wall_time = current_time
                            zone_accum_last_zone = None
                            zone_decay_constants = parse_zone_decay_rates(
                                meta.get("zones", args.zones),
                                args.max_amplitude_volts,
                                args.min_amplitude_volts,
                                args.decay_mode,
                            )
                            output_state, next_flash_time, pulse_end_time, _ = reset_flash_state(current_time)

                            new_csv_path = meta.get("flash_csv_output", active_csv_path)
                            if new_csv_path != active_csv_path:
                                if csv_file is not None:
                                    csv_file.close()
                                active_csv_path = new_csv_path
                                csv_file, csv_writer = open_csv(active_csv_path)

                            last_reset_trial_key = new_trial_key
                            logging.info(
                                f"New trial meta: phase={active_phase}, iter={active_iteration}, trial={active_trial}"
                            )
                except BlockingIOError:
                    pass

                dt = max(0.0, current_time - zone_accum_last_wall_time)
                if zone_accum_last_zone in zone_decay_constants:
                    zone_elapsed_time_sec[zone_accum_last_zone] = (
                        zone_elapsed_time_sec.get(zone_accum_last_zone, 0.0) + dt
                    )
                zone_accum_last_wall_time = current_time
                zone_accum_last_zone = zone

                if zone not in zone_decay_constants:
                    write_zero(task)
                    output_state, next_flash_time, pulse_end_time, _ = reset_flash_state(current_time)
                    continue

                decay_constant = zone_decay_constants[zone]

                if decay_constant is None:
                    write_zero(task)
                    output_state, next_flash_time, pulse_end_time, _ = reset_flash_state(current_time)
                    continue

                elapsed_time_sec = zone_elapsed_time_sec.get(zone, 0.0)

                if decay_constant == 0.0:
                    new_amplitude = args.max_amplitude_volts
                else:
                    if args.decay_mode == "exp":
                        new_amplitude = args.max_amplitude_volts * exp(-decay_constant * elapsed_time_sec)
                    else:
                        new_amplitude = args.max_amplitude_volts - (decay_constant * elapsed_time_sec)
                    new_amplitude = max(args.min_amplitude_volts, new_amplitude)

                if output_state and pulse_end_time is not None and current_time >= pulse_end_time:
                    write_zero(task)
                    output_state = False
                    pulse_end_time = None

                if not output_state and current_time >= next_flash_time:
                    output_state = True
                    task.write(float(new_amplitude))
                    pulse_end_time = current_time + FLASH_ON_DURATION_SEC
                    next_flash_time = current_time + flash_period_sec

                    if csv_writer is not None:
                        csv_writer.writerow([
                            f"{current_time:.6f}",
                            active_phase,
                            active_iteration,
                            active_trial,
                            active_global_trial_index,
                            zone,
                            f"{elapsed_time_sec:.4f}",
                            f"{new_amplitude:.6f}",
                            f"{args.flash_frequency_hz:.4f}",
                        ])
                        csv_file.flush()

                sleep(0.001)

        except KeyboardInterrupt:
            logging.info("Interrupted by user. Setting analog output to 0V and exiting.")
            write_zero(task)
            sleep(2)
        except Exception:
            logging.exception("Unexpected error in LED controller. Driving output to 0V before exit.")
            raise
        finally:
            write_zero(task)
            task.stop()
            unity_sock.close()
            trial_sock.close()
            if csv_file is not None:
                csv_file.close()
                logging.info(f"Flash CSV closed: {active_csv_path}")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    udp_daq_control()

