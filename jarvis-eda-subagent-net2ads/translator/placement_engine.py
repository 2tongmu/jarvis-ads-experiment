"""
translator/placement_engine.py
===============================
Stage 3a — Placement engine for the net2ads pipeline.

Computes (x, y, angle) for every component in a BuildPlan and writes
the placement plan to disk. The placement plan is then consumed by the
ADS Python API calls that build the actual schematic.

Coordinate conventions (confirmed from jarvis-eda-learning reference scripts):
  - Signal path: y = 0.0, left to right
  - GND level: y = -1.0
  - Port 1 (left):  x = 1.375  (net_to_ads_cell.py _PORT_LEFT)
  - First shunt:    x = 2.875  (net_to_ads_cell.py _SHUNT_X[0])
  - First series:   x = 4.25   (net_to_ads_cell.py _SERIES_X[0])
  - Component spacing: 2.0 units between consecutive components
  - Wire waypoints: sorted union of all component x positions + port x positions

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


# ── Placement constants (confirmed from reference scripts) ─────────────────────
PORT_LEFT_X   = 1.375   # port 1 wire endpoint x (net_to_ads_cell.py _PORT_LEFT)
FIRST_SHUNT_X = 2.875   # first shunt component x (net_to_ads_cell.py _SHUNT_X[0])
FIRST_SERIES_X = 4.25   # first series component x (net_to_ads_cell.py _SERIES_X[0])
COMPONENT_SPACING = 2.0 # units between consecutive components on signal path
SIGNAL_Y     = 0.0      # all signal-path components at y=0
GND_Y        = -1.0     # GND symbols at y=-1

# Angle conventions (confirmed from ads_build_spdt_pdk.py)
ANGLE_SERIES  = 0.0
ANGLE_SHUNT   = -90.0
ANGLE_GND     = -90.0
ANGLE_TLINE   = 0.0


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


# ── Coordinate assignment ──────────────────────────────────────────────────────

def _assign_coordinates(
    build_plan: BuildPlan,
    warnings: list,
) -> tuple:
    """
    Assign (x, y) to each BuildInstance and each port.

    Strategy:
      1. Separate instances into shunts, series/tline, GNDs, and switches.
      2. Assign shunt x positions starting at FIRST_SHUNT_X, spaced COMPONENT_SPACING apart.
      3. Assign series/tline x positions starting at FIRST_SERIES_X, spaced COMPONENT_SPACING.
         If there are no shunts, series starts at FIRST_SHUNT_X instead (no gap needed).
      4. GND symbols share x with their companion shunt component, placed at GND_Y.
      5. Compute right port x as last component's x + 1.0.
      6. Wire waypoints: sorted union of all component x + port x positions.

    Returns (placed_ports, placed_instances, placed_wires).
    """
    shunts   = [i for i in build_plan.instances if i.role == "shunt"]
    series   = [i for i in build_plan.instances if i.role in ("series", "tline")]
    gnds     = [i for i in build_plan.instances if i.role == "gnd"]
    switches = [i for i in build_plan.instances if i.role == "switch"]
    # Switches treated same as series for placement purposes
    all_series = series + switches

    # ── Assign shunt x positions ──────────────────────────────────────────────
    shunt_x_map = {}   # id -> x
    shunt_xs = []
    for idx, inst in enumerate(shunts):
        x = FIRST_SHUNT_X + idx * COMPONENT_SPACING
        shunt_x_map[inst.id] = x
        shunt_xs.append(x)

    # ── Assign series x positions ─────────────────────────────────────────────
    series_x_map = {}   # id -> x
    series_xs = []
    start_x = FIRST_SERIES_X if shunts else FIRST_SHUNT_X
    for idx, inst in enumerate(all_series):
        x = start_x + idx * COMPONENT_SPACING
        series_x_map[inst.id] = x
        series_xs.append(x)

    # ── GND companion positions (share x with shunt) ──────────────────────────
    # GND id convention: "GND_{shunt_id}" — match by stripping "GND_" prefix
    gnd_x_map = {}
    for gnd in gnds:
        companion_id = gnd.id[4:] if gnd.id.startswith("GND_") else gnd.id
        x = shunt_x_map.get(companion_id, FIRST_SHUNT_X)
        gnd_x_map[gnd.id] = x

    # ── Port x positions ──────────────────────────────────────────────────────
    left_x = PORT_LEFT_X
    all_comp_xs = shunt_xs + series_xs
    right_x = (max(all_comp_xs) + 1.0) if all_comp_xs else (left_x + 2.0)

    port_x_map = {}
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
        x = shunt_x_map[inst.id]
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=round(x, 4), y=SIGNAL_Y,
            angle=_angle_for(inst), params=inst.params, role=inst.role,
        ))

    for gnd in gnds:
        x = gnd_x_map.get(gnd.id, FIRST_SHUNT_X)
        placed_instances.append(PlacedInstance(
            id=gnd.id, ads_lib=gnd.ads_lib, ads_cell=gnd.ads_cell,
            ads_view=gnd.ads_view, x=round(x, 4), y=GND_Y,
            angle=ANGLE_GND, params=gnd.params, role=gnd.role,
        ))

    for inst in all_series:
        x = series_x_map[inst.id]
        placed_instances.append(PlacedInstance(
            id=inst.id, ads_lib=inst.ads_lib, ads_cell=inst.ads_cell,
            ads_view=inst.ads_view, x=round(x, 4), y=SIGNAL_Y,
            angle=_angle_for(inst), params=inst.params, role=inst.role,
        ))

    # ── Wire generation ───────────────────────────────────────────────────────
    # Main horizontal wire: one polyline through all waypoints at y=0.
    # Waypoints = sorted union of left_x, right_x, all shunt_xs, all series_xs.
    waypoint_xs = sorted(set([left_x, right_x] + shunt_xs + series_xs))
    main_wire = PlacedWire(
        id="main_wire",
        points=[(round(x, 4), SIGNAL_Y) for x in waypoint_xs],
        note="main signal path (horizontal at y=0)",
    )

    # Shunt vertical wires: one per shunt branch
    shunt_wires = [
        PlacedWire(
            id=f"shunt_wire_{inst.id}",
            points=[(round(shunt_x_map[inst.id], 4), SIGNAL_Y),
                    (round(shunt_x_map[inst.id], 4), GND_Y)],
            note=f"shunt branch: {inst.id} → GND",
        )
        for inst in shunts
    ]

    placed_wires = [main_wire] + shunt_wires

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
