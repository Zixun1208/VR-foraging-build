#!/usr/bin/env python3
"""UDP wiring for the experiment pipeline.

THESE VALUES DO NOT CONTROL UNITY. They must *match* it.

The Unity end of this contract is a pair of `public int` Inspector fields on
Closed_loop_client.cs, whose effective values are serialized into every .unity
scene file (`receivePort: 1318`, `sendPort: 1319`) and then frozen into each
built player under ~/Unity_Builds. Changing a port here changes only the Python
side; the matching change requires editing the C#, every scene that serializes
those fields, and rebuilding each player that is still in use.

So treat the numbers below as a frozen wire protocol. This module exists to stop
the Python processes from disagreeing among *themselves* (1320 and 1321 were
each declared twice), and to give one authoritative place to read the wiring.
Verification that the contract still holds is run_experiment.sh's port
pre-flight, not this file.

    FicTrac        --1317-->  calc_path
    calc_path      --1318-->  Unity            (Unity: receivePort)
    Unity          --1319-->  con_led          (Unity: sendPort)
    coordinator    --1320-->  con_led          (trial metadata)
    calc_path      --1321-->  coordinator      (teleport boundary events)
"""

from __future__ import annotations

UDP_IP = "127.0.0.1"

FICTRAC_TO_CALC_PATH = 1317
CALC_PATH_TO_UNITY = 1318
UNITY_TO_CON_LED = 1319
COORDINATOR_TO_CON_LED = 1320
CALC_PATH_TO_COORDINATOR = 1321

# Ports a fresh run must be able to bind. A port still held here means a process
# from a previous run survived; it would silently swallow the packets the new
# run expects, so this is checked before launch rather than discovered as a
# session that quietly recorded nothing.
LISTEN_PORTS = {
    FICTRAC_TO_CALC_PATH: "calc_path (FicTrac input)",
    UNITY_TO_CON_LED: "con_led (Unity reward cues)",
    COORDINATOR_TO_CON_LED: "con_led (trial metadata)",
    CALC_PATH_TO_COORDINATOR: "trial_coordinator (teleport boundaries)",
}


def occupied_ports() -> list[tuple[int, str]]:
    """Return [(port, owner_description)] for each listen port already in use."""
    import socket

    busy = []
    for port, owner in sorted(LISTEN_PORTS.items()):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((UDP_IP, port))
        except OSError:
            busy.append((port, owner))
        finally:
            probe.close()
    return busy


if __name__ == "__main__":
    import sys

    busy = occupied_ports()
    for port, owner in busy:
        print(f"[PREFLIGHT ERROR] UDP port {port} is already in use — expected free for {owner}.")
    if busy:
        print("[PREFLIGHT ERROR] A process from a previous run is still alive. "
              "Find it with: lsof -iUDP:" + ",".join(str(p) for p, _ in busy))
        sys.exit(1)
    print(f"[PREFLIGHT OK] UDP ports free: {', '.join(str(p) for p in sorted(LISTEN_PORTS))}")
