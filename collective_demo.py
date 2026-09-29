#!/usr/bin/env python3
"""Send two five-packet collectives; delay the last packet of the second."""

import argparse
import socket
import struct
import time


def send_packet(sock, destination, port, collective_id, flow_id, participant_id):
    shim = struct.pack("!HBBBB", collective_id, flow_id, participant_id, 1, 0)
    sock.sendto(shim + b"collective-demo", (destination, port))
    print(
        f"sent collective_id={collective_id} flow={flow_id} "
        f"participant={participant_id}"
    )


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--collective-1", type=int, default=100)
parser.add_argument("--collective-2", type=int, default=101)
parser.add_argument("--flow", type=int, default=7)
parser.add_argument("--straggler-delay-ms", type=float, default=50)
parser.add_argument("--dst", default="10.0.4.4")
parser.add_argument("--port", type=int, default=9999)
args = parser.parse_args()

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    for participant_id in range(1, 6):
        send_packet(
            sock,
            args.dst,
            args.port,
            args.collective_1,
            args.flow,
            participant_id,
        )

    for participant_id in range(1, 5):
        send_packet(
            sock,
            args.dst,
            args.port,
            args.collective_2,
            args.flow,
            participant_id,
        )

    time.sleep(args.straggler_delay_ms / 1000.0)
    send_packet(
        sock,
        args.dst,
        args.port,
        args.collective_2,
        args.flow,
        5,
    )