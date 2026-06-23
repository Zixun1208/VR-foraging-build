#!/usr/bin/env python3
"""Print raw FicTrac UDP socket packets and token offsets."""

import argparse
import socket


def main():
    parser = argparse.ArgumentParser(
        description="Listen for FicTrac UDP output and report whether packets start with FT."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local interface to bind.")
    parser.add_argument("--port", type=int, default=1317, help="Local UDP port to bind.")
    parser.add_argument("--count", type=int, default=10, help="Number of packets to print.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Socket timeout in seconds.")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(args.timeout)

    print(f"Listening on UDP {args.host}:{args.port} for {args.count} packet(s)...", flush=True)

    for packet_idx in range(1, args.count + 1):
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            print(f"Timed out after {args.timeout:g}s waiting for packet {packet_idx}.")
            break

        text = data.decode("utf-8", errors="replace").strip()
        print(f"\n--- packet {packet_idx} from {addr} ---")
        print(f"raw: {text!r}")

        for line_idx, line in enumerate(text.splitlines(), start=1):
            tokens = [token.strip() for token in line.split(",")]
            first = tokens[0] if tokens else ""
            has_ft = first.upper() == "FT"
            off = 1 if has_ft else 0

            print(
                f"line {line_idx}: token_count={len(tokens)} first={first!r} "
                f"has_ft={has_ft} off={off}"
            )
            print(f"first tokens: {tokens[:10]}")
            if len(tokens) >= off + 8:
                print(
                    "interpreted lab deltas: "
                    f"dr_lab_x={tokens[off + 5]}, "
                    f"dr_lab_y={tokens[off + 6]}, "
                    f"dr_lab_z={tokens[off + 7]}"
                )


if __name__ == "__main__":
    main()
