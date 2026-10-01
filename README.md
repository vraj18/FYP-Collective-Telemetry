# P4 Collective Flow Straggler Experiment

This BMv2/Mininet experiment models **one collective** with four or five flows. Each flow contains the same number of UDP packets. Four worker hosts (`h1`-`h4`) send through `s1`; the receiver (`h5`) is connected to `s4`.

The P4 program performs flow-affine ECMP at `s1`: even flow IDs use `s1-s2-s4`, and odd flow IDs use `s1-s3-s4`. The paths have equal hop count. The `s1-s2` link has a configured 30 ms delay to create a controlled network-induced straggler case. This is P4 ECMP, not an NCCL runtime integration.

## Topology

| Link | Delay | Ports |
| --- | ---: | --- |
| h1-h4 to s1 | 0 ms | s1 p1-p4 |
| s1-s2 | 30 ms | s1 p5, s2 p1 |
| s1-s3 | 0 ms | s1 p6, s3 p1 |
| s2-s4 | 0 ms | s2 p2, s4 p1 |
| s3-s4 | 0 ms | s3 p2, s4 p2 |
| h5-s4 | 0 ms | s4 p3 |

All hosts share `10.0.0.0/24`; the senders have a static neighbor entry for h5 so frames arrive with h5's destination MAC. `straggler.p4` is compiled once per switch ID; its fixed egress ports match this topology.

## Detection And Telemetry

The UDP-payload shim contains a collective ID, flow ID, packet index, packets-per-flow count, expected ECMP path, and sender `monotonic_ns` timestamp. It also reserves a packet-header snapshot and four switch-hop records. At s1, P4 copies the observed Ethernet, IPv4, and UDP header fields into the snapshot. Each switch fills its own record with switch ID, ingress port, egress port, and raw ingress timestamp. Telemetry travels inline with the data packet; switches do not emit per-packet logs or send a second telemetry packet.

At h5, `collective_demo.py` writes one JSON object per received packet to `/tmp/collective-telemetry.jsonl`, followed by a collective summary object. Packet records include worker/source and destination addresses, MACs, Ethernet type, IPv4 and UDP fields, flow and sequence numbers, path, per-switch ports and timestamps, and sender/receiver timing. The summary includes packet totals per flow and the straggler classification. P4 sets the UDP checksum to zero after updating telemetry; the record includes the checksum observed at s1 ingress and the transmitted zero checksum.

The receiver waits until all expected packets for every flow arrive. It reports the latest completed flow and the flow with the largest median transit delay. A network-induced straggler is declared when that flow's delay exceeds the median flow delay by more than 10 ms. One `COLLECTIVE_RESULT` line is emitted for the completed collective.

The traffic generators use equal packet counts and pacing and do not intentionally delay any flow. The 30 ms impairment is configured on a topology link, so the injected difference is in the network path. In a deployment with unsynchronized host clocks, replace the sender timestamp approach with synchronized clocks or switch ingress/egress timestamps.

## Run

From this directory:

```sh
make
make run
```

In the Mininet CLI, start the receiver first, then launch the four workers. For five flows, worker 1 sends flows 1 and 5; workers 2-4 send one flow each. The senders interleave their own flows packet-by-packet.

```text
h5 python3 collective_demo.py --collective-id 42 --flows 5 --packets 64 &
h1 python3 sender.py --worker-id 1 --collective-id 42 --flows 5 --packets 64 &
h2 python3 sender.py --worker-id 2 --collective-id 42 --flows 5 --packets 64 &
h3 python3 sender.py --worker-id 3 --collective-id 42 --flows 5 --packets 64 &
h4 python3 sender.py --worker-id 4 --collective-id 42 --flows 5 --packets 64 &
```

The receiver prints one summary similar to:

```text
COLLECTIVE_RESULT collective_id=42 flows=5 packets_per_flow=64 latest_flow=4 network_straggler_flow=4 path=s1-s2-s4 network_delay_ms=30.4 delay_over_median_ms=29.9 completion_skew_ms=30.1 classification=NETWORK_INDUCED_STRAGGLER
```

After the collective completes, inspect all packet telemetry and the final totals from the Mininet prompt:

```text
h5 cat /tmp/collective-telemetry.jsonl
```

Each line is a separate JSON object. Lines with `"event": "packet"` contain packet/header and per-switch hop data; the final `"event": "collective_result"` line contains per-flow packet counts and the detection result. To choose another file, pass `--telemetry-file /path/to/file.jsonl` to the receiver.

Use `--flows 4` on all five commands for a four-flow run. Set the same collective ID, flow count, and packet count on the receiver and every worker. Change `--threshold-ms` on the receiver to adjust the network-delay threshold. Use `make stop` to stop Mininet. The optional topology viewer is available with `python3 topology_viewer.py`.

## Scope

This is a controlled prototype of flow completion and network-path straggler detection. It uses software switches and synthetic UDP collective traffic, not NCCL packets or physical switches. The receiver's send-to-receive latency includes host scheduling and userspace receive overhead as well as network delay; the shared-clock timestamp and identical workload reduce, but do not eliminate, those effects. For production attribution, use synchronized PTP timestamps or in-band switch telemetry and integrate with the collective runtime's flow IDs and completion events.
