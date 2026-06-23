#!/usr/bin/env python3
"""Standalone LED/DAQ flash test — drives AO pulses without UDP input."""

import argparse
import logging
import signal
import warnings
from time import perf_counter, sleep, time

import nidaqmx
from nidaqmx.system import System

FLASH_FREQUENCY = 50.0
FLASH_ON_DURATION_SEC = 0.001
DEFAULT_DAQ_AO_CHANNEL = "cDAQ1Mod2/ao0"

shutdown_requested = False


def request_shutdown(signum, _frame):
    global shutdown_requested
    shutdown_requested = True
    logging.info("Received signal %s. Requesting shutdown and driving output to 0V.", signum)


def write_zero(task):
    try:
        task.write(0.0)
    except Exception as exc:
        logging.warning("Failed to drive analog output to 0V: %s", exc)


def list_nidaq_hardware():
    """Print all detected NI-DAQmx devices and their channels."""
    system = System.local()
    print(f"\nNI-DAQmx driver version: {system.driver_version}")
    devices = list(system.devices)
    if not devices:
        print("No NI-DAQ devices detected.")
        return

    print(f"\nFound {len(devices)} device(s):\n")
    for dev in devices:
        print(f"  {dev.name}")
        print(f"    Product type : {dev.product_type}")
        print(f"    Serial number: {dev.serial_num}")
        ai = [c.name for c in dev.ai_physical_chans]
        ao = [c.name for c in dev.ao_physical_chans]
        di = [l.name for l in dev.di_lines]
        do = [l.name for l in dev.do_lines]
        if ai:
            print(f"    AI channels  : {', '.join(ai)}")
        if ao:
            print(f"    AO channels  : {', '.join(ao)}")
        if di:
            print(f"    DI lines     : {', '.join(di)}")
        if do:
            print(f"    DO lines     : {', '.join(do)}")
        print()


def get_available_ao_channels():
    channels = []
    try:
        system = System.local()
        for device in system.devices:
            for ao_chan in device.ao_physical_chans:
                channels.append(ao_chan.name)
    except Exception as exc:
        logging.warning("Unable to query NI-DAQmx AO channels: %s", exc)
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
        fallback = available_channels[0]
        logging.warning(
            "Requested AO channel '%s' not found. Falling back to '%s'.",
            requested_channel,
            fallback,
        )
        return fallback
    raise RuntimeError(
        "No NI-DAQmx AO channels detected. Ensure the AO module is powered, seated, "
        "and visible in NI-DAQmx before starting."
    )


def run_flash_test(
    ao_channel,
    amplitude_volts,
    flash_freq_hz,
    duration_sec,
):
    flash_period_sec = 1.0 / flash_freq_hz
    resolved_channel = resolve_ao_channel(ao_channel)
    end_time = time() + duration_sec if duration_sec > 0 else None
    pulse_count = 0

    logging.info(
        "Starting flash test: channel=%s, amplitude=%.3f V, freq=%.1f Hz, "
        "pulse width=%.4f s%s",
        resolved_channel,
        amplitude_volts,
        flash_freq_hz,
        FLASH_ON_DURATION_SEC,
        f", duration={duration_sec:.1f} s" if duration_sec > 0 else " (run until Ctrl+C)",
    )

    with nidaqmx.Task() as task:
        task.ao_channels.add_ao_voltage_chan(
            resolved_channel,
            min_val=0.0,
            max_val=max(amplitude_volts, 5.0),
        )
        task.start()
        write_zero(task)

        try:
            next_flash_time = time()
            while not shutdown_requested:
                now = time()
                if end_time is not None and now >= end_time:
                    break

                if now >= next_flash_time:
                    task.write(float(amplitude_volts))
                    pulse_deadline = perf_counter() + FLASH_ON_DURATION_SEC
                    while perf_counter() < pulse_deadline:
                        pass
                    task.write(0.0)
                    pulse_count += 1
                    next_flash_time = now + flash_period_sec

                sleep(0)
        finally:
            write_zero(task)
            task.stop()

    logging.info("Flash test finished. Total pulses emitted: %d", pulse_count)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous DAQ flash test — lists hardware and drives AO pulses."
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="List NI-DAQ hardware and exit without flashing.",
    )
    parser.add_argument(
        "--ao-channel",
        type=str,
        default=DEFAULT_DAQ_AO_CHANNEL,
        help="DAQ analog output channel.",
    )
    parser.add_argument(
        "--amplitude-volts",
        type=float,
        default=5.0,
        help="Pulse amplitude in volts.",
    )
    parser.add_argument(
        "--flash-frequency-hz",
        type=float,
        default=FLASH_FREQUENCY,
        help="Pulse frequency in Hz.",
    )
    parser.add_argument(
        "--duration-sec",
        type=float,
        default=0.0,
        help="How long to flash (0 = run until Ctrl+C).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    warnings.filterwarnings("ignore", category=UserWarning, module="nidaqmx")

    list_nidaq_hardware()

    if args.list_only:
        return

    if args.amplitude_volts <= 0.0:
        raise ValueError("--amplitude-volts must be > 0")
    if args.flash_frequency_hz <= 0.0:
        raise ValueError("--flash-frequency-hz must be > 0")

    run_flash_test(
        ao_channel=args.ao_channel,
        amplitude_volts=args.amplitude_volts,
        flash_freq_hz=args.flash_frequency_hz,
        duration_sec=args.duration_sec,
    )


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    main()
