"""
translator/ir_builder.py
========================
Stage 1b — Intermediate Representation (IR) builder for the net2ads pipeline.

Receives a ParseResult from parser.py and produces:
  - A validated, classified IR (see schemas/ir.yaml for schema)
  - A YAML artifact written to <output_dir>/<name>_ir.yaml (CONSTRAINTS.md C5)

IR construction steps:
  1. Collect all unique nodes from component node lists
  2. Classify each component as series / shunt / tline / switch
  3. Identify backbone (main signal path from port 1 to port 2)
  4. Identify shunt branches and switch arms
  5. Compute minimum phase required for the full circuit

Usage:
    from translator.ir_builder import build_ir, write_ir
    ir = build_ir(parse_result)
    write_ir(ir, output_dir=Path("examples/rc_series_shunt"))
"""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from translator.parser import ParseResult, ParsedComponent, ParsedPort


# ── IR data structures ─────────────────────────────────────────────────────────

@dataclass
class IRNode:
    name: str
    is_port: bool
    connects_to_ground: bool    # has any direct component to node "0"


@dataclass
class IRComponent:
    id: str
    type: str
    nodes: list                 # [node1, node2]
    params: dict                # {param_name: value_string}
    role: str                   # series | shunt | tline | switch
    phase_required: int
    source_line: int


@dataclass
class IRShuntBranch:
    tap_node: str               # signal node where shunt connects
    component_id: str           # component in this shunt branch


@dataclass
class IRSwitchArm:
    component_id: str
    state: str                  # ON | OFF


@dataclass
class IRGraph:
    backbone: list              # ordered node names on main signal path
    backbone_components: list   # ordered component IDs on backbone
    shunt_branches: list        # list of IRShuntBranch
    switch_arms: list           # list of IRSwitchArm


@dataclass
class IRMetadata:
    warnings: list
    port_count: int
    component_count: int
    series_count: int
    shunt_count: int
    tline_count: int
    switch_count: int


@dataclass
class IR:
    cell_name: str
    source_file: str
    parse_timestamp: str
    phase_required: int         # max phase_required across all components
    ports: list                 # list of IRPort (name, node, number)
    nodes: list                 # list of IRNode
    components: list            # list of IRComponent
    graph: IRGraph
    metadata: IRMetadata
    design_variables: list      # list of (name, value_string) from .VAR declarations


@dataclass
class IRPort:
    name: str
    node: str
    number: int                 # 1-indexed


# ── Classification ─────────────────────────────────────────────────────────────

GROUND_NODES = {"0", "gnd", "ground", "vss"}    # node names treated as ground


def _is_ground(node: str) -> bool:
    return node.strip().lower() in GROUND_NODES


def _classify_role(comp: ParsedComponent) -> str:
    """
    Classify a component's topological role.
      shunt   — one node is ground (direct connection to "0")
      tline   — type is TLIN (regardless of node assignment)
      switch  — type is SW
      series  — all other cases (both nodes are signal nodes)
    """
    if comp.type == "TLIN":
        return "tline"
    if comp.type == "SW":
        return "switch"
    if any(_is_ground(n) for n in comp.nodes):
        return "shunt"
    return "series"


# ── Backbone tracing ───────────────────────────────────────────────────────────

def _build_adjacency(components: list, port_nodes: set) -> dict:
    """
    Build adjacency dict: node -> list of (neighbor_node, component_id).
    Only includes series and tline components (shunts branch off to ground).
    """
    adj = {}
    for comp in components:
        if comp.role not in ("series", "tline"):
            continue
        n1, n2 = comp.nodes[0], comp.nodes[1]
        adj.setdefault(n1, []).append((n2, comp.id))
        adj.setdefault(n2, []).append((n1, comp.id))
    return adj


def _trace_backbone(adj: dict, start: str, end: str) -> tuple:
    """
    BFS to find shortest path from start node to end node through series components.
    Returns (node_path, component_path) or ([], []) if no path found.
    """
    from collections import deque
    queue = deque([(start, [start], [])])
    visited = {start}

    while queue:
        node, node_path, comp_path = queue.popleft()
        if node == end:
            return node_path, comp_path
        for neighbor, comp_id in adj.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, node_path + [neighbor], comp_path + [comp_id]))

    return [], []


# ── Main builder ───────────────────────────────────────────────────────────────

def build_ir(parse_result: ParseResult) -> IR:
    """
    Build an IR from a ParseResult.

    The IR is the normalized internal representation of the circuit topology.
    It is PDK-agnostic — mapping to ADS components happens in Stage 2.
    """
    warnings = list(parse_result.warnings)  # carry forward parser warnings

    # ── Ports ──────────────────────────────────────────────────────────────────
    # Primary port list: from PORT: declarations.
    # Fallback: use .SUBCKT header port names if PORT: lines are absent.
    if parse_result.ports:
        ports = [
            IRPort(name=p.name, node=p.node, number=i + 1)
            for i, p in enumerate(parse_result.ports)
        ]
    else:
        ports = [
            IRPort(name=name, node=name, number=i + 1)
            for i, name in enumerate(parse_result.subckt_ports)
        ]
        if parse_result.subckt_ports:
            warnings.append(
                "[INFO] No PORT: declarations found — using .SUBCKT port list as port definitions"
            )

    port_nodes = {p.node for p in ports}
    port_names = {p.name for p in ports}

    # ── Components — classify roles ───────────────────────────────────────────
    ir_components = []
    for comp in parse_result.components:
        role = _classify_role(comp)
        ir_components.append(IRComponent(
            id=comp.id,
            type=comp.type,
            nodes=comp.nodes,
            params=comp.params,
            role=role,
            phase_required=comp.phase_required,
            source_line=comp.source_line,
        ))

    # ── Nodes ─────────────────────────────────────────────────────────────────
    all_nodes = set()
    ground_adjacent = set()   # nodes that have a direct component to ground
    for comp in ir_components:
        for n in comp.nodes:
            if not _is_ground(n):
                all_nodes.add(n)
            else:
                # The other node connects to ground
                signal_nodes = [x for x in comp.nodes if not _is_ground(x)]
                ground_adjacent.update(signal_nodes)

    ir_nodes = [
        IRNode(
            name=n,
            is_port=(n in port_nodes or n in port_names),
            connects_to_ground=(n in ground_adjacent),
        )
        for n in sorted(all_nodes)
    ]

    # ── Graph: backbone trace ─────────────────────────────────────────────────
    adj = _build_adjacency(ir_components, port_nodes)

    backbone_nodes, backbone_comps = [], []
    if len(ports) >= 2:
        start_node = ports[0].node
        end_node   = ports[1].node
        backbone_nodes, backbone_comps = _trace_backbone(adj, start_node, end_node)
        if not backbone_nodes:
            if len(ports) >= 3:
                # 3-port topology (e.g. SPDT switch): backbone trace not applicable.
                # The SPDT placement path handles multi-port routing independently.
                warnings.append(
                    f"[INFO] Backbone trace skipped for {len(ports)}-port topology "
                    f"('{start_node}' -> '{end_node}'). Expected for SPDT circuits."
                )
            else:
                warnings.append(
                    f"[WARN] Could not trace backbone from '{start_node}' to '{end_node}'. "
                    "Check that series components connect port 1 to port 2."
                )

    # ── Graph: shunt branches ─────────────────────────────────────────────────
    shunt_branches = []
    for comp in ir_components:
        if comp.role == "shunt":
            # tap node = the non-ground node
            tap = next((n for n in comp.nodes if not _is_ground(n)), None)
            if tap:
                shunt_branches.append(IRShuntBranch(tap_node=tap, component_id=comp.id))

    # ── Graph: switch arms ────────────────────────────────────────────────────
    switch_arms = []
    for comp in ir_components:
        if comp.role == "switch":
            state = comp.params.get("State", comp.params.get("state", "UNKNOWN")).upper()
            switch_arms.append(IRSwitchArm(component_id=comp.id, state=state))
            if state not in ("ON", "OFF"):
                warnings.append(
                    f"[WARN] Component {comp.id}: unrecognized State value '{state}' "
                    "(expected ON or OFF)"
                )

    graph = IRGraph(
        backbone=backbone_nodes,
        backbone_components=backbone_comps,
        shunt_branches=shunt_branches,
        switch_arms=switch_arms,
    )

    # ── Phase requirement ─────────────────────────────────────────────────────
    phase_required = 1
    for comp in ir_components:
        if comp.phase_required > phase_required:
            phase_required = comp.phase_required

    # ── Metadata ──────────────────────────────────────────────────────────────
    roles = [c.role for c in ir_components]
    metadata = IRMetadata(
        warnings=warnings,
        port_count=len(ports),
        component_count=len(ir_components),
        series_count=roles.count("series"),
        shunt_count=roles.count("shunt"),
        tline_count=roles.count("tline"),
        switch_count=roles.count("switch"),
    )

    return IR(
        cell_name=parse_result.cell_name,
        source_file=parse_result.source_file,
        parse_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        phase_required=phase_required,
        ports=ports,
        nodes=ir_nodes,
        components=ir_components,
        graph=graph,
        metadata=metadata,
        design_variables=list(parse_result.design_variables),
    )


# ── YAML serialization ─────────────────────────────────────────────────────────

def _ir_to_dict(ir: IR) -> dict:
    """Convert IR to a plain dict suitable for YAML serialization."""
    return {
        "cell_name": ir.cell_name,
        "source_file": ir.source_file,
        "parse_timestamp": ir.parse_timestamp,
        "phase_required": ir.phase_required,
        "ports": [
            {"name": p.name, "node": p.node, "number": p.number}
            for p in ir.ports
        ],
        "nodes": [
            {"name": n.name, "is_port": n.is_port, "connects_to_ground": n.connects_to_ground}
            for n in ir.nodes
        ],
        "components": [
            {
                "id": c.id,
                "type": c.type,
                "nodes": c.nodes,
                "params": c.params,
                "role": c.role,
                "phase_required": c.phase_required,
            }
            for c in ir.components
        ],
        "graph": {
            "backbone": ir.graph.backbone,
            "backbone_components": ir.graph.backbone_components,
            "shunt_branches": [
                {"tap_node": b.tap_node, "component_id": b.component_id}
                for b in ir.graph.shunt_branches
            ],
            "switch_arms": [
                {"component_id": a.component_id, "state": a.state}
                for a in ir.graph.switch_arms
            ],
        },
        "metadata": {
            "warnings": ir.metadata.warnings,
            "port_count": ir.metadata.port_count,
            "component_count": ir.metadata.component_count,
            "series_count": ir.metadata.series_count,
            "shunt_count": ir.metadata.shunt_count,
            "tline_count": ir.metadata.tline_count,
            "switch_count": ir.metadata.switch_count,
        },
        "design_variables": [
            {"name": name, "value": val} for name, val in ir.design_variables
        ],
    }


def write_ir(ir: IR, output_dir: Path) -> Path:
    """
    Write IR to <output_dir>/<cell_name_lower>_ir.yaml.
    Returns the path written.
    Raises RuntimeError if PyYAML is not available.
    """
    if not _YAML_AVAILABLE:
        raise RuntimeError(
            "PyYAML not available — cannot write IR YAML.\n"
            "Install with: pip install pyyaml\n"
            "Or use ADS Python which bundles PyYAML."
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{ir.cell_name.lower()}_ir.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(_ir_to_dict(ir), f, default_flow_style=False, sort_keys=False)
    return out_path


# ── CLI usage ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from translator.parser import parse_research_netlist

    if len(sys.argv) < 2:
        print("Usage: python ir_builder.py <research_netlist.net> [output_dir]")
        sys.exit(1)

    net_path = Path(sys.argv[1])
    out_dir  = Path(sys.argv[2]) if len(sys.argv) > 2 else net_path.parent

    parse_result = parse_research_netlist(net_path)
    ir = build_ir(parse_result)

    print(f"Cell:          {ir.cell_name}")
    print(f"Phase req:     {ir.phase_required}")
    print(f"Ports:         {[p.name for p in ir.ports]}")
    print(f"Components:    {ir.metadata.component_count}")
    print(f"  series={ir.metadata.series_count}  shunt={ir.metadata.shunt_count}"
          f"  tline={ir.metadata.tline_count}  switch={ir.metadata.switch_count}")
    print(f"Backbone:      {ir.graph.backbone}")
    print(f"Shunt branches:{[(b.tap_node, b.component_id) for b in ir.graph.shunt_branches]}")
    print(f"Warnings:      {len(ir.metadata.warnings)}")
    for w in ir.metadata.warnings:
        print(f"  {w}")

    out_path = write_ir(ir, out_dir)
    print(f"\nIR written: {out_path}")
