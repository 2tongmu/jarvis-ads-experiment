"""
translator/placement_engine.py
===============================
Stage 3a — Placement engine for the net2ads pipeline.

Computes (x, y, angle) for every component in a BuildPlan and writes
the placement plan to disk. The placement plan is then consumed by the
ADS Python API calls that build the actual schematic.

Coordinate conventions (topology-preserving, netlist-driven):
  - Signal path: y = 0.0, left to right
  - GND level: y = -1.0
  - Port 1 (left):  x = 1.375  (PORT_LEFT_X)
  - Series start:   x = 2.875  (FIRST_SHUNT_X — all series start here, no pre-shunt gap)
  - Component width: 1.0 unit (P1 to P2 of a series component)
  - Component spacing: 2.0 units between consecutive series origins
  - Shunt x: backbone_node_x[tap_node] — the P2 x of the upstream series component
    (the gap between consecutive series components, confirmed topology-correct)
  - Wire segments: per-net routing — one horizontal segment per net spanning
    distinct x positions; co-located pins auto-connect (no wire emitted)

Angle conventions (confirmed from ads_build_spdt_pdk.py mkR/mkC/mkGnd):
  R/L/C series:   0.0
  C/R/L shunt:   -90.0
  GND:           -90.0
  TLIN:           0.0

Usage:
    from translator.placement_engine import compute_placement, write_placement, build_ads_schematic
    placement = compute_placement(build_plan)
    write_placement(placement, output_dir=Path("examples/rc_series_shunt"))
    build_ads_schematic(placement, workspace=..., lib_name=...)
"""

import datetime
import warnings as _warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from translator.ads_mapper import BuildPlan, BuildInstance, BuildPort


# ── Placement constants ────────────────────────────────────────────────────────
PORT_LEFT_X       = 1.375   # port 1 pin x (net_to_ads_cell.py _PORT_LEFT)
FIRST_SHUNT_X     = 2.875   # first series component x (all series start here)
COMPONENT_SPACING = 2.0     # units between consecutive series component origins
SIGNAL_Y          = 0.0     # all signal-path components at y=0
GND_Y             = -1.0    # GND symbols at y=-1

# Angle conventions (confirmed from ads_build_spdt_pdk.py)
ANGLE_SERIES  = 0.0
ANGLE_SHUNT   = -90.0
ANGLE_GND     = -90.0
ANGLE_TLINE   = 0.0

# Component width: x-distance from a series component's P1 to its P2 (confirmed bbox).
COMP_WIDTH    = 1.0

# ── Ground node set (local copy — avoids importing from ir_builder) ────────────
_GROUND_NODES = frozenset({"0", "gnd", "ground", "vss"})


def _is_ground_node(node: str) -> bool:
    """Return True if the node name represents a ground reference."""
    return node.strip().lower() in _GROUND_NODES


# ── Placed instance ────────────────────────────────────────────────────────────

@dataclass
class PlacedInstance:
    id: str
    ads_lib: str
    ads_cell: str
    ads_view: str
    x: float
    y: float
    angle: float
    params: dict
    role: str


@dataclass
class PlacedPort:
    name: str
    node: str
    number: int
    x: float
    y: float


@dataclass
class PlacedWire:
    id: str
    points: list        # list of (x, y) tuples
    note: str


@dataclass
class PlacementPlan:
    cell_name: str
    source_buildplan: str
    generation_timestamp: str
    ports: list             # list of PlacedPort
    instances: list         # list of PlacedInstance
    wires: list             # list of PlacedWire
    warnings: list


# ── SPDT layout constants (from WIN_PP1029_core.yaml confirmed pin offsets) ────
PATH_A_Y          =  2.0   # Path A signal rail y
PATH_B_Y          = -2.0   # Path B signal rail y
# FET origin offsets (angle=90 series, angle=0 shunt) — both -0.5 below signal rail
FET_ORIGIN_DY     = -0.5   # origin is 0.5 units below path_y for both FET types


# ── Angle assignment ───────────────────────────────────────────────────────────

def _angle_for(inst: BuildInstance) -> float:
    """Return placement angle for a BuildInstance based on role and element type."""
    if inst.role == "gnd":
        return ANGLE_GND
    if inst.role == "shunt":
        return ANGLE_SHUNT
    if inst.role == "tline":
        return ANGLE_TLINE
    if inst.role == "vsource":
        return ANGLE_SHUNT   # V_DC: vertical (P1 on signal rail, P2 below → GND companion at y-1)
    if inst.role == "fet_series":
        return 90.0    # drain left, source right, gate below — WIN_PP1029_core.yaml
    if inst.role == "fet_shunt":
        return 0.0     # drain at signal tap, source down — WIN_PP1029_core.yaml
    if inst.role == "fetbias":
        return 0.0     # VCTRL left, GATE right
    return ANGLE_SERIES   # series, switch (ON=R), default


def _is_spdt_topology(build_plan: BuildPlan) -> bool:
    """Return True if this build plan describes a 3-port SPDT with FET elements."""
    has_fets = any(i.role in ("fet_series", "fet_shunt") for i in build_plan.instances)
    has_3_rf_ports = sum(
        1 for p in build_plan.ports
        if not p.name.startswith("VCTRL")
    ) >= 3
    return has_fets and has_3_rf_ports


def _partition_spdt_paths(
    build_plan: BuildPlan,
) -> tuple:
    """
    Partition non-FET/non-fetbias instances into (common, path_a, path_b) by
    BFS from each RF output port (P2=path_a, P3=path_b).

    Supports multi-stage topologies (multiple series FETs per path): the SPDT
    junction node (N_COM) is detected dynamically and used as the BFS boundary
    so that elements between cascaded series FETs are correctly assigned to
    their path rather than the common section.

    Returns:
        common_insts   : list[BuildInstance] — P1 → branch point
        path_a_insts   : list[BuildInstance] — branch → P2 (series + shunts)
        path_b_insts   : list[BuildInstance] — branch → P3 (series + shunts)
        path_a_shunts  : list[BuildInstance] — shunt branches on Path A
        path_b_shunts  : list[BuildInstance] — shunt branches on Path B
    """
    from collections import deque

    # RF ports: P1, P2, P3 (exclude VCTRL ports)
    rf_ports = [p for p in build_plan.ports if not p.name.startswith("VCTRL")]
    port_by_number = {p.number: p for p in rf_ports}
    p1_node = port_by_number.get(1, rf_ports[0]).node if rf_ports else None
    p2_node = port_by_number.get(2, rf_ports[1]).node if len(rf_ports) > 1 else None
    p3_node = port_by_number.get(3, rf_ports[2]).node if len(rf_ports) > 2 else None

    # Only partition regular instances (R, L, C, switch-role) — not FETs/fetbias
    regular = [
        i for i in build_plan.instances
        if i.role in ("series", "shunt", "switch", "gnd")
    ]
    all_series_fets = [i for i in build_plan.instances if i.role == "fet_series"]

    # ── Detect N_COM (SPDT junction): forward BFS from P1 through passive/switch
    # elements only. N_COM = the node at the end of the common section that
    # connects to one or more series FETs.  For single-stage SPDT this is the
    # one node shared by SW_SERIES_A and SW_SERIES_B; for multi-stage it is the
    # node shared by SW_SERIES_A1 and SW_SERIES_B1 (the first FET of each path).
    n_com_node: str = None
    if p1_node and all_series_fets:
        passive_adj: dict = {}
        for inst in regular:
            if inst.role in ("series", "switch") and len(inst.nodes) >= 2:
                n0, n1 = inst.nodes[0], inst.nodes[1]
                passive_adj.setdefault(n0, []).append(n1)
                passive_adj.setdefault(n1, []).append(n0)
        visited_p1 = {p1_node}
        queue_p1 = deque([p1_node])
        while queue_p1:
            n = queue_p1.popleft()
            for nb in passive_adj.get(n, []):
                if nb not in visited_p1:
                    visited_p1.add(nb)
                    queue_p1.append(nb)
        # N_COM = node reachable from P1 (passive only) that also appears in a series FET
        fet_nodes = {nd for f in all_series_fets for nd in f.nodes}
        candidates = visited_p1 & fet_nodes - {p1_node}
        if candidates:
            n_com_node = next(iter(candidates))

    # ── Build full adjacency (including fet_series and fet_shunt) for path BFS.
    # Using N_COM as the stop boundary prevents path A/B BFS from bleeding through
    # the common section and absorbing each other's elements.
    full_traversal = regular + [
        i for i in build_plan.instances
        if i.role in ("fet_series", "fet_shunt")
    ]
    adj: dict = {}
    for inst in full_traversal:
        if inst.role not in ("gnd",) and len(inst.nodes) >= 2:
            n0, n1 = inst.nodes[0], inst.nodes[1]
            adj.setdefault(n0, []).append((inst, n1))
            adj.setdefault(n1, []).append((inst, n0))

    def _reachable_from(start_node: str, exclude_nodes: set) -> tuple:
        """
        BFS from start_node (excluding certain nodes and ground nodes).
        Ground nodes are never traversed — they are shared across all paths and
        would otherwise allow BFS to bleed from one path's shunt resistor through
        GND into the other path's shunt resistor (N_AST→"0"→N_BST contamination).
        Returns (visited_inst_ids: set, visited_nodes: set).
        """
        visited_nodes = {start_node}
        visited_insts = set()
        queue = deque([start_node])
        while queue:
            node = queue.popleft()
            for inst, neighbor in adj.get(node, []):
                if (neighbor not in exclude_nodes
                        and neighbor not in visited_nodes
                        and not _is_ground_node(neighbor)):
                    visited_nodes.add(neighbor)
                    visited_insts.add(inst.id)
                    queue.append(neighbor)
                elif inst.id not in visited_insts and node not in exclude_nodes:
                    visited_insts.add(inst.id)
        return visited_insts, visited_nodes

    # Path A = reachable from P2, stopping at P1, P3, and N_COM
    exclude_a = {p1_node, p3_node}
    if n_com_node:
        exclude_a.add(n_com_node)
    path_a_ids, path_a_nodes = _reachable_from(p2_node, exclude_a) if p2_node else (set(), set())

    # Path B = reachable from P3, stopping at P1, P2, and N_COM
    exclude_b = {p1_node, p2_node}
    if n_com_node:
        exclude_b.add(n_com_node)
    path_b_ids, path_b_nodes = _reachable_from(p3_node, exclude_b) if p3_node else (set(), set())

    def _shunt_tap(inst) -> str:
        """Return the non-ground tap node of a shunt instance."""
        return next((n for n in inst.nodes if not _is_ground_node(n)), inst.nodes[0] if inst.nodes else "")

    common_insts = []
    path_a_series, path_a_shunts = [], []
    path_b_series, path_b_shunts = [], []

    for inst in regular:
        if inst.role == "gnd":
            continue  # handled separately via companion shunt
        if inst.role == "shunt":
            # Classify shunt by its tap node — the non-ground node must be
            # reachable from the output port (not just traversed as a series inst).
            tap = _shunt_tap(inst)
            if tap in path_a_nodes:
                path_a_shunts.append(inst)
            elif tap in path_b_nodes:
                path_b_shunts.append(inst)
            else:
                common_insts.append(inst)
        else:
            in_a = inst.id in path_a_ids
            in_b = inst.id in path_b_ids
            if in_a:
                path_a_series.append(inst)
            elif in_b:
                path_b_series.append(inst)
            else:
                common_insts.append(inst)

    return common_insts, path_a_series, path_a_shunts, path_b_series, path_b_shunts


def _order_chain(insts: list, start_node: str, end_node: str) -> list:
    """
    Order series instances as a linear chain from start_node to end_node.
    Uses greedy walk through adjacency — returns instances in signal-flow order.
    Returns empty list if start_node is not found in any instance's nodes.
    """
    adj: dict = {}
    for inst in insts:
        if len(inst.nodes) >= 2:
            n0, n1 = inst.nodes[0], inst.nodes[1]
            adj.setdefault(n0, []).append((inst, n1))
            adj.setdefault(n1, []).append((inst, n0))

    ordered = []
    current = start_node
    visited: set = set()
    while current != end_node:
        found = False
        for inst, next_node in adj.get(current, []):
            if inst.id not in visited:
                ordered.append(inst)
                visited.add(inst.id)
                current = next_node
                found = True
                break
        if not found:
            break
    return ordered


def _assign_spdt_coordinates(
    build_plan: BuildPlan,
    warnings: list,
) -> tuple:
    """
    Compute placement for a 3-port SPDT with PDK FETs and fetbias subcells.

    Layout (from WIN_PP1029_core.yaml placement_recipes, SPDT multi-rail):
      y=0       : common section (P1 → N_COM via RIN_PAD, LIN_PAD)
      y=PATH_A_Y: Path A signal rail (N_COM → P2)
      y=PATH_B_Y: Path B signal rail (N_COM → P3)

    Series FET (angle=90) origin formula: (branch_x+0.5, path_y-0.5)
      → drain=(branch_x, path_y), source=(branch_x+1.0, path_y), gate=origin
    Shunt FET (angle=0) origin formula: (tap_x-0.5, path_y-0.5)
      → drain=(tap_x, path_y), source=(tap_x, path_y-1.0), gate=origin

    fetbias origin = (gate_x-2.0, gate_y)  so GATE pin lands at FET gate
    VCTRL port co-located with fetbias origin (VCTRL pin is at (0,0))
    RTERM placed at shunt FET source (tap_x, path_y-1.0)
    GND companion 1 unit below RTERM
    """
    rf_ports = [p for p in build_plan.ports if not p.name.startswith("VCTRL")]
    vctrl_ports = [p for p in build_plan.ports if p.name.startswith("VCTRL")]
    port_by_number = {p.number: p for p in rf_ports}
    vctrl_port_map = {p.node: p for p in vctrl_ports}

    (common_insts, path_a_series, path_a_shunts,
     path_b_series, path_b_shunts) = _partition_spdt_paths(build_plan)

    placed_instances: list = []
    placed_ports: list = []

    # ── Common section layout (y=0) ───────────────────────────────────────────
    x = FIRST_SHUNT_X
    for inst in common_insts:
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=round(x, 4), y=SIGNAL_Y,
            angle=_angle_for(inst), params=inst.params, role=inst.role,
        ))
        x += COMPONENT_SPACING
    # branch_x = P2 pin of last common inst = x of N_COM node on y=0 rail
    branch_x = round(x - COMPONENT_SPACING + COMP_WIDTH, 4)

    # ── Classify FETs into path A / path B ───────────────────────────────────
    all_fets    = [i for i in build_plan.instances if i.role in ("fet_series", "fet_shunt")]
    all_fetbias = [i for i in build_plan.instances if i.role == "fetbias"]

    def _fets_for_path(path_series_list, path_shunts_list):
        """Return (series_fets, shunt_fets) whose nodes overlap with this path."""
        path_nodes: set = set()
        for inst in path_series_list + path_shunts_list:
            path_nodes.update(inst.nodes)
        ser = [f for f in all_fets if f.role == "fet_series"
               and any(n in path_nodes for n in f.nodes)]
        sh  = [f for f in all_fets if f.role == "fet_shunt"
               and any(n in path_nodes for n in f.nodes)]
        return ser, sh

    ser_fets_a, sh_fets_a = _fets_for_path(path_a_series, path_a_shunts)
    ser_fets_b, sh_fets_b = _fets_for_path(path_b_series, path_b_shunts)

    # ── Path layout inner function ────────────────────────────────────────────
    p2_node = port_by_number[2].node if 2 in port_by_number else None
    p3_node = port_by_number[3].node if 3 in port_by_number else None

    def _layout_spdt_path(
        series_passives, shunt_passives, series_fets_p, shunt_fets_p,
        path_y, port_out_node,
    ):
        """
        Layout one SPDT signal path.

        Supports multi-stage topologies with multiple series FETs:
        - First series FET placed at the SPDT junction (branch_x).
        - Additional series FETs placed in the 1-unit gap between consecutive
          passives, at the position where their drain node meets a passive P2.

        Returns (placed, end_x, gate_pos_first_ser, gate_pos_shunt, all_ser_gate_positions)
          all_ser_gate_positions: {fet_id: (gate_x, gate_y)} for ALL series FETs.
        """
        placed = []
        node_pos: dict = {}   # {node_name: (x, y)} for wire computation

        # ── First series FET (angle=90) at SPDT junction ──────────────────────
        # origin=(branch_x+0.5, path_y-0.5) → drain=(branch_x, path_y), source=(branch_x+1, path_y)
        ser_fet = series_fets_p[0] if series_fets_p else None
        gate_pos_ser = None
        all_ser_gate_positions: dict = {}
        if ser_fet:
            org_x = round(branch_x + 0.5, 4)
            org_y = round(path_y - 0.5, 4)
            placed.append(PlacedInstance(
                id=ser_fet.id, ads_lib=ser_fet.ads_lib, ads_cell=ser_fet.ads_cell,
                ads_view=ser_fet.ads_view, x=org_x, y=org_y,
                angle=90.0, params=ser_fet.params, role=ser_fet.role,
            ))
            gate_pos_ser = (org_x, org_y)
            all_ser_gate_positions[ser_fet.id] = gate_pos_ser
            node_pos[ser_fet.nodes[0]] = (branch_x,       round(path_y, 4))   # drain = N_COM
            node_pos[ser_fet.nodes[1]] = (branch_x + 1.0, round(path_y, 4))   # source = N_A1/N_B1
            source_node = ser_fet.nodes[1]
        else:
            source_node = None

        # ── Build ordered chain: passives + extra series FETs ────────────────
        # Include extra series FETs in the chain so _order_chain can traverse
        # through FET-to-passive boundaries in multi-stage topologies.
        extra_ser_fets = series_fets_p[1:]
        all_chain_elements = list(series_passives) + list(extra_ser_fets)
        if source_node and port_out_node:
            ordered_elements = _order_chain(all_chain_elements, source_node, port_out_node)
        else:
            ordered_elements = list(series_passives)
        if not ordered_elements and all_chain_elements:
            ordered_elements = list(series_passives)
            warnings.append(
                f"[WARN] Could not order path elements from '{source_node}' to "
                f"'{port_out_node}' — using buildplan order"
            )

        # Walk the chain: passives advance px; extra FETs occupy the gap at current px.
        # After advancing for a passive, px points to the next passive's P1.
        # An extra FET between two passives:
        #   drain  = (px - COMP_WIDTH, path_y)  [= prev passive P2]
        #   source = (px,              path_y)  [= next passive P1, co-located]
        #   origin = (px - 0.5,        path_y - 0.5)
        # px does NOT advance for a FET — the next passive starts at the same px.
        px = round(branch_x + 1.0, 4)
        for elem in ordered_elements:
            if elem.role == "fet_series":
                extra_org_x = round(px - 0.5, 4)
                extra_org_y = round(path_y - 0.5, 4)
                placed.append(PlacedInstance(
                    id=elem.id, ads_lib=elem.ads_lib, ads_cell=elem.ads_cell,
                    ads_view=elem.ads_view, x=extra_org_x, y=extra_org_y,
                    angle=90.0, params=elem.params, role=elem.role,
                ))
                all_ser_gate_positions[elem.id] = (extra_org_x, extra_org_y)
                node_pos.setdefault(elem.nodes[0], (round(px - COMP_WIDTH, 4), round(path_y, 4)))
                node_pos.setdefault(elem.nodes[1], (round(px,             4), round(path_y, 4)))
                # px does NOT advance — next passive is co-located with FET source
            else:
                placed.append(PlacedInstance(
                    id=elem.id, ads_lib=elem.ads_lib, ads_cell=elem.ads_cell,
                    ads_view=elem.ads_view, x=round(px, 4), y=round(path_y, 4),
                    angle=ANGLE_SERIES, params=elem.params, role=elem.role,
                ))
                # Use setdefault: first assignment wins (P2 of previous comp = correct tap x)
                node_pos.setdefault(elem.nodes[0], (round(px, 4),              round(path_y, 4)))
                node_pos.setdefault(elem.nodes[1], (round(px + COMP_WIDTH, 4), round(path_y, 4)))
                px += COMPONENT_SPACING

        end_x = round(px - COMPONENT_SPACING + COMP_WIDTH, 4)

        # ── Shunt FET (angle=0) ───────────────────────────────────────────────
        # origin=(tap_x-0.5, path_y-0.5) → drain=(tap_x, path_y), source=(tap_x, path_y-1.0)
        sh_fet = shunt_fets_p[0] if shunt_fets_p else None
        gate_pos_sh = None
        if sh_fet:
            tap_node = sh_fet.nodes[0]    # N_A3 / N_B3 — signal rail tap
            src_node = sh_fet.nodes[1]    # N_AST / N_BST — to RTERM
            tap_pos = node_pos.get(tap_node)
            if tap_pos is None:
                warnings.append(
                    f"[WARN] shunt FET '{sh_fet.id}' tap '{tap_node}' not in node_pos"
                )
                tap_x = end_x
            else:
                tap_x = tap_pos[0]
            org_x = round(tap_x - 0.5, 4)
            org_y = round(path_y - 0.5, 4)
            placed.append(PlacedInstance(
                id=sh_fet.id, ads_lib=sh_fet.ads_lib, ads_cell=sh_fet.ads_cell,
                ads_view=sh_fet.ads_view, x=org_x, y=org_y,
                angle=0.0, params=sh_fet.params, role=sh_fet.role,
            ))
            gate_pos_sh = (org_x, org_y)
            # source = (tap_x, path_y - 1.0)
            node_pos[src_node] = (round(tap_x, 4), round(path_y - 1.0, 4))

        # ── Shunt passives (RTERM) at shunt FET source position ───────────────
        for inst in shunt_passives:
            tap = next((n for n in inst.nodes if not _is_ground_node(n)), None)
            tap_pos = node_pos.get(tap) if tap else None
            if tap_pos:
                rterm_x, rterm_y = tap_pos
            else:
                rterm_x = round(end_x, 4)
                rterm_y = round(path_y - 1.0, 4)
                warnings.append(
                    f"[WARN] RTERM '{inst.id}': tap '{tap}' not found, using fallback position"
                )
            placed.append(PlacedInstance(
                id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
                ads_view=inst.ads_view, x=round(rterm_x, 4), y=round(rterm_y, 4),
                angle=ANGLE_SHUNT, params=inst.params, role=inst.role,
            ))
            # GND companion 1 unit below RTERM
            gnd_id = f"GND_{inst.id}"
            gnd = next((i for i in build_plan.instances if i.id == gnd_id), None)
            if gnd:
                placed.append(PlacedInstance(
                    id=gnd.id, ads_lib=gnd.ads_lib, ads_cell=gnd.ads_cell,
                    ads_view=gnd.ads_view, x=round(rterm_x, 4),
                    y=round(rterm_y - 1.0, 4),
                    angle=ANGLE_GND, params=gnd.params, role=gnd.role,
                ))

        return placed, end_x, gate_pos_ser, gate_pos_sh, all_ser_gate_positions

    # ── Layout both paths ─────────────────────────────────────────────────────
    placed_a, end_x_a, ser_gate_a, sh_gate_a, ser_gate_map_a = _layout_spdt_path(
        path_a_series, path_a_shunts, ser_fets_a, sh_fets_a, PATH_A_Y, p2_node,
    )
    placed_b, end_x_b, ser_gate_b, sh_gate_b, ser_gate_map_b = _layout_spdt_path(
        path_b_series, path_b_shunts, ser_fets_b, sh_fets_b, PATH_B_Y, p3_node,
    )
    placed_instances.extend(placed_a)
    placed_instances.extend(placed_b)

    # ── fetbias: origin=(gate_x-2.0, gate_y) so GATE pin lands at FET gate ───
    # fetbias symbol: VCTRL pin at (0,0)=origin, GATE pin at (2.0,0) from origin.
    gate_pos_map: dict = {}
    gate_pos_map.update(ser_gate_map_a)   # all series FETs in path A
    gate_pos_map.update(ser_gate_map_b)   # all series FETs in path B
    if sh_fets_a and sh_gate_a: gate_pos_map[sh_fets_a[0].id] = sh_gate_a
    if sh_fets_b and sh_gate_b: gate_pos_map[sh_fets_b[0].id] = sh_gate_b

    for inst in all_fetbias:
        fet_id = inst.id.replace("BIAS_", "Q_", 1)   # BIAS_SW_SERIES_A → Q_SW_SERIES_A
        gate_pos = gate_pos_map.get(fet_id)
        if gate_pos is None:
            warnings.append(f"[WARN] fetbias '{inst.id}': no gate position for '{fet_id}'")
            gate_x, gate_y = FIRST_SHUNT_X, SIGNAL_Y
        else:
            gate_x, gate_y = gate_pos

        bias_x = round(gate_x - 2.0, 4)
        bias_y = round(gate_y, 4)
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=bias_x, y=bias_y,
            angle=0.0, params=inst.params, role=inst.role,
        ))

        # VCTRL port co-located at fetbias origin — VCTRL pin is at (0,0)
        vctrl_node = inst.nodes[0] if inst.nodes else None
        vctrl_port = vctrl_port_map.get(vctrl_node)
        if vctrl_port:
            placed_ports.append(PlacedPort(
                name=vctrl_port.name, node=vctrl_port.node, number=vctrl_port.number,
                x=bias_x, y=bias_y,
            ))

    # ── RF port positions ─────────────────────────────────────────────────────
    placed_ports.insert(0, PlacedPort(
        name=port_by_number[1].name, node=port_by_number[1].node, number=1,
        x=PORT_LEFT_X, y=SIGNAL_Y,
    ))
    if p2_node and 2 in port_by_number:
        placed_ports.insert(1, PlacedPort(
            name=port_by_number[2].name, node=p2_node, number=2,
            x=round(end_x_a, 4), y=round(PATH_A_Y, 4),
        ))
    if p3_node and 3 in port_by_number:
        placed_ports.insert(2, PlacedPort(
            name=port_by_number[3].name, node=p3_node, number=3,
            x=round(end_x_b, 4), y=round(PATH_B_Y, 4),
        ))

    # ── Wire routing ──────────────────────────────────────────────────────────
    placed_wires = _route_spdt_wires(
        build_plan, placed_instances, placed_ports,
        branch_x, PATH_A_Y, PATH_B_Y,
    )

    return placed_ports, placed_instances, placed_wires


def _route_spdt_wires(
    build_plan, placed_instances, placed_ports,
    branch_x, path_a_y, path_b_y,
) -> list:
    """
    Generate wire segments for the SPDT schematic.

    Wire categories:
      1. Horizontal per-net segments (auto-derived from component pin positions):
         - Common section: P1 wire, N_IN wire
         - Path rail gaps: N_A2, N_A3, N_B2, N_B3 horizontal bridges
         - N_A1/N_B1 co-located with series FET source (no wire needed)
         - N_AST/N_BST co-located with RTERM P1 and shunt FET source (no wire needed)
         - P2/P3 co-located with ROUT P2 (no wire needed)
      2. N_COM vertical wires: (branch_x, 0) → (branch_x, ±path_y)

    FET pin offsets (from WIN_PP1029_core.yaml, confirmed probe 2026-04-06):
      angle=90 (series): drain=(origin.x-0.5, origin.y+0.5), source=(origin.x+0.5, origin.y+0.5)
      angle=0  (shunt):  drain=(origin.x+0.5, origin.y+0.5), source=(origin.x+0.5, origin.y-0.5)
    """
    net_xs_by_y: dict = {}   # {node: {y_level: {x_pos, ...}}}
    inst_map = {pi.id: pi for pi in placed_instances}

    # ── Ports (exclude VCTRL — co-located with fetbias origin, no wire) ───────
    for port in placed_ports:
        if port.name.startswith("VCTRL"):
            continue
        net_xs_by_y.setdefault(port.node, {}).setdefault(
            round(port.y, 6), set()
        ).add(round(port.x, 6))

    # ── Series/shunt passives ─────────────────────────────────────────────────
    for bi in build_plan.instances:
        pi = inst_map.get(bi.id)
        if pi is None or bi.role in ("gnd", "fetbias"):
            continue
        if bi.role in ("series", "switch") and len(bi.nodes) >= 2:
            n0, n1 = bi.nodes[0], bi.nodes[1]
            if not _is_ground_node(n0):
                net_xs_by_y.setdefault(n0, {}).setdefault(
                    round(pi.y, 6), set()
                ).add(round(pi.x, 6))
            if not _is_ground_node(n1):
                net_xs_by_y.setdefault(n1, {}).setdefault(
                    round(pi.y, 6), set()
                ).add(round(pi.x + COMP_WIDTH, 6))
        elif bi.role == "shunt":
            # Tap (non-ground) pin only — GND side is handled by place_ground()
            tap = next((n for n in bi.nodes if not _is_ground_node(n)), None)
            if tap:
                net_xs_by_y.setdefault(tap, {}).setdefault(
                    round(pi.y, 6), set()
                ).add(round(pi.x, 6))

    # ── FET pin positions (angle=90 series, angle=0 shunt) ───────────────────
    for bi in build_plan.instances:
        pi = inst_map.get(bi.id)
        if pi is None or len(bi.nodes) < 2:
            continue
        if bi.role == "fet_series":   # angle=90
            drain_x = round(pi.x - 0.5, 6)
            drain_y = round(pi.y + 0.5, 6)
            src_x   = round(pi.x + 0.5, 6)
            src_y   = round(pi.y + 0.5, 6)   # same y as drain (signal rail)
        elif bi.role == "fet_shunt":  # angle=0
            drain_x = round(pi.x + 0.5, 6)
            drain_y = round(pi.y + 0.5, 6)
            src_x   = round(pi.x + 0.5, 6)
            src_y   = round(pi.y - 0.5, 6)   # below drain
        else:
            continue
        drain_node, src_node = bi.nodes[0], bi.nodes[1]
        if not _is_ground_node(drain_node):
            net_xs_by_y.setdefault(drain_node, {}).setdefault(drain_y, set()).add(drain_x)
        if not _is_ground_node(src_node):
            net_xs_by_y.setdefault(src_node, {}).setdefault(src_y, set()).add(src_x)

    # ── Emit one horizontal wire per net per y-level (span > 0) ──────────────
    wires = []
    wire_idx = 0
    for node_name, y_map in sorted(net_xs_by_y.items()):
        for y_level, xs in sorted(y_map.items()):
            xs_sorted = sorted(xs)
            x1, x2 = xs_sorted[0], xs_sorted[-1]
            if abs(x2 - x1) < 1e-9:
                continue  # co-located pins — ADS auto-connects, no wire needed
            wires.append(PlacedWire(
                id=f"wire_{wire_idx}",
                points=[(round(x1, 4), round(y_level, 4)),
                        (round(x2, 4), round(y_level, 4))],
                note=f"net '{node_name}' y={y_level}",
            ))
            wire_idx += 1

    # ── N_COM vertical wires: connect y=0 common rail to both path rails ──────
    # LIN_PAD P2 is at (branch_x, 0.0); series FET drains are at (branch_x, ±path_y)
    wires.append(PlacedWire(
        id=f"wire_{wire_idx}",
        points=[(round(branch_x, 4), round(SIGNAL_Y, 4)),
                (round(branch_x, 4), round(path_a_y, 4))],
        note="N_COM: y=0 -> path_a",
    ))
    wire_idx += 1
    wires.append(PlacedWire(
        id=f"wire_{wire_idx}",
        points=[(round(branch_x, 4), round(SIGNAL_Y, 4)),
                (round(branch_x, 4), round(path_b_y, 4))],
        note="N_COM: y=0 -> path_b",
    ))
    wire_idx += 1

    return wires


# ── Angle assignment ──────────────────────────────────────────────────────���────


# ── Backbone ordering ──────────────────────────────────────────────────────────

def _build_backbone_order(build_plan: BuildPlan) -> tuple:
    """
    Traverse series/tline/switch components from port1.node to port2.node.

    Returns:
        ordered_backbone : list of (BuildInstance, entry_node, exit_node)
                           in signal-flow order from port1 to port2
        backbone_node_x  : dict mapping each backbone node name -> x position
                           on the signal path (y=0 plane).

    Uses setdefault so intermediate nodes keep the FIRST (exit-side) x value —
    this places shunts at the gap between two series components, not at the
    entry of the next series component.

    Example (t_network_lcl):
        backbone = [(L1_SER, "P1", "N_MID"), (L2_SER, "N_MID", "P2")]
        backbone_node_x = {"P1": 1.375, "N_MID": 3.875, "P2": 5.875}
        -> C1_SH tap "N_MID": placed at x=3.875
        -> L1_SER at x=2.875, L2_SER at x=4.875

    Example (rc_series_shunt):
        backbone = [(R1_SER, "P1", "N_OUT"), (R_TIE, "N_OUT", "P2")]
        backbone_node_x = {"P1": 1.375, "N_OUT": 3.875, "P2": 5.875}
        -> C1_SH tap "N_OUT": placed at x=3.875
    """
    port1_node = next((p.node for p in build_plan.ports if p.number == 1), None)
    port2_node = next((p.node for p in build_plan.ports if p.number == 2), None)

    series_insts = [
        i for i in build_plan.instances
        if i.role in ("series", "tline", "switch")
    ]

    # Build adjacency dict: node_name -> [(BuildInstance, other_node), ...]
    # O(n) build; O(1) lookup per step → total walk is O(n).
    adj: dict = {}
    for inst in series_insts:
        if len(inst.nodes) < 2:
            continue
        n0, n1 = inst.nodes[0], inst.nodes[1]
        adj.setdefault(n0, []).append((inst, n1))
        adj.setdefault(n1, []).append((inst, n0))

    # Greedy walk from port1_node — O(n) total
    ordered: list = []
    current_node = port1_node
    visited_insts: set = set()

    while current_node != port2_node:
        found = False
        for inst, next_node in adj.get(current_node, []):
            if inst.id not in visited_insts:
                ordered.append((inst, current_node, next_node))
                visited_insts.add(inst.id)
                current_node = next_node
                found = True
                break
        if not found:
            break  # disconnected graph or unsupported topology

    # Compute backbone_node_x: each signal node -> its x on the signal path.
    # Port1 pin is at PORT_LEFT_X; series components start at FIRST_SHUNT_X.
    # Use setdefault so that intermediate nodes keep the FIRST (exit-side) x value.
    backbone_node_x: dict = {port1_node: PORT_LEFT_X}
    x = FIRST_SHUNT_X
    for inst, entry, exit_ in ordered:
        backbone_node_x.setdefault(entry, x)                # series P1 position
        backbone_node_x.setdefault(exit_, x + COMP_WIDTH)  # series P2 position
        x += COMPONENT_SPACING

    return ordered, backbone_node_x


# ── Per-net wire routing ───────────────────────────────────────────────────────

def _route_wires_from_netlist(
    build_plan: BuildPlan,
    placed_instances: list,
    placed_ports: list,
    ordered_backbone: list,
) -> list:
    """
    Route one horizontal wire segment per net that connects >= 2 distinct x positions.

    Algorithm:
      1. Collect all signal-path (y=0) pin x-positions per net from ports and
         placed instances. Ground-side shunt pins are excluded — vertical wires
         to GND are drawn by place_ground() in schematic_ops.
      2. For each net, if max_x > min_x, emit one wire from (min_x, 0) to (max_x, 0).

    Co-located pins on the same net (same x) need no wire — ADS auto-connects them.
    This produces port-to-series wires, inter-series gap wires, and shunt-tap wires
    without any hard-coded coordinate assumptions.

    Returns list of PlacedWire.
    """
    # Build lookup: backbone direction for each series component
    backbone_dir = {
        bi.id: (entry, exit_)
        for bi, entry, exit_ in ordered_backbone
    }

    # {node_name: set of x_positions} from ports and placed instances
    net_xs: dict = {}

    for port in placed_ports:
        net_xs.setdefault(port.node, set()).add(round(port.x, 6))

    inst_by_id = {pi.id: pi for pi in placed_instances}

    for bi in build_plan.instances:
        pi = inst_by_id.get(bi.id)
        if pi is None or bi.role == "gnd":
            continue

        if bi.role in ("series", "tline", "switch"):
            entry, exit_ = backbone_dir.get(bi.id, (None, None))
            if entry is None and len(bi.nodes) >= 2:
                entry, exit_ = bi.nodes[0], bi.nodes[1]
            if entry and not _is_ground_node(entry):
                net_xs.setdefault(entry, set()).add(round(pi.x, 6))
            if exit_ and not _is_ground_node(exit_):
                net_xs.setdefault(exit_, set()).add(round(pi.x + COMP_WIDTH, 6))

        elif bi.role in ("shunt", "vsource"):
            # Only P1 (signal node) contributes to signal-path routing.
            # P2 (ground) is connected via GND companion in placement — omit here.
            # vsource (e.g. V_DC: N_VDD→'0'): P1 at origin, P2 below — same convention.
            tap_node = next(
                (n for n in bi.nodes if not _is_ground_node(n)), None
            )
            if tap_node:
                net_xs.setdefault(tap_node, set()).add(round(pi.x, 6))

    # Emit one wire segment per net with a non-trivial x span
    placed_wires = []
    for wire_idx, (node_name, xs) in enumerate(sorted(net_xs.items())):
        xs_sorted = sorted(xs)
        x1, x2 = xs_sorted[0], xs_sorted[-1]
        if abs(x2 - x1) < 1e-9:
            continue  # all pins co-located — ADS auto-connects
        placed_wires.append(PlacedWire(
            id=f"wire_{wire_idx}",
            points=[(round(x1, 4), SIGNAL_Y), (round(x2, 4), SIGNAL_Y)],
            note=f"net '{node_name}': ({x1},{SIGNAL_Y})->({x2},{SIGNAL_Y})",
        ))

    return placed_wires


# ── Coordinate assignment ──────────────────────────────────────────────────────

def _assign_coordinates(
    build_plan: BuildPlan,
    warnings: list,
) -> tuple:
    """
    Assign (x, y) to each BuildInstance and each port.

    Strategy (topology-preserving, netlist-driven):
      1. Build backbone order via BFS/greedy walk from port1.node to port2.node.
         backbone_node_x maps each signal node -> its x on the signal path.
      2. Series components placed at FIRST_SHUNT_X + i * COMPONENT_SPACING.
      3. Shunt components placed at backbone_node_x[tap_node] — the exit x
         of the upstream series component, which is the correct topological
         tap position (gap between the two adjacent series components).
      4. GND symbols share x with their companion shunt component, at GND_Y.
      5. Port2 x = backbone_node_x[port2_node], co-locating with last series P2
         so no wire is needed for that connection (ADS auto-connects).
      6. Wires: per-net routing via _route_wires_from_netlist — one horizontal
         segment per net spanning distinct x positions; no hard-coded features.

    Returns (placed_ports, placed_instances, placed_wires).
    """
    shunts     = [i for i in build_plan.instances if i.role == "shunt"]
    gnds       = [i for i in build_plan.instances if i.role == "gnd"]
    switches   = [i for i in build_plan.instances if i.role == "switch"]
    vsources   = [i for i in build_plan.instances if i.role == "vsource"]
    series     = [i for i in build_plan.instances if i.role in ("series", "tline")]
    all_series = series + switches + vsources

    # ── Backbone order + signal-path node x-positions ─────────────────────────
    ordered_backbone, backbone_node_x = _build_backbone_order(build_plan)

    # ── Series x positions from backbone order ─────────────────────────────────
    series_x_map: dict = {}
    series_xs: list = []
    x = FIRST_SHUNT_X
    for inst, _entry, _exit in ordered_backbone:
        series_x_map[inst.id] = x
        series_xs.append(x)
        x += COMPONENT_SPACING

    # Fallback for series components not reached by BFS (should not happen)
    backbone_ids = {inst.id for inst, _, _ in ordered_backbone}
    for inst in all_series:
        if inst.id not in backbone_ids:
            fallback_x = (max(series_xs) + COMPONENT_SPACING) if series_xs else FIRST_SHUNT_X
            series_x_map[inst.id] = fallback_x
            series_xs.append(fallback_x)
            warnings.append(
                f"[WARN] Series '{inst.id}' not reached by backbone BFS — "
                f"using fallback x={fallback_x:.4f}"
            )

    # ── Shunt x from backbone tap nodes ───────────────────────────────────────
    shunt_x_map: dict = {}
    shunt_xs: list = []
    for inst in shunts:
        tap_node = next((n for n in inst.nodes if not _is_ground_node(n)), None)
        if tap_node and tap_node in backbone_node_x:
            shunt_x = backbone_node_x[tap_node]
        else:
            shunt_x = FIRST_SHUNT_X
            warnings.append(
                f"[WARN] Shunt '{inst.id}': tap node '{tap_node}' not in backbone. "
                "Using FIRST_SHUNT_X as fallback."
            )
        shunt_x_map[inst.id] = shunt_x
        shunt_xs.append(shunt_x)

    # ── GND companion positions (share x with companion shunt or vsource) ────────
    # GND id convention: "GND_{companion_id}" — match by stripping "GND_" prefix.
    # Shunt companions: GND at shunt tap x (P2 of angle=-90 component is 1 unit below P1).
    # Vsource companions: GND at series_x (P2 of V_DC at angle=0 is 1 unit below P1).
    gnd_x_map: dict = {}
    for gnd in gnds:
        companion_id = gnd.id[4:] if gnd.id.startswith("GND_") else gnd.id
        if companion_id in shunt_x_map:
            gnd_x_map[gnd.id] = shunt_x_map[companion_id]
        elif companion_id in series_x_map:
            gnd_x_map[gnd.id] = series_x_map[companion_id]
        else:
            gnd_x_map[gnd.id] = FIRST_SHUNT_X

    # ── Port x positions ──────────────────────────────────────────────────────
    left_x = PORT_LEFT_X
    port2_node = next((p.node for p in build_plan.ports if p.number == 2), None)
    right_x = backbone_node_x.get(port2_node) if port2_node else None
    if right_x is None:
        all_comp_xs = shunt_xs + series_xs
        right_x = (max(all_comp_xs) + COMP_WIDTH) if all_comp_xs else (left_x + 2.0)

    port_x_map: dict = {}
    for port in build_plan.ports:
        if port.number == 1:
            port_x_map[port.name] = left_x
        elif port.number == 2:
            port_x_map[port.name] = right_x
        else:
            # 3+ port circuits (Phase 3 SPDT) — not yet defined
            port_x_map[port.name] = right_x + (port.number - 2) * 2.0
            warnings.append(
                f"[WARN] Port {port.number} ('{port.name}'): 3-port placement not yet defined. "
                "Using estimated x position. See MEMORY.md OI-07."
            )

    # ── Build PlacedPort list ─────────────────────────────────────────────────
    placed_ports = [
        PlacedPort(
            name=p.name, node=p.node, number=p.number,
            x=round(port_x_map.get(p.name, left_x), 4), y=SIGNAL_Y,
        )
        for p in build_plan.ports
    ]

    # ── Build PlacedInstance list ─────────────────────────────────────────────
    placed_instances = []

    for inst in shunts:
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=round(shunt_x_map[inst.id], 4), y=SIGNAL_Y,
            angle=_angle_for(inst), params=inst.params, role=inst.role,
        ))

    for gnd in gnds:
        placed_instances.append(PlacedInstance(
            id=gnd.id, ads_lib=gnd.ads_lib, ads_cell=gnd.ads_cell,
            ads_view=gnd.ads_view, x=round(gnd_x_map.get(gnd.id, FIRST_SHUNT_X), 4), y=GND_Y,
            angle=ANGLE_GND, params=gnd.params, role=gnd.role,
        ))

    for inst in all_series:
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=round(series_x_map[inst.id], 4), y=SIGNAL_Y,
            angle=_angle_for(inst), params=inst.params, role=inst.role,
        ))

    # ── Wire generation (netlist-driven per-net routing) ──────────────────────
    placed_wires = _route_wires_from_netlist(
        build_plan, placed_instances, placed_ports, ordered_backbone
    )

    return placed_ports, placed_instances, placed_wires


# ── Main placement function ────────────────────────────────────────────────────

def compute_placement(build_plan: BuildPlan) -> PlacementPlan:
    """
    Compute full placement plan from a BuildPlan.
    Returns a PlacementPlan with coordinates for every component and wire.
    Dispatches to SPDT-specific layout when FET elements are present.
    """
    warnings = list(build_plan.warnings)
    if _is_spdt_topology(build_plan):
        placed_ports, placed_instances, placed_wires = _assign_spdt_coordinates(
            build_plan, warnings
        )
    else:
        placed_ports, placed_instances, placed_wires = _assign_coordinates(build_plan, warnings)

    return PlacementPlan(
        cell_name=build_plan.cell_name,
        source_buildplan=build_plan.source_ir,
        generation_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        ports=placed_ports,
        instances=placed_instances,
        wires=placed_wires,
        warnings=warnings,
    )


# ── YAML serialization ─────────────────────────────────────────────────────────

def _placement_to_dict(plan: PlacementPlan) -> dict:
    return {
        "cell_name": plan.cell_name,
        "source_buildplan": plan.source_buildplan,
        "generation_timestamp": plan.generation_timestamp,
        "ports": [
            {"name": p.name, "node": p.node, "number": p.number, "x": p.x, "y": p.y}
            for p in plan.ports
        ],
        "instances": [
            {
                "id": i.id,
                "ads_lib": i.ads_lib,
                "ads_cell": i.ads_cell,
                "ads_view": i.ads_view,
                "x": i.x,
                "y": i.y,
                "angle": i.angle,
                "params": i.params,
                "role": i.role,
            }
            for i in plan.instances
        ],
        "wires": [
            {"id": w.id, "points": w.points, "note": w.note}
            for w in plan.wires
        ],
        "warnings": plan.warnings,
    }


def write_placement(plan: PlacementPlan, output_dir: Path) -> Path:
    """Write placement plan to <output_dir>/<cell_name_lower>_placement.yaml."""
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not available — cannot write placement plan.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{plan.cell_name.lower()}_placement.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(_placement_to_dict(plan), f, default_flow_style=False, sort_keys=False)
    return out_path


# ── ADS schematic build ────────────────────────────────────────────────────────

def build_ads_schematic(
    plan: PlacementPlan,
    workspace_path: str,
    lib_name: str,
    ads_dir: str = r"C:\Program Files\Keysight\ADS2026_Update1",
) -> None:
    """
    Stage 3b — Execute ADS Python API calls to build the schematic cell.

    All API calls use CONFIRMED patterns from:
    ../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md

    Must be run with the ADS-bundled Python interpreter:
      C:\\Program Files\\Keysight\\ADS2026_Update1\\tools\\python\\python.exe

    Args:
        plan          : PlacementPlan from compute_placement()
        workspace_path: path to existing ADS workspace
        lib_name      : target library name (must exist in workspace)
        ads_dir       : ADS installation directory

    Raises:
        ImportError   : if not running in ADS Python environment
        RuntimeError  : if workspace or library not found
    """
    import sys, os
    sys.path.insert(0, str(Path(ads_dir) / "tools" / "python" / "packages"))
    os.environ.setdefault("HPEESOF_DIR", ads_dir)

    try:
        import keysight.ads.de as de
        from keysight.ads.de import db_uu as db
        from keysight.ads.de._pde.db import TermType, DesignMode  # ✅ CONFIRMED import path
    except ImportError as e:
        raise ImportError(
            f"ADS Python packages not available: {e}\n"
            "Run this script with the ADS-bundled Python interpreter:\n"
            f"  {ads_dir}\\tools\\python\\python.exe"
        ) from e

    cell_name = plan.cell_name.lower()

    print(f"=== Building ADS cell: {lib_name}:{cell_name} ===")

    # ── Open workspace (✅ CONFIRMED) ─────────────────────────────────────────
    print("[1] Opening workspace...")
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        ws = de.open_workspace(workspace_path)
    print(f"    {ws}")

    # ── Get library (✅ CONFIRMED) ─────────────────────────────────────────────
    print("[2] Getting library...")
    lib = de.get_open_library(lib_name)

    # ── Get or create cell (✅ CONFIRMED) ──────────────────────────────────────
    print("[3] Setting up cell...")
    if lib.cell_exists(cell_name):
        cell = lib.cell(cell_name)
        print(f"    cell exists: {cell_name}")
    else:
        cell = de.Cell.create(lib, cell_name)
        print(f"    cell created: {cell_name}")

    # ── Recreate schematic view (✅ CONFIRMED) ─────────────────────────────────
    if cell.view_exists("schematic"):
        cell.delete_view("schematic")
        print("    deleted existing schematic view")
    sch_view = de.View.create(cell, "schematic", "schematic")
    print("    schematic view created")

    # ── Open design in WRITE mode (✅ CONFIRMED) ───────────────────────────────
    # CRITICAL: default is READ_ONLY — must use WRITE to enable save_design()
    design = sch_view.get_design(DesignMode.WRITE)
    print("    design open (WRITE mode)")

    # ── Create port terms (✅ CONFIRMED) ──────────────────────────────────────
    # Port terms = sub-cell pins (NOT simulation Term components).
    print("[4] Creating port terms...")
    for port in sorted(plan.ports, key=lambda p: p.number):
        net  = design.find_or_add_net(port.name)   # ✅ CONFIRMED
        term = design.add_term(net, port.name, TermType.INPUT_OUTPUT)  # ✅ CONFIRMED
        print(f"    port {port.number}: '{port.name}'")

    # ── Place instances (✅ CONFIRMED) ─────────────────────────────────────────
    print("[5] Placing instances...")
    for inst in plan.instances:
        if inst.role == "gnd":
            # GND symbol — no parameters
            design.add_instance(
                de.LCVName(inst.ads_lib, inst.ads_cell, inst.ads_view),  # ✅ CONFIRMED
                (inst.x, inst.y), name=inst.id, angle=inst.angle,
            )
            print(f"    GND  {inst.id} @ ({inst.x}, {inst.y}) angle={inst.angle}")
        else:
            ads_inst = design.add_instance(
                de.LCVName(inst.ads_lib, inst.ads_cell, inst.ads_view),  # ✅ CONFIRMED
                (inst.x, inst.y), name=inst.id, angle=inst.angle,
            )
            # Set parameters (✅ CONFIRMED: inst.parameters[key].value = expr)
            for param_name, param_value in inst.params.items():
                try:
                    ads_inst.parameters[param_name].value = param_value
                except (KeyError, AttributeError) as exc:
                    print(f"    [WARN] Could not set {inst.id}.{param_name}={param_value}: {exc}")
            print(f"    {inst.role:<8} {inst.id} @ ({inst.x}, {inst.y}) "
                  f"angle={inst.angle}  params={inst.params}")

    # ── Add wires (✅ CONFIRMED) ───────────────────────────────────────────────
    print("[6] Adding wires...")
    for wire in plan.wires:
        design.add_wire(wire.points)   # ✅ CONFIRMED
        print(f"    {wire.id}: {wire.points}")

    # ── Design variables (✅ CONFIRMED) ───────────────────────────────────────
    # Only written if the build plan includes design_variables entries.
    # For Phase 1 (literal values), this list is empty.
    # (API confirmed: design.cell.write_design_variables([...]))

    # ── Save schematic (✅ CONFIRMED — must call; changes are not auto-saved) ──
    print("[7] Saving schematic...")
    design.save_design()
    print(f"    saved: {lib_name}:{cell_name}:schematic")

    # ── Create blackbox symbol (✅ CONFIRMED pattern) ─────────────────────────
    print("[8] Creating symbol...")
    try:
        if cell.view_exists("symbol"):
            cell.delete_view("symbol")
            print("    deleted existing symbol view")

        db.create_symbol((lib_name, cell_name, "symbol"))   # ✅ CONFIRMED
        sym_view  = cell.view("symbol")                      # ✅ CONFIRMED
        sym_write = sym_view.get_design(DesignMode.WRITE)   # ✅ CONFIRMED

        sch_terms = list(design.terms)  # ✅ CONFIRMED
        print(f"    terms: {[t.name for t in sch_terms]}")

        y_spacing = 2.0
        y_start   = (len(sch_terms) - 1) * y_spacing / 2.0
        for idx, term in enumerate(sch_terms):
            y_pos = y_start - (idx * y_spacing)
            sym_write.add_pin_fig_for_term_type(  # ✅ CONFIRMED
                term.term_type, (0.0, y_pos)
            )
            print(f"    pin '{term.name}' @ (0.0, {y_pos})")

        sym_write.save_design()  # ✅ CONFIRMED
        print(f"    saved: {lib_name}:{cell_name}:symbol")

    except Exception as exc:
        print(f"    [ERROR] Symbol creation failed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()

    print(f"\n=== Done ===")
    print(f"  Schematic : {lib_name}:{cell_name}:schematic")
    print(f"  Symbol    : {lib_name}:{cell_name}:symbol")


# ── CLI usage ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from translator.parser import parse_research_netlist
    from translator.ir_builder import build_ir, write_ir
    from translator.ads_mapper import map_ir_to_buildplan, write_buildplan, load_mapping_config

    if len(sys.argv) < 4:
        print("Usage: python placement_engine.py <netlist.net> <ads_mapping.yaml> <workspace> [lib_name] [output_dir]")
        print("       Add --dry-run to skip ADS API calls and only write placement plan")
        sys.exit(1)

    net_path    = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    workspace   = sys.argv[3]
    lib_name    = sys.argv[4] if len(sys.argv) > 4 else "net2ads_lib"
    out_dir     = Path(sys.argv[5]) if len(sys.argv) > 5 else net_path.parent
    dry_run     = "--dry-run" in sys.argv

    # Run full pipeline
    config   = load_mapping_config(config_path)
    parsed   = parse_research_netlist(net_path)
    ir       = build_ir(parsed)
    write_ir(ir, out_dir)

    plan_bp  = map_ir_to_buildplan(ir, config)
    write_buildplan(plan_bp, out_dir)

    placement = compute_placement(plan_bp)
    pl_path   = write_placement(placement, out_dir)
    print(f"Placement plan: {pl_path}")

    for inst in placement.instances:
        print(f"  {inst.role:<8} {inst.id:<25} @ ({inst.x:6.3f}, {inst.y:5.1f}) "
              f"angle={inst.angle:6.1f}  {inst.ads_lib}:{inst.ads_cell}")
    for wire in placement.wires:
        print(f"  wire  {wire.id}: {wire.points}")

    if not dry_run:
        print("\n--- Building ADS schematic ---")
        build_ads_schematic(placement, workspace_path=workspace, lib_name=lib_name)
    else:
        print("\n[DRY-RUN] Placement plan written. Skipping ADS API calls.")
        print(f"  To build: run without --dry-run using ADS Python interpreter")
