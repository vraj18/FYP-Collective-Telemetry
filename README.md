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

### Packet fields

The senders create ordinary Ethernet/IPv4/UDP packets to h5 (`10.0.0.5:9999`). Immediately after the UDP header, the UDP payload begins with a fixed-format context shim, followed by telemetry space and the application payload. The P4 parser treats these payload bytes as custom headers so each switch can read and update them.

| Field | Size | Who fills it | Meaning |
| --- | ---: | --- | --- |
| Ethernet header | 14 B | Sender | Destination/source MAC addresses and EtherType. |
| IPv4 header | 20 B | Sender/host stack | Source/destination IP, protocol, length, TTL, and other IPv4 fields. |
| UDP header | 8 B | Sender/host stack | Source/destination ports, length, and checksum. |
| Collective ID | 2 B | Sender | Identifies the collective instance. |
| Flow ID | 1 B | Sender | Identifies a flow within that collective; s1 uses its low bit to select a path. |
| Packet index | 2 B | Sender | Zero-based packet number within the flow. |
| Packets per flow | 2 B | Sender | Expected packet count for that flow. |
| Path ID | 1 B | Sender | Declared expected path: 1 for even flow IDs (`s1-s2-s4`), 2 for odd IDs (`s1-s3-s4`). |
| Sender timestamp | 8 B | Sender | `time.monotonic_ns()` at send time, used by h5 for end-to-end elapsed time. |
| Original-header snapshot | 42 B | Initially zero from sender; filled by s1 | Copy of the Ethernet (14 B), IPv4 (20 B), and UDP (8 B) header fields as observed at s1 ingress. |
| Four hop records | 4 x 11 B | Initially zero from sender; one slot per switch | Each record contains switch ID (1 B), ingress port (1 B), egress port (1 B), and raw ingress timestamp (8 B). |
| Application payload | Remaining bytes | Sender | The current example appends the literal bytes `collective-flow`. |

The context shim is 16 bytes, the header snapshot is 42 bytes, and the four reserved hop records total 44 bytes. Thus each packet carries 102 bytes of context/snapshot/hop metadata in addition to its Ethernet, IPv4, and UDP headers and application payload. The sender initializes the snapshot and hop records to zero. As the packet traverses the fabric, switches fill their own hop slot; telemetry remains inline in that same data packet.

### What each switch processes

All four switches run the same P4 source, compiled with a different `SWITCH_ID`. The parser extracts Ethernet, then IPv4 for EtherType IPv4, UDP for protocol 17, and then the context shim, snapshot, and four hop records. The ingress logic accepts packets only when the IPv4 and UDP headers and context shim are valid and the IPv4 destination is h5. It uses the switch's compile-time ID to choose its forwarding action and hop-record slot. This prototype uses fixed output-port assignments rather than programmable ECMP tables or load-aware routing.

| Switch | Expected ingress | Forwarding decision | Hop record written |
| --- | --- | --- | --- |
| s1 | Host-facing ports 1-4 | Even flow ID -> port 5 to s2; odd flow ID -> port 6 to s3 | Record 1: s1 ID, actual ingress port, selected egress port, ingress timestamp. Also copies the packet's original Ethernet/IPv4/UDP fields into the snapshot. |
| s2 | Port 1 from s1 | Port 2 to s4 | Record 2: s2 ID, ingress/egress ports, ingress timestamp. |
| s3 | Port 1 from s1 | Port 2 to s4 | Record 3: s3 ID, ingress/egress ports, ingress timestamp. |
| s4 | Port 1 from s2 or port 2 from s3 | Port 3 to h5 | Record 4: s4 ID, ingress/egress ports, ingress timestamp. |

The two paths converge at s4. Each switch forwards the packet immediately after setting its output port and writing its telemetry; there is no packet buffering barrier, cross-flow aggregation, or switch-generated report in this program. The switches do not rewrite the original Ethernet/IP addresses or decrement TTL in this P4 logic. Since the telemetry changes the UDP payload, P4 sets the UDP checksum to zero; the snapshot preserves the UDP checksum observed at s1 ingress.

### Receiver-side detection and logs

At h5, `collective_demo.py` writes one JSON object per received packet to `/tmp/collective-telemetry.jsonl`, followed by a collective summary object. Packet records include worker/source and destination addresses, MACs, Ethernet type, IPv4 and UDP fields, flow and sequence numbers, path, per-switch ports and timestamps, and sender/receiver timing. The summary includes packet totals per flow and the straggler classification.

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
