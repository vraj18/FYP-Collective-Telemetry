# Basic P4 Collective Straggler Detector

This experiment detects arrival-time skew between participants in a collective operation. It uses BMv2 switches and reports detections in the switch log.

## Topology

The checked-in `topology.json` defines four hosts and four P4 switches. All links have bandwidth 100; the h3-to-s2 link has 20 ms delay and the other links have zero configured delay.

| Link endpoints | Delay |
| --- | ---: |
| h1 - s1 port 1 | 0 |
| h2 - s1 port 2 | 0 |
| s1 port 3 - s3 port 1 | 0 |
| s1 port 4 - s4 port 2 | 0 |
| h3 - s2 port 1 | 20 ms |
| h4 - s2 port 2 | 0 |
| s2 port 3 - s4 port 1 | 0 |
| s2 port 4 - s3 port 2 | 0 |

h1, h2, and h3 are collective participants; h4 is the receiver. For traffic to h4, s1 forwards through s4 and then s2. h3 connects directly to s2. As a result, all three participants' packets pass through s2, where their arrival times can be compared. The extra link delay on h3's path makes participant 3 the expected straggler in the example.

Each switch is compiled separately with its own `SWITCH_ID` and forwarding table. Each switch also has independent detection registers.

## Detection behavior

The sender puts a 6-byte collective shim at the beginning of the UDP payload:

| Field | Size |
| --- | ---: |
| `collective_id` | 2 bytes |
| `flow_id` | 1 byte |
| `participant_id` | 1 byte |
| `total_flow_count` | 1 byte |
| `flags` | 1 byte |

`collective_id` groups all constituent flows in one collective operation; `flow_id` identifies an individual flow within it. Set `total_flow_count` to the number of constituent flows and use the same value on every packet in that collective. For each hashed `collective_id`/`flow_id` pair, a switch stores the minimum and maximum ingress timestamps and the participant IDs associated with those timestamps. It calculates:

For a collective with five flows, all packets use the same `--collective-id 42 --total-flows 5`, while the flows use `--flow 1` through `--flow 5`. A log naming `collective_id=42 flow=4 total_flows=5` identifies flow 4 as the detected lagging flow within that five-flow collective.

```text
skew = max_timestamp - min_timestamp
```

When `skew > 5000` (the configured 5 ms threshold), it writes a `COLLECTIVE_STRAGGLER` message to that switch's BMv2 log. The report includes the switch ID, collective ID, affected flow, declared total flow count, triggering participant, skew, and the participants associated with the minimum and maximum timestamps. `impact=COLLECTIVE_DEGRADED` signals that the collective containing the affected flow is impacted. The report is generated in the data plane's log; this version does not send a separate telemetry packet.

For this experiment, participant 1 is assumed to arrive first and resets the timestamp bounds for that collective/flow. Send participant 1 before the other participants. Switches still track and report flows independently: `total_flow_count` is packet-provided context, not an observed count of completed or slow flows. The log identifies a flow with network arrival skew that may delay its parent collective; it does not observe application-level completion or prove that workers are waiting. `flags` is carried in the shim but is not currently used by the P4 program.

## Build and run

Run these commands from this directory:

```sh
make
make run
```

`make` compiles `straggler.p4` into `build/s1.json` through `build/s4.json`. `make run` starts the Mininet topology using `topology.json`. In the Mininet CLI, send one packet from each participant, in order:

```text
h1 python3 sender.py --participant 1 --collective-id 1 --flow 7 --total-flows 1
h2 python3 sender.py --participant 2 --collective-id 1 --flow 7 --total-flows 1
h3 python3 sender.py --participant 3 --collective-id 1 --flow 7 --total-flows 1
```

The h3 packet should reach s2 roughly 20 ms later than the packets from h1 and h2, exceeding the 5 ms threshold. Watch s2's log from another terminal:

```sh
tail -f logs/s2.log
```

A detection should resemble:

```text
COLLECTIVE_STRAGGLER switch=2 collective_id=1 flow=7 total_flows=1 impact=COLLECTIVE_DEGRADED participant=3 skew_us=... min_participant=1 max_participant=3
```

### Two-collective test

Instead of the three sender commands above, run this in the Mininet CLI:

```text
h1 python3 collective_demo.py --collective-1 100 --collective-2 101 --straggler-delay-ms 50
```

The script sends five participant packets for each collective on the same flow. Collective 1 is sent as a burst; collective 2's participant 5 is delayed by 50 ms, above the 5 ms detector threshold. Here `total_flows=1` because the five packets are participants on one flow, not five distinct flows. The expected detection names `collective_id=101` and `participant=5`; there should be no new detection for `collective_id=100`. Since the script sends from h1, detections should appear on its path through s1, s4, and s2. In another terminal, inspect them with:

```sh
grep 'COLLECTIVE_STRAGGLER' logs/s1.log logs/s2.log logs/s4.log
```

The logs append across runs, so use new collective IDs or clear the logs before repeating the test.

The measured skew varies with runtime scheduling. Use `make stop` to stop and clean up Mininet. To render the topology JSON in the optional viewer, run `python3 topology_viewer.py` from this directory.

## Scope

This starter implements the core arrival-skew detection loop: operation context, per-switch state, minimum/maximum arrival timestamps, a threshold, and log-based reporting. The configured delay is link-wide, not selectively injected into a particular packet, and detection state is not explicitly expired or cleared except when participant 1 starts the same context/flow again.
