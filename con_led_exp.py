import nidaqmx
import socket
import logging
import warnings
import argparse
from time import sleep, time
from math import log, exp

# Constants
FLASH_FREQUENCY = 50.0  # Initial Hz
DAQ_CHANNEL = "cDAQ1Mod1/port0/line0"
UDP_IP = "127.0.0.1"
UDP_PORT = 1319
FRAME_RATE = 120.0  # Frames per second used to convert frame_count to seconds

def parse_zone_decay_rates(zones_str):
    """
    Parses a string of zone:decay_duration pairs (e.g., "0:150,1:none") into a dict.
    Each value is the time in seconds for the frequency to decay from 50Hz to 1Hz.
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
                    zone_decay_constants[int(zone)] = 0.0  # Constant frequency
                else:
                    k = log(FLASH_FREQUENCY / 1.0) / decay_time  # decay from 50Hz to 1Hz
                    zone_decay_constants[int(zone)] = k
        except ValueError:
            logging.error(f"Invalid format for '{zone_pair}'. Expected 'zone:seconds' or 'zone:none'")
    return zone_decay_constants

# Argument parser
parser = argparse.ArgumentParser(
    description="UDP to DAQ control with exponential decay for flashing frequency."
)
parser.add_argument(
    "--zones",
    type=str,
    default="0:150,1:none",
    help=("Comma-separated list of zone:decay_seconds pairs (e.g., '0:150,1:none'). "
          "Defines how long (in seconds) it takes to decay from 50Hz to 1Hz. "
          "Use 'none' to disable reward output for a zone. Use '0' to disable decay and keep constant 50Hz.")
)
args = parser.parse_args()

ZONE_DECAY_CONSTANTS = parse_zone_decay_rates(args.zones)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
warnings.filterwarnings("ignore", category=UserWarning, module="nidaqmx")

def udp_daq_control():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    sock.setblocking(False)
    logging.info(f"Socket bound on {UDP_IP}:{UDP_PORT}")
    logging.info("Waiting for a client to send any data to establish 'connection'...")

    connected = False
    while not connected:
        try:
            data, addr = sock.recvfrom(512)
            if data:
                logging.info(f"Connection established from {addr}")
                connected = True
        except BlockingIOError:
            sleep(0.01)
        except Exception as e:
            logging.warning(f"Error while waiting for connection: {e}")
            sleep(0.01)

    output_state = False
    next_flash_time = time()
    frame_count = 0
    zone = -1

    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(DAQ_CHANNEL)
        task.start()

        try:
            while True:
                try:
                    data, addr = sock.recvfrom(512)
                    message = data.decode().strip()
                    values = list(map(float, message.split(',')))
                    frame_count = int(values[0])
                    zone = int(values[1])
                except BlockingIOError:
                    sleep(0.001)
                    continue
                except (ValueError, IndexError):
                    logging.warning(f"Invalid message received: {data}")
                    continue

                current_time = time()

                if zone not in ZONE_DECAY_CONSTANTS:
                    logging.info(f"Zone {zone} not in config: setting digital output to LOW.")
                    task.write(False)
                    continue

                decay_constant = ZONE_DECAY_CONSTANTS[zone]

                if decay_constant is None:
                    logging.info(f"Zone {zone} has no reward: setting digital output to LOW.")
                    task.write(False)
                    continue

                # Convert frame count to seconds
                elapsed_time_sec = frame_count / FRAME_RATE

                if decay_constant == 0.0:
                    new_flash_freq = FLASH_FREQUENCY
                else:
                    new_flash_freq = FLASH_FREQUENCY * exp(-decay_constant * elapsed_time_sec)

                if current_time >= next_flash_time:
                    output_state = not output_state
                    logging.info(
                        f"Zone {zone}, frame {frame_count}: flashing {'HIGH' if output_state else 'LOW'} "
                        f"at {new_flash_freq:.2f} Hz (elapsed: {elapsed_time_sec:.1f}s)"
                    )
                    task.write(output_state)
                    next_flash_time = current_time + 1.0 / new_flash_freq

        except KeyboardInterrupt:
            logging.info("Interrupted by user. Setting digital output LOW and exiting.")
            task.write(False)
            sleep(2)
        finally:
            task.write(False)
            task.stop()
            sock.close()

if __name__ == "__main__":
    udp_daq_control()

