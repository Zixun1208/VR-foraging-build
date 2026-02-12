import numpy as np
import socket
import time
from numba import jit

# UDP socket setup
recv_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
recv_socket.bind(("127.0.0.1", 1317))  # Adjust with your port
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send_addr = ("127.0.0.1", 1318)  # Adjust with your target address

# JIT-optimized function for dx, dy calculation
@jit(nopython=True)
def calculate_dx_dy(ds, df, dr, ds_gain, df_gain, dr_gain):
    gain_ds = ds_gain * ds
    gain_df = df_gain * df
    angle = dr_gain * dr
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    dx = gain_df * cos_a - gain_ds * sin_a
    dy = gain_df * sin_a + gain_ds * cos_a
    return dx, dy


# Initialize x, y, r
x, y = 0, 0
r = 0.0
#Gain parameters
gain_ds = 2.0
gain_df = 2.0
gain_dr = 1.0

# Send initial position for several seconds so Unity (starts later) receives 0,0,0
recv_socket.settimeout(0.02)
t0 = time.monotonic()
while time.monotonic() - t0 < 3.0:
    try:
        recv_socket.recvfrom(1024)
    except socket.timeout:
        pass
    send_socket.sendto(f"{x:.1f},{y:.1f},{r:.1f}".encode(), send_addr)
    time.sleep(1 / 60.0)
recv_socket.settimeout(None)

# Main loop
while True:
    # Receive data
    data, addr = recv_socket.recvfrom(1024)  # Adjust buffer size as necessary
    try:
        # Parse incoming data assuming CSV format ("ds,df,dr")
        #ds, df, dr = map(float, data.decode().split(','))
        parsed_data = str(data).split(',')
        ds = float(parsed_data[6])
        df = float(parsed_data[7])
        dr = float(parsed_data[8])
    except ValueError:
        continue  # Skip invalid packets
    
    # Compute dx and dy using the JIT-optimized function
    dx, dy = calculate_dx_dy(ds, df, dr, gain_ds, gain_df, gain_dr)
    #print(dx, dy, dr)
    # Update x and y
    x_gain = 1
    y_gain = 0
    r_gain = 1
    x += x_gain * dx
    y += y_gain * dy
    r += r_gain * dr
    print(x,y,r)
    # Send updated x, y as CSV-formatted string
    send_data = f"{x:.1f},{y:.1f},{r:.1f}".encode()
    send_socket.sendto(send_data, send_addr)

