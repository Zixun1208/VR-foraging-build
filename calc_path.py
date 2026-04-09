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
    default=100.0,
    help="Virtual corridor length in z units. z wraps forward at z0+path_length. Use <=0 to disable wrapping.",
)
args = parser.parse_args()

# UDP socket setup
recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_socket.bind(("127.0.0.1", 1317))  # Listen here
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send_addr = ("127.0.0.1", 1318)  # Send updated position here

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

# Send initial position for several seconds so Unity (starts later) receives 0,0,0
z0 = 0.01
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

# Main loop
while True:
    data, addr = recv_socket.recvfrom(1024)
    try:
        parsed_data = data.decode().strip().split(',')
        ds = float(parsed_data[6])
        df = float(parsed_data[7])
        dr = float(parsed_data[8])
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
            z = z0 + ((new_z - z0) % path_length)
        else:
            z = new_z

    # Send result
    send_data = f"{z:.1f},{x:.1f},{r:.1f}".encode()
    print(send_data.decode())  # Print output for logging
    send_socket.sendto(send_data, send_addr)
