#!/usr/bin/env python3
"""Send this worker's share of one multi-flow collective from a Mininet host."""

import argparse
import socket
import struct
import time


SHIM = struct.Struct("!HBHHBQ")
PACKET_SNAPSHOT = struct.Struct("!6s6sHBBHHHBBH4s4sHHHH")
HOP_RECORD = struct.Struct("!BBBQ")


def assigned_flows(worker_id, flow_count):
    return range(worker_id, flow_count + 1, 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", type=int, choices=range(1, 5), required=True)
    parser.add_argument("--collective-id", type=int, default=42)
    parser.add_argument("--flows", type=int, choices=(4, 5), default=5)
    parser.add_argument("--packets", type=int, default=64)
    parser.add_argument("--inter-packet-ms", type=float, default=1.0)
    parser.add_argument("--dst", default="10.0.0.5")
    parser.add_argument("--port", type=int, default=9999)
    args = parser.parse_args()

    if not 1 <= args.collective_id <= 65535:
        parser.error("--collective-id must be between 1 and 65535")
    if not 1 <= args.packets <= 65535:
        parser.error("--packets must be between 1 and 65535")
    if args.inter_packet_ms < 0:
        parser.error("--inter-packet-ms cannot be negative")

    flow_ids = list(assigned_flows(args.worker_id, args.flows))
    if not flow_ids:
        parser.error("this worker has no flows for the selected flow count")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for packet_index in range(args.packets):
            for flow_id in flow_ids:
                ecmp_path = 1 if flow_id % 2 == 0 else 2
                sent_ns = time.monotonic_ns()
                shim = SHIM.pack(
                    args.collective_id,
                    flow_id,
                    packet_index,
                    args.packets,
                    ecmp_path,
                    sent_ns,
                )
                empty_snapshot = PACKET_SNAPSHOT.pack(
                    b"\0" * 6,
                    b"\0" * 6,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    b"\0" * 4,
                    b"\0" * 4,
                    0,
                    0,
                    0,
                    0,
                )
                empty_hops = HOP_RECORD.pack(0, 0, 0, 0) * 4
                sock.sendto(
                    shim + empty_snapshot + empty_hops + b"collective-flow",
                    (args.dst, args.port),
                )
            if args.inter_packet_ms and packet_index + 1 < args.packets:
                time.sleep(args.inter_packet_ms / 1000.0)

    print(
        f"COLLECTIVE_SENT collective_id={args.collective_id} "
        f"worker={args.worker_id} flows={','.join(map(str, flow_ids))} "
        f"packets_per_flow={args.packets}"
    )


if __name__ == "__main__":
    main()
