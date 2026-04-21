import json

import numpy as np
import socket
import time as _time
import argparse
from numba import jit

# Args
parser = argparse.ArgumentParser(description="Integrate FicTrac motion and stream pose to Unity over UDP.")
parser.add_argument(
    "--path-length",
    type=float,
    default=130.0,
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
    default=0.0,
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
gain_dr = 0.0
gain_dx = 0.0
gain_dz = 4.0
gain_r = 0.0

z0 = float(args.trial_start_z)
path_length = float(args.path_length)
z = (z0 % path_length) if path_length > 0 else z0
teleport_count = 0
# Unity is started last and may not yet be bound to the receive port; the main
# loop below will keep streaming (z0, 0, 0) every FicTrac frame while the fly
# is still, so Unity latches onto z0 as soon as it comes up.
print(
    f"[calc_path] trial_start_z={z0:.3f}, initial_z={z:.3f}, path_length={path_length:.3f}",
    flush=True,
)

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

    # Update z (corridor bounds are absolute: [0, path_length))
    # Only the forward edge triggers a teleport; the lower edge is clamped to 0
    # so small backwards fluctuations near the start don't wrap to path_length
    # and spuriously "restart" the trial.
    new_z = z + gain_dz * dz
    if path_length > 0:
        if new_z >= path_length:
            z = new_z % path_length
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
        elif new_z < 0.0:
            z = 0.0
        else:
            z = new_z
    else:
        z = new_z

    # Send result and emit a tagged status line for GUI live position display.
    send_data = f"{z:.1f},{x:.1f},{r:.1f}".encode()
    print(f"[pos] z={z:.1f} x={x:.1f} r={r:.1f}", flush=True)
    send_socket.sendto(send_data, send_addr)
