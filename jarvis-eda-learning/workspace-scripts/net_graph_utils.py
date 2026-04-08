from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional


@dataclass
class Component:
    name: str
    ctype: str
    nets: List[str]
    params: Dict[str, str] = field(default_factory=dict)


@dataclass
class NetGraph:
    components: Dict[str, Component] = field(default_factory=dict)
    net_to_components: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_component(self, comp: Component) -> None:
        self.components[comp.name] = comp
        for net in comp.nets:
            self.net_to_components[net].add(comp.name)

    def component_neighbors(self, comp_name: str) -> Set[str]:
        neighbors: Set[str] = set()
        comp = self.components[comp_name]
        for net in comp.nets:
            neighbors.update(self.net_to_components[net])
        neighbors.discard(comp_name)
        return neighbors

    def find_ports(self) -> List[str]:
        port_like = []
        for name, comp in self.components.items():
            ctype = comp.ctype.lower()
            if "port" in ctype or "term" in ctype:
                port_like.append(name)
        return port_like


def shortest_component_path(graph: NetGraph, start: str, end: str) -> List[str]:
    """Breadth-first search over component adjacency."""
    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        node, path = queue.popleft()
        if node == end:
            return path

        for nbr in graph.component_neighbors(node):
            if nbr not in visited:
                visited.add(nbr)
                queue.append((nbr, path + [nbr]))

    return []


def infer_main_backbone(graph: NetGraph, preferred_ports: Optional[List[str]] = None) -> List[str]:
    """
    Very simple backbone inference:
    - find 2 ports
    - return shortest path between them
    """
    ports = preferred_ports or graph.find_ports()
    if len(ports) < 2:
        return []

    best_path: List[str] = []
    for i in range(len(ports)):
        for j in range(i + 1, len(ports)):
            path = shortest_component_path(graph, ports[i], ports[j])
            if path and (not best_path or len(path) > len(best_path)):
                best_path = path
    return best_path


def classify_component_basic(comp: Component) -> str:
    """
    Very rough heuristic classification for placement planning.
    """
    ctype = comp.ctype.lower()
    name = comp.name.lower()

    if "port" in ctype or "term" in ctype:
        return "port"
    if "gnd" in name or "gnd" in ctype:
        return "ground_support"
    if any(k in ctype for k in ["fet", "mos", "transistor"]):
        return "active_core"
    if any(k in name for k in ["gate", "bias", "ctrl", "vctrl", "vg"]):
        return "control_bias"
    if any(k in ctype for k in ["cap", "ind", "res", "mlin", "tline", "tl"]):
        return "rf_or_passive"
    if any(k in ctype for k in ["sp", "hb", "sim", "controller"]):
        return "simulation"
    return "unknown"