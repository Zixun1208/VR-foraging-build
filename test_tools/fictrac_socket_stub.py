import argparse
import math
import socket
import time


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "FicTrac replacement sender. Emits FicTrac-formatted UDP lines to calc_path "
            "so the rest of the pipeline (calc_path -> Unity -> con_led) stays intact."
        )
    )
    parser.add_argument("--ip", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1317, help="calc_path UDP input port")
    parser.add_argument("--hz", type=float, default=120.0)
    parser.add_argument("--profile", type=str, default="idle", choices=["idle", "forward", "oscillate"])
    parser.add_argument("--df", type=float, default=0.01, help="Forward increment for forward profile")
    parser.add_argument("--ds", type=float, default=0.0, help="Sideways increment for forward profile")
    parser.add_argument("--dr", type=float, default=0.0, help="Rotation increment for forward profile")
    parser.add_argument("--osc-amplitude", type=float, default=0.02)
    parser.add_argument("--osc-hz", type=float, default=0.2)
    return parser.parse_args()


def build_ft_message(frame, ds, df, dr):
    # calc_path reads frame at index 1 and ds/df/dr at indices 7/8/9 when prefixed with "FT".
    values = [
        "FT",
        str(frame),  # [1] frame
        "0",         # [2]
        "0",         # [3]
        "0",         # [4]
        "0",         # [5]
        "0",         # [6]
        f"{ds:.8f}", # [7] ds
        f"{df:.8f}", # [8] df
        f"{dr:.8f}", # [9] dr
        "0",
        "0",
        "0",
    ]
    return ",".join(values).encode("utf-8")


def profile_values(args, elapsed_sec):
    if args.profile == "idle":
        return 0.0, 0.0, 0.0
    if args.profile == "forward":
        return args.ds, args.df, args.dr
    # oscillate
    df = args.osc_amplitude * math.sin(2.0 * math.pi * args.osc_hz * elapsed_sec)
    return 0.0, df, 0.0


def main():
    args = parse_args()
    if args.hz <= 0.0:
        raise ValueError("--hz must be > 0")
    period = 1.0 / args.hz

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addr = (args.ip, args.port)
    frame = 0
    start = time.monotonic()
    next_send = start

    print(
        f"FicTrac stub sending to {args.ip}:{args.port} "
        f"at {args.hz:.1f} Hz (profile={args.profile})",
        flush=True,
    )

    while True:
        now = time.monotonic()
        if now < next_send:
            time.sleep(min(0.0005, next_send - now))
            continue

        elapsed = now - start
        ds, df, dr = profile_values(args, elapsed)
        message = build_ft_message(frame, ds, df, dr)
        sock.sendto(message, addr)
        frame += 1
        next_send += period
        if now - next_send > period:
            # Prevent drift explosion after scheduling stalls.
            next_send = now + period


if __name__ == "__main__":
    main()
