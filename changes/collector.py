#!/usr/bin/env python3
"""Read per-collective aggregates from s1 and s4 and name the slow path."""
import argparse
import re
import subprocess

THRIFT = {1: 9090, 2: 9091, 3: 9092, 4: 9093}
BUCKETS = 1024
# path name -> (slot at s1 = output port, slot at s4 = input port)
PATHS = {"s1-s2-s4": (5, 1), "s1-s3-s4": (6, 2)}


def cli(switch, commands):
    return subprocess.run(
        ["simple_switch_CLI", "--thrift-port", str(THRIFT[switch])],
        input=commands, capture_output=True, text=True,
    ).stdout


def reg(switch, name, index):
    out = cli(switch, f"register_read MyIngress.{name} {index}\n")
    found = re.search(r"\]\s*=\s*(\d+)", out)
    if not found:
        raise SystemExit(f"could not read {name}[{index}] from s{switch}:\n{out}")
    return int(found.group(1))


def aggregate(switch, collective_id, slot):
    index = (collective_id % BUCKETS) * 8 + slot
    return reg(switch, "agg_count", index), reg(switch, "agg_sum", index)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collective-id", type=int, default=42)
    ap.add_argument("--threshold-ms", type=float, default=10.0)
    ap.add_argument("--reset", action="store_true", help="zero all aggregates and exit")
    args = ap.parse_args()

    if args.reset:
        for switch in THRIFT:
            cli(switch, "register_reset MyIngress.agg_count\nregister_reset MyIngress.agg_sum\n")
        print("aggregates reset")
        return

    transit = {}
    for name, (s1_slot, s4_slot) in PATHS.items():
        c1, sum1 = aggregate(1, args.collective_id, s1_slot)
        c4, sum4 = aggregate(4, args.collective_id, s4_slot)
        if c1 == 0 or c4 == 0:
            print(f"{name}: no packets seen (s1={c1}, s4={c4})")
            continue
        if c1 != c4:
            print(f"warning: {name} counts differ (s1={c1}, s4={c4}): loss or stale data")
        # Mean s4 time minus mean s1 time for the same packets. Assumes microsecond
        # timestamps. Any constant clock offset between s1 and s4 is the same for
        # both paths, so it cancels in the gap below.
        transit[name] = (sum4 / c4 - sum1 / c1) / 1000.0
        print(f"{name}: packets={c4} mean_transit_ms(incl. constant offset)={transit[name]:.3f}")

    if len(transit) < 2:
        raise SystemExit("need packets on both paths to compare")
    gap = abs(transit["s1-s2-s4"] - transit["s1-s3-s4"])
    flagged = gap > args.threshold_ms
    slow = max(transit, key=transit.get) if flagged else "none"
    verdict = "NETWORK_INDUCED_STRAGGLER_PATH" if flagged else "NO_STRAGGLER_PATH"
    print(f"AGG_RESULT collective_id={args.collective_id} slow_path={slow} "
          f"path_gap_ms={gap:.3f} classification={verdict}")


if __name__ == "__main__":
    main()