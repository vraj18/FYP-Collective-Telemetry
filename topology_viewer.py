#!/usr/bin/env python3
"""
Render a Mininet-style topology JSON as a simple graphical diagram.

Usage:
    python3 topology_viewer.py
    python3 topology_viewer.py --file topology.json
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk


@dataclass
class Node:
    name: str
    kind: str
    x: int = 0
    y: int = 0
    ip: Optional[str] = None
    mac: Optional[str] = None


@dataclass
class Link:
    a: str
    b: str
    delay: Optional[str] = None
    bandwidth: Optional[int] = None


class TopologyParser:
    @staticmethod
    def normalize_endpoint(endpoint: str) -> str:
        if not isinstance(endpoint, str):
            return str(endpoint)
        if "-p" in endpoint:
            return endpoint.split("-p", 1)[0]
        return endpoint

    @staticmethod
    def parse(path: Path) -> Tuple[Dict[str, Node], List[Link]]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        hosts = data.get("hosts", {})
        switches = data.get("switches", {})

        nodes: Dict[str, Node] = {}

        for host_name, host_cfg in hosts.items():
            nodes[host_name] = Node(
                name=host_name,
                kind="host",
                ip=host_cfg.get("ip"),
                mac=host_cfg.get("mac"),
            )

        for switch_name in switches.keys():
            nodes[switch_name] = Node(
                name=switch_name,
                kind="switch",
            )

        links: List[Link] = []
        for raw_link in data.get("links", []):
            if not raw_link:
                continue
            if isinstance(raw_link, dict):
                a = raw_link.get("src")
                b = raw_link.get("dst")
                delay = raw_link.get("delay") or raw_link.get("latency")
                bandwidth = raw_link.get("bandwidth")
            else:
                if len(raw_link) == 2:
                    a, b = raw_link
                    delay = None
                    bandwidth = None
                elif len(raw_link) == 3:
                    a, b, delay = raw_link
                    bandwidth = None
                elif len(raw_link) >= 4:
                    a, b, delay, bandwidth = raw_link[:4]
                else:
                    continue

            if a is None or b is None:
                continue

            a_norm = TopologyParser.normalize_endpoint(str(a))
            b_norm = TopologyParser.normalize_endpoint(str(b))

            if a_norm not in nodes:
                nodes[a_norm] = Node(name=a_norm, kind="switch")
            if b_norm not in nodes:
                nodes[b_norm] = Node(name=b_norm, kind="switch")

            links.append(
                Link(
                    a=a_norm,
                    b=b_norm,
                    delay=str(delay) if delay is not None else None,
                    bandwidth=int(bandwidth) if bandwidth is not None else None,
                )
            )

        return nodes, links


class TopologyCanvas:
    def __init__(self, root: tk.Tk, nodes: Dict[str, Node], links: List[Link]):
        self.root = root
        self.nodes = nodes
        self.links = links
        self.canvas = tk.Canvas(root, width=1200, height=780, bg="#f4f7fb", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.dragged = None
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self._position_nodes()
        self._draw_background_grid()
        self._draw_edges()
        self._draw_nodes()

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self.root.title("Topology Viewer")
        self.root.geometry("1200x780")

    def _position_nodes(self) -> None:
        hosts = sorted((n for n in self.nodes.values() if n.kind == "host"), key=lambda n: n.name)
        switches = sorted((n for n in self.nodes.values() if n.kind == "switch"), key=lambda n: n.name)

        center_x = 600
        center_y = 390
        switch_radius = 200
        host_radius = 330

        if len(switches) == 2:
            for i, sw in enumerate(switches):
                sw.x = 420 if i == 0 else 780
                sw.y = 390
        elif len(switches) >= 3:
            n = len(switches)
            for i, sw in enumerate(switches):
                angle = math.radians(-90 + i * 360 / n)
                sw.x = int(center_x + switch_radius * math.cos(angle))
                sw.y = int(center_y + switch_radius * math.sin(angle))
        elif len(switches) == 1:
            switches[0].x = center_x
            switches[0].y = center_y

        if hosts:
            n_hosts = len(hosts)
            for i, host in enumerate(hosts):
                angle = math.radians(-90 + i * 360 / max(1, n_hosts))
                host.x = int(center_x + host_radius * math.cos(angle))
                host.y = int(center_y + host_radius * math.sin(angle))

    def _find_node_at(self, x: int, y: int):
        for node in self.nodes.values():
            if node.kind == "host":
                width = 160
                height = 70
                if abs(node.x - x) <= width // 2 and abs(node.y - y) <= height // 2:
                    return node
            else:
                r = 52
                if (x - node.x) ** 2 + (y - node.y) ** 2 <= r ** 2:
                    return node
        return None

    def _on_press(self, event):
        node = self._find_node_at(event.x, event.y)
        if node is not None:
            self.dragged = node
            self.drag_offset_x = event.x - node.x
            self.drag_offset_y = event.y - node.y

    def _on_drag(self, event):
        if self.dragged is not None:
            self.dragged.x = event.x - self.drag_offset_x
            self.dragged.y = event.y - self.drag_offset_y
            self.redraw()

    def _on_release(self, event):
        self.dragged = None

    def redraw(self):
        self.canvas.delete("all")
        self._draw_background_grid()
        self._draw_edges()
        self._draw_nodes()

    def _draw_background_grid(self) -> None:
        for x in range(0, 1200, 50):
            self.canvas.create_line(x, 0, x, 780, fill="#e6edf5", width=1)
        for y in range(0, 780, 50):
            self.canvas.create_line(0, y, 1200, y, fill="#e6edf5", width=1)

    def _draw_edges(self) -> None:
        seen = set()
        for link in self.links:
            a = self.nodes.get(link.a)
            b = self.nodes.get(link.b)
            if a is None or b is None:
                continue

            edge_key = tuple(sorted((link.a, link.b)))
            if edge_key in seen:
                continue
            seen.add(edge_key)

            x1, y1 = a.x, a.y
            x2, y2 = b.x, b.y

            self.canvas.create_line(x1, y1, x2, y2, fill="#5a6a85", width=2.5, arrow=tk.LAST)

            mx = (x1 + x2) / 2
            my = (y1 + y2) / 2
            label = ""
            if link.delay:
                label = str(link.delay)
            if link.bandwidth is not None:
                label = f"{label} {link.bandwidth}" if label else str(link.bandwidth)

            if label:
                self.canvas.create_text(mx, my - 12, text=label, fill="#2f3d4f", font=("Helvetica", 9, "bold"))

    def _draw_nodes(self) -> None:
        for node in self.nodes.values():
            if node.kind == "host":
                fill = "#60a5fa"
                outline = "#1d4ed8"
                width = 160
                height = 70
                x1 = node.x - width // 2
                y1 = node.y - height // 2
                self.canvas.create_rectangle(x1, y1, x1 + width, y1 + height, fill=fill, outline=outline, width=2)
                self.canvas.create_text(node.x, node.y - 10, text=node.name, font=("Helvetica", 11, "bold"), fill="#0f172a")
                if node.ip:
                    self.canvas.create_text(node.x, node.y + 12, text=node.ip, font=("Helvetica", 9), fill="#0f172a")
            else:
                fill = "#8b5cf6"
                outline = "#5b21b6"
                r = 52
                self.canvas.create_oval(node.x - r, node.y - r, node.x + r, node.y + r, fill=fill, outline=outline, width=2)
                self.canvas.create_text(node.x, node.y, text=node.name, font=("Helvetica", 11, "bold"), fill="#fff")

    def add_summary(self, root: tk.Tk) -> None:
        summary = ttk.LabelFrame(root, text="Topology Summary", padding=(10, 8))
        summary.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        hosts = sum(1 for n in self.nodes.values() if n.kind == "host")
        switches = sum(1 for n in self.nodes.values() if n.kind == "switch")
        links = len(self.links)

        info = [
            f"Hosts: {hosts}",
            f"Switches: {switches}",
            f"Links: {links}",
        ]

        for line in info:
            ttk.Label(summary, text=line, font=("Helvetica", 10)).pack(anchor="w", pady=4)


class TopologyWindow:
    def __init__(self, topology_path: Path):
        self.root = tk.Tk()
        self.root.configure(bg="#eef4ff")
        self.root.title(f"Topology View: {topology_path.name}")

        nodes, links = TopologyParser.parse(topology_path)
        self.canvas_widget = TopologyCanvas(self.root, nodes, links)
        self.canvas_widget.add_summary(self.root)

    def run(self) -> None:
        self.root.mainloop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visualize a Mininet topology JSON file.")
    parser.add_argument("--file", type=str, default="topology.json", help="Path to topology.json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    topology_path = Path(args.file).resolve()

    if not topology_path.exists():
        raise FileNotFoundError(f"Topology file not found: {topology_path}")

    app = TopologyWindow(topology_path)
    app.run()


if __name__ == "__main__":
    main()
