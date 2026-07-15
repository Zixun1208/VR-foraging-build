import argparse
import json
import select
import socket

import numpy as np
from numba import jit

# Args
parser = argparse.ArgumentParser(description="Integrate FicTrac motion and stream pose to Unity over UDP.")
parser.add_argument(
    "--x-min",
    type=float,
    default=-100.0,
    help="Lower bound for x. Position is clamped so x never goes below this value.",
)
parser.add_argument(
    "--x-max",
    type=float,
    default=100.0,
    help="Upper bound for x. Position is clamped so x never goes above this value.",
)
parser.add_argument(
    "--z-min",
    type=float,
    default=-100.0,
    help="Lower bound for z. Position is clamped so z never goes below this value.",
)
parser.add_argument(
    "--z-max",
    type=float,
    default=100.0,
    help="Upper bound for z. Position is clamped so z never goes above this value.",
)
parser.add_argument(
    "--trial-start-x",
    type=float,
    default=0.0,
    help="Starting x position used at startup and after each trial reset.",
)
parser.add_argument(
    "--trial-start-z",
    type=float,
    default=0.0,
    help="Starting z position used at startup and after each trial reset.",
)
parser.add_argument(
    "--trial-meta-port",
    type=int,
    default=1321,
    help="UDP port for trial_coordinator active_trial metadata (calc_path only).",
)
# Deprecated/ignored: kept so existing launchers passing these flags still run.
parser.add_argument("--path-length", type=float, default=0.0, help=argparse.SUPPRESS)
parser.add_argument("--boundary-ip", type=str, default="127.0.0.1", help=argparse.SUPPRESS)
parser.add_argument("--boundary-port", type=int, default=1321, help=argparse.SUPPRESS)
args = parser.parse_args()

# UDP socket setup
recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_socket.bind(("127.0.0.1", 1317))  # Listen here
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send_addr = ("127.0.0.1", 1318)  # Send updated position here

trial_meta_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
trial_meta_sock.bind(("127.0.0.1", args.trial_meta_port))
trial_meta_sock.setblocking(False)


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


# 2D Gains
gain_ds = 1.5
gain_df = 1.5
gain_dr = 0.5
gain_dx = 8.0
gain_dz = 8.0
gain_r = 0.5   

# Coordinate bounds (absolute world frame). Position is clamped to these.
x_min = float(args.x_min)
x_max = float(args.x_max)
z_min = float(args.z_min)
z_max = float(args.z_max)

# Initial position and heading, clamped into bounds.
x0 = min(max(float(args.trial_start_x), x_min), x_max)
z0 = min(max(float(args.trial_start_z), z_min), z_max)
x, z, r = x0, z0, 0.0
last_global_trial_index = None

# Unity is started last and may not yet be bound to the receive port; the main
# loop below will keep streaming the start pose every FicTrac frame while the fly
# is still, so Unity latches onto it as soon as it comes up.
print(
    f"[calc_path] start=({x0:.3f}, {z0:.3f}), "
    f"x_bounds=[{x_min:.3f}, {x_max:.3f}], z_bounds=[{z_min:.3f}, {z_max:.3f}]",
    flush=True,
)


def drain_trial_meta():
    """Reset pose to start when trial_coordinator advances global_trial_index."""
    global x, z, r, last_global_trial_index
    while True:
        try:
            data, _addr = trial_meta_sock.recvfrom(8192)
        except BlockingIOError:
            break
        try:
            meta = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if meta.get("event") != "active_trial":
            continue
        try:
            idx = int(meta.get("global_trial_index", 0))
        except (TypeError, ValueError):
            continue
        if last_global_trial_index is None:
            last_global_trial_index = idx
            continue
        if idx != last_global_trial_index:
            x, z, r = x0, z0, 0.0
            last_global_trial_index = idx
            print(f"[calc_path] trial reset -> ({x0:.3f}, {z0:.3f}), r=0", flush=True)


def send_pose():
    send_data = f"{z:.1f},{x:.1f},{r:.1f}".encode()
    print(f"[pos] z={z:.1f} x={x:.1f} r={r:.1f}", flush=True)
    send_socket.sendto(send_data, send_addr)


# Main loop
while True:
    drain_trial_meta()

    ready, _, _ = select.select([recv_socket], [], [], 0.05)
    if not ready:
        continue

    data, addr = recv_socket.recvfrom(1024)
    try:
        parsed_data = [p.strip() for p in data.decode().strip().split(",")]
        # FicTrac socket lines are "FT, <csv...>" (see Trackball.cpp addMsg).
        off = 1 if parsed_data and parsed_data[0].upper() == "FT" else 0
        # FicTrac columns 6-8 are delta rotation vector (lab): x, y, z.
        # Its own trackball integration maps y to forward motion and z to heading.
        ds = -float(parsed_data[off + 5])
        df = float(parsed_data[off + 6])
        dr = float(parsed_data[off + 7])
    except (ValueError, IndexError):
        continue

    # Update step rotation angle
    r_step = gain_dr * dr
    # Update r
    r = gain_r * r_step + r

    # Transform movement
    dx, dz = calculate_dx_dz(ds, df, r, gain_ds, gain_df)

    # Integrate both axes, then clamp to absolute bounds (no wrapping/teleport).
    new_x = x + gain_dx * dx
    new_z = z + gain_dz * dz
    x = min(max(new_x, x_min), x_max)
    z = min(max(new_z, z_min), z_max)

    send_pose()
