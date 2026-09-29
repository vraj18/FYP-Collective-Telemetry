#!/usr/bin/env python3
"""
Send one UDP packet containing the 5-byte collective context shim.

Run this from a Mininet host namespace, for example:
    h1 python3 sender.py --participant 1 --context 1
"""

import argparse
import socket
import struct
import time

parser = argparse.ArgumentParser()
parser.add_argument("--participant", type=int, required=True)
parser.add_argument("--collective-id", "--context", dest="collective_id", type=int, default=1)
parser.add_argument("--flow", type=int, default=1)
parser.add_argument("--total-flows", type=int, default=1)
parser.add_argument("--dst", default="10.0.4.4")
parser.add_argument("--port", type=int, default=9999)
parser.add_argument("--payload", default="collective-packet")
args = parser.parse_args()

# collective_id (16 bits), flow_id (8 bits), participant_id (8 bits),
# total_flow_count (8 bits), flags (8 bits)
shim = struct.pack(
    "!HBBBB",
    args.collective_id,
    args.flow,
    args.participant,
    args.total_flows,
    0,
)

payload = shim + args.payload.encode()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(payload, (args.dst, args.port))

print(
    f"sent collective_id={args.collective_id} "
    f"flow={args.flow} "
    f"total_flows={args.total_flows} "
    f"participant={args.participant} "
    f"payload_bytes={len(payload)}"
)
