"""
net_to_ads_cell.py
==================
Unified cell creation flow — Steps 2–4: parse .net → create ADS schematic cell.

Flow (see WORKFLOW.md):
    Step 2  Pre-process  — parse .net, extract components/params/ports
    Step 3  PDK swap     — skipped for generic R/C (no PDK substitution needed)
    Step 4  Create cell  — place instances, wire, set params, save, generate symbol

Usage (Jarvis):
    "C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" \
        workspace-scripts/net_to_ads_cell.py workspace-scripts/test_bias_rc.net

Cell placed in: spdt_switch_pdk_lib
Cell name: cell_<netlist_stem>  (e.g. test_bias_rc → cell_test_bias_rc)

Placement: coordinates and angles match .dem recording and ads_build_spdt_pdk.py
  Angles — C (shunt): -90.0   GND: -90.0   R (series): 0.0  (from ads_build_spdt_pdk.py)
  RC bias coordinates — from .dem ground truth:
    v_ctrl pin: (1.375, 0)   C1: (2.875, 0)   R1: (4.25, 0)   sw_gate pin: (5.25, 0)
    GND: (2.875, -1)
    Main wire: (1.375,0)→(2.875,0)→(4.25,0)→(5.25,0)
    Shunt wire: (2.875,0)→(2.875,-1)
"""

import sys
import re
import warnings
from pathlib import Path

# ── ADS Python environment ─────────────────────────────────────────────────────
ADS_DIR = Path("C:/Program Files/Keysight/ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))

import os
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db
from keysight.ads.de._pde.db import TermType, DesignMode

# ── Constants ──────────────────────────────────────────────────────────────────
WORKSPACE = "C:/Users/jarvis/ads_projects/spdt_switch_pdk_wrk"
LIB       = "spdt_switch_pdk_lib"
GND_NETS  = {'0', 'gnd', 'GND', 'GROUND', 'ground'}

# Component angles — confirmed from ads_build_spdt_pdk.py mkR/mkC/mkGnd helpers
ANGLE_R_SERIES = 0.0     # horizontal resistor
ANGLE_C_SHUNT  = -90.0   # shunt capacitor (vertical, pin1 at top)
ANGLE_GND      = -90.0   # ground symbol


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Parse .net  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def parse_net(path: Path):
    """
    Parse a minimal SPICE-style .net file.

    Supported lines:
        * comment
        R/C/L name node1 node2 value
        .param name=value  (one or more per line)
        .port netname number
        .end

    Returns:
        components : list of {name, type, nodes:[n1,n2], value}
        params     : dict  {name: value_str}
        ports      : list of {net, number}
    """
    components, params, ports = [], {}, []

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('*'):
            continue
        lo = line.lower()
        if lo == '.end':
            break
        elif lo.startswith('.param'):
            for m in re.finditer(r'(\w+)\s*=\s*([^\s]+)', line[6:]):
                params[m.group(1)] = m.group(2)
        elif lo.startswith('.port'):
            parts = line.split()
            ports.append({'net': parts[1], 'number': int(parts[2])})
        elif lo[0] in 'rcl':
            parts = line.split()
            components.append({
                'name':  parts[0],
                'type':  parts[0][0].upper(),
                'nodes': [parts[1], parts[2]],
                'value': parts[3],
            })

    return components, params, ports


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 — Create ADS cell
# ══════════════════════════════════════════════════════════════════════════════

def main(net_path: Path):

    # ── Parse ──────────────────────────────────────────────────────────────────
    print(f"=== Parsing {net_path.name} ===")
    components, params, ports = parse_net(net_path)
    print(f"  components : {[c['name'] for c in components]}")
    print(f"  params     : {params}")
    print(f"  ports      : {ports}")

    cell_name = f"cell_{net_path.stem}"
    lcv       = f"{LIB}:{cell_name}:schematic"
    sym_lcv   = f"{LIB}:{cell_name}:symbol"
    print(f"\n=== Target cell: {lcv} ===")

    # ── Classify components ────────────────────────────────────────────────────
    shunts = [c for c in components if any(n in GND_NETS for n in c['nodes'])]
    series = [c for c in components if c not in shunts]
    print(f"\n=== Topology ===")
    print(f"  series : {[c['name'] for c in series]}")
    print(f"  shunts : {[c['name'] for c in shunts]}")

    # ── Open workspace ─────────────────────────────────────────────────────────
    print("\n=== Opening workspace ===")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws = de.open_workspace(WORKSPACE)
    print(f"  {ws}")

    # ── Get library, create/recreate cell and schematic view ───────────────────
    # Pattern from ads_bias_subcell_create.py (Jarvis confirmed 2026-04-08)
    print("\n=== Setting up cell ===")
    lib = de.get_open_library(LIB)

    if lib.cell_exists(cell_name):
        cell = lib.cell(cell_name)
        print(f"  cell exists: {cell_name}")
    else:
        cell = de.Cell.create(lib, cell_name)
        print(f"  cell created: {cell_name}")

    if cell.view_exists('schematic'):
        cell.delete_view('schematic')
        print(f"  deleted existing schematic view")
    sch_view = de.View.create(cell, 'schematic', 'schematic')
    print(f"  schematic view created")

    # CRITICAL: must use DesignMode.WRITE — READ_ONLY (default) cannot save
    design = sch_view.get_design(DesignMode.WRITE)
    print(f"  design open (WRITE mode)")

    # ── Port terms ─────────────────────────────────────────────────────────────
    # Create terms before instances so wire endpoints connect to them.
    # Positions are implicit — wire endpoints (1.375,0) and (5.25,0) establish location.
    print("\n=== Creating port terms ===")
    port_terms = {}
    for port in sorted(ports, key=lambda p: p['number']):
        net  = design.find_or_add_net(port['net'])
        term = design.add_term(net, port['net'], TermType.INPUT_OUTPUT)
        port_terms[port['net']] = term
        print(f"  port {port['number']}: '{port['net']}'")

    # ── Place instances ────────────────────────────────────────────────────────
    # Coordinates: .dem ground truth (see module docstring)
    # Angles: ads_build_spdt_pdk.py confirmed values
    print("\n=== Placing instances ===")

    # Shunt components: placed at signal wire (y=0), angle=-90 (confirmed)
    for comp in shunts:
        non_gnd = next(n for n in comp['nodes'] if n not in GND_NETS)
        angle   = ANGLE_C_SHUNT if comp['type'] == 'C' else -90.0
        x, y    = _shunt_xy(comp, series)
        inst    = design.add_instance(
            de.LCVName('ads_rflib', comp['type'], 'symbol'),
            (x, y), name=comp['name'], angle=angle,
        )
        inst.parameters[comp['type']].value = comp['value']
        print(f"  {comp['name']} [shunt] @ ({x}, {y}) angle={angle}")

        # GND symbol below shunt component (confirmed: angle=-90)
        gnd_y = y - 1.0
        design.add_instance(
            de.LCVName('ads_rflib', 'GROUND', 'symbol'),
            (x, gnd_y), name=f'GND_{comp["name"]}', angle=ANGLE_GND,
        )
        print(f"  GND_{comp['name']} @ ({x}, {gnd_y}) angle={ANGLE_GND}")

    # Series components: placed on signal wire (y=0), angle=0 (confirmed)
    for comp in series:
        x, y = _series_xy(comp, shunts, series)
        inst  = design.add_instance(
            de.LCVName('ads_rflib', comp['type'], 'symbol'),
            (x, y), name=comp['name'], angle=ANGLE_R_SERIES,
        )
        inst.parameters[comp['type']].value = comp['value']
        print(f"  {comp['name']} [series] @ ({x}, {y}) angle={ANGLE_R_SERIES}")

    # ── Wires ──────────────────────────────────────────────────────────────────
    # Coordinates: .dem ground truth
    # Pattern: ads_build_spdt_pdk.py wire() helper → sch.add_wire(pts)
    print("\n=== Adding wires ===")

    port_xs  = _port_xs(ports, series, shunts)
    left_x   = port_xs['left']
    right_x  = port_xs['right']
    shunt_xs = [_shunt_xy(c, series)[0] for c in shunts]

    # Main horizontal wire — single polyline through all waypoints at y=0.
    # Includes port endpoints, shunt component x positions, and series component x positions.
    series_xs = [_series_xy(c, shunts, series)[0] for c in series]
    waypoints  = sorted({left_x, right_x} | set(shunt_xs) | set(series_xs))
    design.add_wire([(x, 0.0) for x in waypoints])
    print(f"  main wire: {[(x, 0.0) for x in waypoints]}")

    # Shunt vertical wires — from main wire down to GND symbol
    for comp in shunts:
        sx, _ = _shunt_xy(comp, series)
        design.add_wire([(sx, 0.0), (sx, -1.0)])
        print(f"  shunt wire: ({sx}, 0.0) → ({sx}, -1.0)")

    # ── Design variables from .param ───────────────────────────────────────────
    if params:
        print("\n=== Setting design variables ===")
        design.cell.write_design_variables(list(params.items()))
        for k, v in params.items():
            print(f"  {k} = {v}")

    # ── Save schematic ─────────────────────────────────────────────────────────
    print("\n=== Saving schematic ===")
    design.save_design()
    print(f"  saved: {lcv}")

    # ── Symbol ─────────────────────────────────────────────────────────────────
    # Pattern: ads_bias_subcell_create.py (Jarvis confirmed 2026-04-08)
    print("\n=== Creating symbol ===")
    try:
        if cell.view_exists('symbol'):
            cell.delete_view('symbol')
            print(f"  deleted existing symbol view")

        db.create_symbol((LIB, cell_name, 'symbol'))
        sym_view         = cell.view('symbol')
        sym_design_write = sym_view.get_design(DesignMode.WRITE)

        sch_terms = list(design.terms)
        print(f"  terms: {[t.name for t in sch_terms]}")
        y_spacing = 2.0
        y_start   = (len(sch_terms) - 1) * y_spacing / 2.0
        for idx, term in enumerate(sch_terms):
            y_pos = y_start - (idx * y_spacing)
            sym_design_write.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))
            print(f"    '{term.name}' pin @ (0.0, {y_pos})")

        sym_design_write.save_design()
        print(f"  saved: {sym_lcv}")

    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()

    print("\n=== Done ===")
    print(f"  Schematic : {lcv}")
    print(f"  Symbol    : {sym_lcv}")


# ══════════════════════════════════════════════════════════════════════════════
# Placement coordinate helpers
# Coordinates match .dem ground truth for RC bias topology.
# ══════════════════════════════════════════════════════════════════════════════

# Hard x-positions from .dem recording (unit: schematic user units)
# Extend this table when adding new topologies.
_SHUNT_X  = {0: 2.875}   # first shunt component at x=2.875
_SERIES_X = {0: 4.25}    # first series component at x=4.25
_PORT_LEFT  = 1.375       # port 1 (input) wire endpoint x
_PORT_RIGHT = 5.25        # port 2 (output) wire endpoint x


def _shunt_xy(comp, series):
    """Return (x, y) for a shunt component. y=0 (on signal wire)."""
    # All shunts share the same x-position lookup (index 0 for single-shunt topologies).
    # For multi-shunt topologies, extend _SHUNT_X with additional indices.
    return (_SHUNT_X.get(0, 2.875), 0.0)


def _series_xy(comp, shunts, series):
    """Return (x, y) for a series component. y=0 (on signal wire)."""
    idx = series.index(comp)
    return (_SERIES_X.get(idx, 4.25 + idx * 2.0), 0.0)


def _port_xs(ports, series, shunts):
    """Return {'left': x, 'right': x} for the two port pin wire endpoints."""
    return {'left': _PORT_LEFT, 'right': _PORT_RIGHT}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python net_to_ads_cell.py <netlist.net>")
        sys.exit(1)
    main(Path(sys.argv[1]))
