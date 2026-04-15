import csv
import json
import os

import numpy as np
import socket
import time as _time
import argparse
from numba import jit

TRIAL_META_PORT = 1322

# Args
parser = argparse.ArgumentParser(description="Integrate FicTrac motion and stream pose to Unity over UDP.")
parser.add_argument(
    "--path-length",
    type=float,
    default=100.0,
    help="Virtual corridor length in z units. z wraps forward at z0+path_length. Use <=0 to disable wrapping.",
)
parser.add_argument(
    "--boundary-ip",
    type=str,
    default="127.0.0.1",
    help="UDP IP used to publish teleport boundary events.",
)
parser.add_argument(
    "--boundary-port",
    type=int,
    default=1321,
    help="UDP port used to publish teleport boundary events.",
)
parser.add_argument(
    "--trial-start-z",
    type=float,
    default=0.01,
    help="Starting z position used at startup and after each wrap/teleport.",
)
args = parser.parse_args()

# UDP socket setup
recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_socket.bind(("127.0.0.1", 1317))  # Listen here
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send_addr = ("127.0.0.1", 1318)  # Send updated position here
boundary_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
boundary_addr = (args.boundary_ip, args.boundary_port)

trial_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
trial_sock.bind(("127.0.0.1", TRIAL_META_PORT))
trial_sock.setblocking(False)

# JIT-optimized function to convert local movement to global dx, dz
@jit(nopython=True)
def calculate_dx_dz(ds, df, r, ds_gain, df_gain):
    local_x = ds_gain * ds
    local_z = df_gain * df
    cos_r = np.cos(r)
    sin_r = np.sin(r)
    dx = local_x * cos_r - local_z * sin_r
    dz = local_x * sin_r + local_z * cos_r
    return dx, dz

# Initial position and heading
x, z, r = 0.0, 0.0, 0.0

# Gains
gain_ds = 1.0
gain_df = 1.0
gain_dr = 1.0
gain_dx = 0.0
gain_dz = 3.9
gain_r = 0.0

# Send initial position for several seconds so Unity (starts later) receives the trial start position.
z0 = float(args.trial_start_z)
path_length = float(args.path_length)
init_z = z0
recv_socket.settimeout(0.02)
t0 = _time.monotonic()
while _time.monotonic() - t0 < 3.0:
    try:
        recv_socket.recvfrom(1024)
    except socket.timeout:
        pass
    send_socket.sendto(f"{init_z:.1f},{x:.1f},{r:.1f}".encode(), send_addr)
    _time.sleep(1 / 60.0)
recv_socket.settimeout(None)
z = init_z
teleport_count = 0

path_file = None
path_writer = None
last_trial_key = None
trial_start_wall_time = _time.time()


def _close_path_csv():
    global path_file, path_writer
    if path_file is not None:
        path_file.close()
        path_file = None
        path_writer = None


def _open_path_csv(path: str):
    global path_file, path_writer
    _close_path_csv()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    path_file = open(path, "w", newline="", encoding="utf-8")
    path_writer = csv.writer(path_file)
    path_writer.writerow(["t_sec", "z", "x", "r"])


def _drain_trial_meta():
    global last_trial_key, trial_start_wall_time
    try:
        while True:
            data, _ = trial_sock.recvfrom(8192)
            meta = json.loads(data.decode("utf-8"))
            if meta.get("event") != "active_trial":
                continue
            key = (
                str(meta.get("phase", "")),
                int(meta.get("iteration", 0)),
                int(meta.get("trial", 0)),
                int(meta.get("global_trial_index", 0)),
            )
            if key == last_trial_key:
                continue
            last_trial_key = key
            trial_start_wall_time = float(meta.get("trial_start_wall_time", _time.time()))
            out_path = meta.get("path_csv_output")
            if out_path:
                _open_path_csv(out_path)
    except BlockingIOError:
        pass


# Wait for first trial metadata so path CSV path matches coordinator flash naming.
while last_trial_key is None:
    _drain_trial_meta()
    if last_trial_key is None:
        _time.sleep(0.01)

# Main loop
while True:
    data, addr = recv_socket.recvfrom(1024)
    frame_count = None
    try:
        parsed_data = [p.strip() for p in data.decode().strip().split(",")]
        # FicTrac socket lines are "FT, <csv...>" (see Trackball.cpp addMsg).
        off = 1 if parsed_data and parsed_data[0].upper() == "FT" else 0
        frame_count = int(float(parsed_data[off]))
        ds = float(parsed_data[off + 6])
        df = float(parsed_data[off + 7])
        dr = float(parsed_data[off + 8])
    except (ValueError, IndexError):
        continue

    # Update step rotation angle
    r_step = gain_dr * dr
    # Update r
    r = gain_r * r_step + r

    # Transform movement
    dx, dz = calculate_dx_dz(ds, df, r, gain_ds, gain_df)

    # Update z (floor only; wrap forward at end of corridor)
    new_z = z + gain_dz * dz
    if new_z < z0:
        z = z0
    else:
        if path_length > 0:
            did_wrap = (new_z - z0) >= path_length
            z = z0 + ((new_z - z0) % path_length)
            if did_wrap:
                teleport_count += 1
                boundary_message = {
                    "event": "teleport_boundary",
                    "teleport_count": teleport_count,
                    "frame_count": frame_count,
                    "wall_time": _time.time(),
                }
                boundary_socket.sendto(
                    json.dumps(boundary_message).encode("utf-8"),
                    boundary_addr,
                )
        else:
            z = new_z

    _drain_trial_meta()
    if path_writer is not None and path_file is not None:
        t_sec = _time.time() - trial_start_wall_time
        path_writer.writerow([f"{t_sec:.9f}", f"{z:.9f}", f"{x:.9f}", f"{r:.9f}"])
        path_file.flush()

    # Send result and emit a tagged status line for GUI live position display.
    send_data = f"{z:.1f},{x:.1f},{r:.1f}".encode()
    print(f"[pos] z={z:.1f} x={x:.1f} r={r:.1f}", flush=True)
    send_socket.sendto(send_data, send_addr)
