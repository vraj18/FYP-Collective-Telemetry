#include <core.p4>
#include <v1model.p4>

/* Flow-affine ECMP forwarding for one multi-flow collective. */

const bit<16> ETHERTYPE_IPV4 = 0x0800;
const bit<8>  IP_PROTO_UDP   = 17;
const bit<32> RECEIVER_IPV4 = 0x0a000005;

#ifndef SWITCH_ID
#define SWITCH_ID 1
#endif

header ethernet_t {
    bit<48> dstAddr;
    bit<48> srcAddr;
    bit<16> etherType;
}

header ipv4_t {
    bit<4>  version;
    bit<4>  ihl;
    bit<8>  diffserv;
    bit<16> totalLen;
    bit<16> identification;
    bit<3>  flags;
    bit<13> fragOffset;
    bit<8>  ttl;
    bit<8>  protocol;
    bit<16> hdrChecksum;
    bit<32> srcAddr;
    bit<32> dstAddr;
}

header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length_;
    bit<16> checksum;
}

/* Collective context followed by packet-header and four-hop telemetry. */
header collective_t {
    bit<16> collective_id;
    bit<8>  flow_id;
    bit<16> packet_index;
    bit<16> packets_per_flow;
    bit<8>  ecmp_path;
    bit<64> sender_timestamp_ns;
}

header packet_snapshot_t {
    bit<48> eth_dst;
    bit<48> eth_src;
    bit<16> ethertype;
    bit<4>  ip_version;
    bit<4>  ip_ihl;
    bit<8>  ip_diffserv;
    bit<16> ip_total_len;
    bit<16> ip_identification;
    bit<3>  ip_flags;
    bit<13> ip_frag_offset;
    bit<8>  ip_ttl;
    bit<8>  ip_protocol;
    bit<16> ip_checksum;
    bit<32> ip_src;
    bit<32> ip_dst;
    bit<16> udp_src_port;
    bit<16> udp_dst_port;
    bit<16> udp_length;
    bit<16> udp_checksum;
}

header hop_t {
    bit<8> switch_id;
    bit<8> ingress_port;
    bit<8> egress_port;
    bit<64> ingress_timestamp;
}

struct headers_t {
    ethernet_t  ethernet;
    ipv4_t      ipv4;
    udp_t       udp;
    collective_t collective;
    packet_snapshot_t packet_snapshot;
    hop_t hop1;
    hop_t hop2;
    hop_t hop3;
    hop_t hop4;
}

struct metadata_t {
    bit<1> unused;
}

parser MyParser(
    packet_in packet,
    out headers_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t standard_metadata)
{
    state start {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            ETHERTYPE_IPV4: parse_ipv4;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            IP_PROTO_UDP: parse_udp;
            default: accept;
        }
    }

    state parse_udp {
        packet.extract(hdr.udp);
        transition parse_collective;
    }

    state parse_collective {
        packet.extract(hdr.collective);
        transition parse_packet_snapshot;
    }

    state parse_packet_snapshot {
        packet.extract(hdr.packet_snapshot);
        transition parse_hops;
    }

    state parse_hops {
        packet.extract(hdr.hop1);
        packet.extract(hdr.hop2);
        packet.extract(hdr.hop3);
        packet.extract(hdr.hop4);
        transition accept;
    }
}

control MyVerifyChecksum(
    inout headers_t hdr,
    inout metadata_t meta)
{
    apply { }
}

control MyIngress(
    inout headers_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t standard_metadata)
{
    action drop() {
        mark_to_drop(standard_metadata);
    }

    apply {
        if (hdr.ipv4.isValid() && hdr.udp.isValid() &&
            hdr.collective.isValid() && hdr.ipv4.dstAddr == RECEIVER_IPV4) {
#if SWITCH_ID == 1
            /* Flow-ID parity is the ECMP hash over the two equal-cost paths. */
            if (hdr.collective.flow_id[0:0] == 1w0) {
                standard_metadata.egress_spec = 5;
            }
            else {
                standard_metadata.egress_spec = 6;
            }
            hdr.packet_snapshot.eth_dst = hdr.ethernet.dstAddr;
            hdr.packet_snapshot.eth_src = hdr.ethernet.srcAddr;
            hdr.packet_snapshot.ethertype = hdr.ethernet.etherType;
            hdr.packet_snapshot.ip_version = hdr.ipv4.version;
            hdr.packet_snapshot.ip_ihl = hdr.ipv4.ihl;
            hdr.packet_snapshot.ip_diffserv = hdr.ipv4.diffserv;
            hdr.packet_snapshot.ip_total_len = hdr.ipv4.totalLen;
            hdr.packet_snapshot.ip_identification = hdr.ipv4.identification;
            hdr.packet_snapshot.ip_flags = hdr.ipv4.flags;
            hdr.packet_snapshot.ip_frag_offset = hdr.ipv4.fragOffset;
            hdr.packet_snapshot.ip_ttl = hdr.ipv4.ttl;
            hdr.packet_snapshot.ip_protocol = hdr.ipv4.protocol;
            hdr.packet_snapshot.ip_checksum = hdr.ipv4.hdrChecksum;
            hdr.packet_snapshot.ip_src = hdr.ipv4.srcAddr;
            hdr.packet_snapshot.ip_dst = hdr.ipv4.dstAddr;
            hdr.packet_snapshot.udp_src_port = hdr.udp.srcPort;
            hdr.packet_snapshot.udp_dst_port = hdr.udp.dstPort;
            hdr.packet_snapshot.udp_length = hdr.udp.length_;
            hdr.packet_snapshot.udp_checksum = hdr.udp.checksum;
            hdr.hop1.switch_id = 1;
            hdr.hop1.ingress_port = (bit<8>) standard_metadata.ingress_port;
            hdr.hop1.egress_port = (bit<8>) standard_metadata.egress_spec;
            hdr.hop1.ingress_timestamp = (bit<64>) standard_metadata.ingress_global_timestamp;
#elif SWITCH_ID == 2
            standard_metadata.egress_spec = 2;
            hdr.hop2.switch_id = 2;
            hdr.hop2.ingress_port = (bit<8>) standard_metadata.ingress_port;
            hdr.hop2.egress_port = (bit<8>) standard_metadata.egress_spec;
            hdr.hop2.ingress_timestamp = (bit<64>) standard_metadata.ingress_global_timestamp;
#elif SWITCH_ID == 3
            standard_metadata.egress_spec = 2;
            hdr.hop3.switch_id = 3;
            hdr.hop3.ingress_port = (bit<8>) standard_metadata.ingress_port;
            hdr.hop3.egress_port = (bit<8>) standard_metadata.egress_spec;
            hdr.hop3.ingress_timestamp = (bit<64>) standard_metadata.ingress_global_timestamp;
#elif SWITCH_ID == 4
            standard_metadata.egress_spec = 3;
            hdr.hop4.switch_id = 4;
            hdr.hop4.ingress_port = (bit<8>) standard_metadata.ingress_port;
            hdr.hop4.egress_port = (bit<8>) standard_metadata.egress_spec;
            hdr.hop4.ingress_timestamp = (bit<64>) standard_metadata.ingress_global_timestamp;
#else
            drop();
#endif
            /* Telemetry modifies the UDP payload; disable its old checksum. */
            hdr.udp.checksum = 0;
        }
        else {
            drop();
        }
    }
}

control MyEgress(
    inout headers_t hdr,
    inout metadata_t meta,
    inout standard_metadata_t standard_metadata)
{
    apply { }
}

control MyComputeChecksum(
    inout headers_t hdr,
    inout metadata_t meta)
{
    apply {
        /*
         * We do not modify the IPv4 header, so its checksum remains valid.
         */
    }
}

control MyDeparser(
    packet_out packet,
    in headers_t hdr)
{
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.udp);
        packet.emit(hdr.collective);
        packet.emit(hdr.packet_snapshot);
        packet.emit(hdr.hop1);
        packet.emit(hdr.hop2);
        packet.emit(hdr.hop3);
        packet.emit(hdr.hop4);

        /*
         * Any bytes after the parsed headers are automatically
         * treated as payload by BMv2 and remain after the deparser.
         */
    }
}

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
