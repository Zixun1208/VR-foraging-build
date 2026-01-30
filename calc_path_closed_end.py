import numpy as np
import socket
from numba import jit

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
gain_r = 1.0

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
    # dx, dz = calculate_dx_dz(ds, df, r_step, gain_ds, gain_df)

    # Update z with clamp
    new_z = z + gain_dz * dz
    if new_z > 99.9:
        z = 99.9
    elif new_z < 0.01:
        z = 0.01
    else:
        z = new_z

    # Send result
    send_data = f"{z:.1f},{x:.1f},{r:.1f}".encode()
    print(send_data.decode())  # Print output for logging
    send_socket.sendto(send_data, send_addr)

