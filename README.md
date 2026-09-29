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

The sender puts a 5-byte collective shim at the beginning of the UDP payload:

| Field | Size |
| --- | ---: |
| `context_id` | 2 bytes |
| `flow_id` | 1 byte |
| `participant_id` | 1 byte |
| `flags` | 1 byte |

For each hashed `context_id`/`flow_id` pair, a switch stores the minimum and maximum ingress timestamps and the participant IDs associated with those timestamps. It calculates:

```text
skew = max_timestamp - min_timestamp
```

When `skew > 5000` (the configured 5 ms threshold), it writes a `STRAGGLER` message to that switch's BMv2 log. The report includes the switch ID, context, flow, triggering packet's participant, skew, and the participants associated with the minimum and maximum timestamps. The report is generated in the data plane's log; this version does not send a separate telemetry packet.

For this experiment, participant 1 is assumed to arrive first and resets the timestamp bounds for that context/flow. Send participant 1 before the other participants. `flags` is carried in the shim but is not currently used by the P4 program.

## Build and run

Run these commands from this directory:

```sh
make
make run
```

`make` compiles `straggler.p4` into `build/s1.json` through `build/s4.json`. `make run` starts the Mininet topology using `topology.json`. In the Mininet CLI, send one packet from each participant, in order:

```text
h1 python3 sender.py --participant 1 --context 1 --flow 7
h2 python3 sender.py --participant 2 --context 1 --flow 7
h3 python3 sender.py --participant 3 --context 1 --flow 7
```

The h3 packet should reach s2 roughly 20 ms later than the packets from h1 and h2, exceeding the 5 ms threshold. Watch s2's log from another terminal:

```sh
tail -f logs/s2.log
```

A detection should resemble:

```text
STRAGGLER switch=2 context=1 flow=7 participant=3 skew_us=... min_participant=1 max_participant=3
```

The measured skew varies with runtime scheduling. Use `make stop` to stop and clean up Mininet. To render the topology JSON in the optional viewer, run `python3 topology_viewer.py` from this directory.

## Scope

This starter implements the core arrival-skew detection loop: operation context, per-switch state, minimum/maximum arrival timestamps, a threshold, and log-based reporting. The configured delay is link-wide, not selectively injected into a particular packet, and detection state is not explicitly expired or cleared except when participant 1 starts the same context/flow again.
