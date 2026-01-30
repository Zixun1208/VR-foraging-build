import numpy as np
import socket
import time as pytime

# Parameters
fps = 120
duration_sec = 149
total_frames = fps * duration_sec
z_start, z_end = 0.01, 99.9
x_const = 0.0

# UDP setup
send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
send_addr = ("127.0.0.1", 1318)

# Movement durations in frames
walk_duration = int(total_frames * 0.45)  # walk forward
turn_duration = int(total_frames * 0.05)  # turning
walk_back_duration = int(total_frames * 0.45)  # walk back
final_turn_duration = total_frames - (walk_duration + turn_duration + walk_back_duration)

# 1. Forward walk (r = 0)
z_forward = np.linspace(z_start, z_end, walk_duration)
r_forward = np.zeros(walk_duration)

# 2. Turn 180 (r from 0 to pi)
r_turn1 = np.linspace(0, np.pi, turn_duration)
z_turn1 = np.full(turn_duration, z_end)

# 3. Walk back (r = pi)
z_backward = np.linspace(z_end, z_start, walk_back_duration)
r_backward = np.full(walk_back_duration, np.pi)

# 4. Final turn to face forward (r from pi to 0)
r_turn2 = np.linspace(np.pi, 0, final_turn_duration)
z_turn2 = np.full(final_turn_duration, z_start)

# Combine all
z_all = np.concatenate([z_forward, z_turn1, z_backward, z_turn2])
r_all = np.concatenate([r_forward, r_turn1, r_backward, r_turn2])
x_all = np.full_like(z_all, x_const)

assert len(z_all) == total_frames

# Send coordinates via socket
for z, x, r in zip(z_all, x_all, r_all):
    msg = f"{z:.4f},{x:.4f},{r:.6f}".encode()
    send_socket.sendto(msg, send_addr)
    pytime.sleep(1 / fps)  # i added a real-time frame delay


