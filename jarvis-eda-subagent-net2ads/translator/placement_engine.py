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


# ── Angle assignment ───────────────────────────────────────────────────────────

def _angle_for(inst: BuildInstance) -> float:
    """Return placement angle for a BuildInstance based on role and element type."""
    if inst.role == "gnd":
        return ANGLE_GND
    if inst.role == "shunt":
        return ANGLE_SHUNT
    if inst.role == "tline":
        return ANGLE_TLINE
    return ANGLE_SERIES   # series, switch (ON=R), default


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

        elif bi.role == "shunt":
            # Only P1 (signal node) contributes to signal-path routing.
            # P2 (ground) is a vertical wire drawn by place_ground() — omit here.
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
    series     = [i for i in build_plan.instances if i.role in ("series", "tline")]
    all_series = series + switches

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

    # ── GND companion positions (share x with companion shunt) ────────────────
    # GND id convention: "GND_{shunt_id}" — match by stripping "GND_" prefix
    gnd_x_map: dict = {}
    for gnd in gnds:
        companion_id = gnd.id[4:] if gnd.id.startswith("GND_") else gnd.id
        gnd_x_map[gnd.id] = shunt_x_map.get(companion_id, FIRST_SHUNT_X)

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
    """
    warnings = list(build_plan.warnings)
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
