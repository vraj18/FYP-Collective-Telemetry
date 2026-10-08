#!/usr/bin/env python3
"""Collect one collective at h5 and report its network-induced straggler once."""

import argparse
import ipaddress
import json
import socket
import statistics
import struct
import sys
import time
from pathlib import Path


SHIM = struct.Struct("!HBHHBQ")
PACKET_SNAPSHOT = struct.Struct("!6s6sHBBHHHBBH4s4sHHHH")
HOP_RECORD = struct.Struct("!BBBQ")
PATH_NAMES = {1: "s1-s2-s4", 2: "s1-s3-s4"}


def mac_text(value):
    return ":".join(f"{octet:02x}" for octet in value)


def write_json_line(output, record):
    output.write(json.dumps(record, sort_keys=True) + "\n")
    output.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collective-id", type=int, default=42)
    parser.add_argument("--flows", type=int, choices=(4, 5), default=5)
    parser.add_argument("--packets", type=int, default=64)
    parser.add_argument("--threshold-ms", type=float, default=10.0)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--dst", default="10.0.0.5")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--telemetry-file", default="/tmp/collective-telemetry.jsonl")
    parser.add_argument(
        "--packet-logs",
        action="store_true",
        help="Write one JSON line per packet in addition to the switch summaries.",
    )
    args = parser.parse_args()

    if not 1 <= args.collective_id <= 65535:
        parser.error("--collective-id must be between 1 and 65535")
    if not 1 <= args.packets <= 65535:
        parser.error("--packets must be between 1 and 65535")
    if args.threshold_ms < 0 or args.timeout_s <= 0:
        parser.error("threshold must be nonnegative and timeout must be positive")

    received = {flow_id: {} for flow_id in range(1, args.flows + 1)}
    switch_samples = {}
    deadline = time.monotonic() + args.timeout_s
    minimum_length = SHIM.size + PACKET_SNAPSHOT.size + 4 * HOP_RECORD.size
    telemetry_path = Path(args.telemetry_file)
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)

    with telemetry_path.open("w", encoding="utf-8") as telemetry, socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM
    ) as sock:
        sock.bind((args.listen, args.port))
        while time.monotonic() < deadline:
            sock.settimeout(min(0.5, max(0.01, deadline - time.monotonic())))
            try:
                datagram, source = sock.recvfrom(65535)
            except socket.timeout:
                continue

            if len(datagram) < minimum_length:
                continue
            collective_id, flow_id, packet_index, packet_count, path_id, sent_ns = (
                SHIM.unpack_from(datagram)
            )
            if collective_id != args.collective_id:
                continue
            if flow_id not in received or packet_count != args.packets:
                continue
            if packet_index >= args.packets:
                continue
            expected_path = 1 if flow_id % 2 == 0 else 2
            if path_id != expected_path:
                continue

            snapshot_values = PACKET_SNAPSHOT.unpack_from(datagram, SHIM.size)
            (
                eth_dst,
                eth_src,
                ethertype,
                version_ihl,
                diffserv,
                total_len,
                identification,
                flags_offset,
                ttl,
                protocol,
                ip_checksum,
                ip_src,
                ip_dst,
                udp_src_port,
                udp_dst_port,
                udp_length,
                udp_checksum,
            ) = snapshot_values

            hop_offset = SHIM.size + PACKET_SNAPSHOT.size
            hops = []
            for hop_index in range(4):
                hop_values = HOP_RECORD.unpack_from(
                    datagram, hop_offset + hop_index * HOP_RECORD.size
                )
                switch_id, ingress_port, egress_port, ingress_timestamp = hop_values
                if switch_id:
                    hops.append(
                        {
                            "switch_id": f"s{switch_id}",
                            "ingress_port": ingress_port,
                            "egress_port": egress_port,
                            "ingress_timestamp_raw": ingress_timestamp,
                        }
                    )

            received_ns = time.monotonic_ns()
            record = {
                "event": "packet",
                "collective_id": collective_id,
                "flow_id": flow_id,
                "packet_index": packet_index,
                "packets_per_flow": packet_count,
                "ecmp_path_id": path_id,
                "switch_path": [hop["switch_id"] for hop in hops],
                "hops": hops,
                "source": {
                    "worker_id": int(source[0].rsplit(".", 1)[-1]),
                    "ip": socket.inet_ntoa(ip_src),
                    "udp_port": udp_src_port,
                    "received_from_ip": source[0],
                    "received_from_udp_port": source[1],
                    "mac": mac_text(eth_src),
                },
                "destination": {
                    "ip": socket.inet_ntoa(ip_dst),
                    "udp_port": udp_dst_port,
                    "mac": mac_text(eth_dst),
                },
                "ethernet": {"ethertype": f"0x{ethertype:04x}"},
                "ipv4": {
                    "version": version_ihl >> 4,
                    "ihl_words": version_ihl & 0x0F,
                    "diffserv": diffserv,
                    "total_length": total_len,
                    "identification": identification,
                    "flags": flags_offset >> 13,
                    "fragment_offset": flags_offset & 0x1FFF,
                    "ttl": ttl,
                    "protocol": protocol,
                    "header_checksum": f"0x{ip_checksum:04x}",
                },
                "udp": {
                    "source_port": udp_src_port,
                    "destination_port": udp_dst_port,
                    "length": udp_length,
                    "checksum_at_s1_ingress": f"0x{udp_checksum:04x}",
                    "checksum_on_wire": "0x0000",
                },
                "payload_length_bytes": len(datagram),
                "sender_timestamp_monotonic_ns": sent_ns,
                "receiver_timestamp_monotonic_ns": received_ns,
                "estimated_transit_ns": received_ns - sent_ns,
            }
            if args.packet_logs:
                write_json_line(telemetry, record)

            for hop in hops:
                switch_name = hop["switch_id"]
                if not switch_name:
                    continue
                switch_id = int(switch_name[1:])
                switch_samples.setdefault(switch_id, []).append(
                    hop["ingress_timestamp_raw"] - sent_ns
                )

            packets = received[flow_id]
            if packet_index not in packets:
                packets[packet_index] = {
                    "received_ns": received_ns,
                    "sent_ns": sent_ns,
                    "path_id": path_id,
                    "hops": hops,
                }

            if all(len(packets) == args.packets for packets in received.values()):
                break

    incomplete = {
        flow_id: args.packets - len(packets)
        for flow_id, packets in received.items()
        if len(packets) != args.packets
    }
    if incomplete:
        missing = ",".join(f"{flow}:{count}" for flow, count in incomplete.items())
        with telemetry_path.open("a", encoding="utf-8") as telemetry:
            write_json_line(
                telemetry,
                {
                    "event": "collective_incomplete",
                    "collective_id": args.collective_id,
                    "missing_packets_by_flow": {
                        str(flow): count for flow, count in incomplete.items()
                    },
                },
            )
        print(
            f"COLLECTIVE_INCOMPLETE collective_id={args.collective_id} "
            f"missing_packets_by_flow={missing} telemetry_file={telemetry_path}",
            file=sys.stderr,
        )
        return 1

    flow_stats = {}
    for flow_id, packets in received.items():
        transit_ns = [packet["received_ns"] - packet["sent_ns"] for packet in packets.values()]
        completion_ns = max(packet["received_ns"] for packet in packets.values())
        flow_stats[flow_id] = {
            "network_delay_ns": statistics.median(transit_ns),
            "completion_ns": completion_ns,
            "path_id": next(iter(packets.values()))["path_id"],
            "packet_count": len(packets),
            "switch_path": [
                hop["switch_id"] for hop in next(iter(packets.values()))["hops"]
            ],
        }

    with telemetry_path.open("a", encoding="utf-8") as telemetry:
        switch_summary = []
        for switch_id in sorted(switch_samples):
            values = sorted(switch_samples[switch_id])
            switch_summary.append(
                {
                    "switch_id": f"s{switch_id}",
                    "sample_count": len(values),
                    "avg_arrival_ns": statistics.mean(values),
                    "median_arrival_ns": statistics.median(values),
                    "min_arrival_ns": values[0],
                    "max_arrival_ns": values[-1],
                }
            )
        write_json_line(
            telemetry,
            {
                "event": "switch_summary",
                "switches": switch_summary,
                "aggregate_window_packets": sum(len(v) for v in switch_samples.values()),
            },
        )

    network_straggler = max(flow_stats, key=lambda flow: flow_stats[flow]["network_delay_ns"])
    latest_flow = max(flow_stats, key=lambda flow: flow_stats[flow]["completion_ns"])
    delays_ns = [stats["network_delay_ns"] for stats in flow_stats.values()]
    delay_gap_ns = flow_stats[network_straggler]["network_delay_ns"] - statistics.median(delays_ns)
    completion_times = [stats["completion_ns"] for stats in flow_stats.values()]
    completion_skew_ns = max(completion_times) - min(completion_times)
    classification = (
        "NETWORK_INDUCED_STRAGGLER"
        if delay_gap_ns > args.threshold_ms * 1_000_000
        else "NO_NETWORK_INDUCED_STRAGGLER"
    )
    path_id = flow_stats[network_straggler]["path_id"]

    summary = {
        "event": "collective_result",
        "collective_id": args.collective_id,
        "flow_count": args.flows,
        "expected_packets_per_flow": args.packets,
        "total_unique_packets": sum(len(packets) for packets in received.values()),
        "packet_count_by_flow": {
            str(flow_id): len(packets) for flow_id, packets in received.items()
        },
        "latest_flow": latest_flow,
        "network_straggler_flow": network_straggler,
        "path": PATH_NAMES[path_id],
        "switch_path": flow_stats[network_straggler]["switch_path"],
        "network_delay_ms": flow_stats[network_straggler]["network_delay_ns"] / 1_000_000,
        "delay_over_median_ms": delay_gap_ns / 1_000_000,
        "completion_skew_ms": completion_skew_ns / 1_000_000,
        "classification": classification,
    }
    with telemetry_path.open("a", encoding="utf-8") as telemetry:
        write_json_line(telemetry, summary)

    print(
        f"COLLECTIVE_RESULT collective_id={args.collective_id} flows={args.flows} "
        f"packets_per_flow={args.packets} latest_flow={latest_flow} "
        f"network_straggler_flow={network_straggler} "
        f"path={PATH_NAMES[path_id]} "
        f"network_delay_ms={flow_stats[network_straggler]['network_delay_ns'] / 1_000_000:.3f} "
        f"delay_over_median_ms={delay_gap_ns / 1_000_000:.3f} "
        f"completion_skew_ms={completion_skew_ns / 1_000_000:.3f} "
        f"classification={classification} telemetry_file={telemetry_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())