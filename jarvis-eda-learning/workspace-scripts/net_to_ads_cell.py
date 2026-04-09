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

API: keysight.ads.de object API only — no AEL de_* calls.
     Confirmed by Jarvis execution 2026-04-08. See ADS_API_REFERENCE.md.
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

COMP_LCV = {
    'R': de.LCVName('ads_rflib', 'R', 'symbol'),
    'C': de.LCVName('ads_rflib', 'C', 'symbol'),
    'L': de.LCVName('ads_rflib', 'L', 'symbol'),
}
GND_LCV  = de.LCVName('ads_rflib', 'GROUND', 'symbol')
GND_NETS = {'0', 'gnd', 'GND', 'GROUND', 'ground'}

# Schematic grid (user units) — matches ads_rflib component sizes
GRID_X     = 2.0   # horizontal spacing between series components
GRID_Y     = 1.5   # vertical drop for shunt component center
PIN_OFFSET = 0.5   # assumed pin-to-center half-width for ads_rflib R/C


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 — Parse .net
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
# Placement helpers
# ══════════════════════════════════════════════════════════════════════════════

def _order_series(series, start_net):
    """
    Walk series components from start_net in topological order.
    Returns (ordered_list, entry_nodes_list).
    """
    ordered, entry_nodes, remaining = [], [], list(series)
    current = start_net
    while remaining:
        for c in remaining:
            if current in c['nodes']:
                ordered.append(c)
                entry_nodes.append(current)
                remaining.remove(c)
                current = next(n for n in c['nodes'] if n != current)
                break
        else:
            ordered.extend(remaining)
            entry_nodes.extend([remaining[0]['nodes'][0]] * len(remaining))
            break
    return ordered, entry_nodes


def compute_placement(components, ports):
    """
    Simple left-to-right placement for single-path topologies.
      Series: placed horizontally at y=0, x = GRID_X, 2*GRID_X, ...
      Shunt:  placed vertically below their junction node.

    Returns:
        placement   : {name: {x, y, angle}}
        gnd_markers : {gnd_name: {x, y, angle}}
        ordered     : series components in traversal order
        entry_nodes : which node was entry for each ordered component
        final_x     : x after last series component (used for right port pin)
    """
    port1_net = next(
        (p['net'] for p in sorted(ports, key=lambda p: p['number'])), None
    )
    shunts  = [c for c in components if any(n in GND_NETS for n in c['nodes'])]
    series  = [c for c in components if c not in shunts]
    ordered, entry_nodes = _order_series(series, port1_net)

    placement, gnd_markers = {}, {}

    x = GRID_X
    for comp in ordered:
        placement[comp['name']] = {'x': x, 'y': 0.0, 'angle': 0.0}
        x += GRID_X

    for comp in shunts:
        non_gnd = next(n for n in comp['nodes'] if n not in GND_NETS)
        ref_x   = x - GRID_X  # fallback
        for sc, en in zip(ordered, entry_nodes):
            if non_gnd in sc['nodes']:
                exit_n = next(n for n in sc['nodes'] if n != en)
                ref_x  = placement[sc['name']]['x'] + (PIN_OFFSET if non_gnd == exit_n else -PIN_OFFSET)
                break
        placement[comp['name']]            = {'x': ref_x, 'y': -(GRID_Y / 2), 'angle': 90.0}
        gnd_markers[f'GND_{comp["name"]}'] = {'x': ref_x, 'y': -(GRID_Y + 0.5), 'angle': 180.0}

    return placement, gnd_markers, ordered, entry_nodes, x


# ══════════════════════════════════════════════════════════════════════════════
# Main
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

    # ── Open workspace ─────────────────────────────────────────────────────────
    print("\n=== Opening workspace ===")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws = de.open_workspace(WORKSPACE)
    print(f"  {ws}")

    # ── Get library, create/recreate cell and schematic view ───────────────────
    print("\n=== Setting up cell and schematic view ===")
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
    print(f"  schematic view created: {lcv}")

    # ── Get design in WRITE mode ───────────────────────────────────────────────
    # CRITICAL: default is READ_ONLY — must use WRITE to persist changes
    design = sch_view.get_design(DesignMode.WRITE)
    print(f"  design open (WRITE): {design}")

    # ── Compute placement ──────────────────────────────────────────────────────
    shunts = [c for c in components if any(n in GND_NETS for n in c['nodes'])]
    placement, gnd_markers, ordered, entry_nodes, final_x = compute_placement(
        components, ports
    )

    # ── Create port nets and terms ─────────────────────────────────────────────
    # Terms (sub-cell pins) must be created before instances/wires so that
    # wires can reach their snap-points.
    print("\n=== Creating port terms ===")
    port_nets  = {}
    port_terms = {}
    for port in sorted(ports, key=lambda p: p['number']):
        net  = design.find_or_add_net(port['net'])
        term = design.add_term(net, port['net'], TermType.INPUT_OUTPUT)
        port_nets[port['net']]  = net
        port_terms[port['net']] = term
        print(f"  port {port['number']}: '{port['net']}'")

    # ── Place series instances ─────────────────────────────────────────────────
    print("\n=== Placing instances ===")
    instances = {}

    for comp in ordered:
        p    = placement[comp['name']]
        lcv_ = COMP_LCV.get(comp['type'], de.LCVName('ads_rflib', comp['type'], 'symbol'))
        inst = design.add_instance(lcv_, (p['x'], p['y']),
                                   name=comp['name'], angle=p['angle'])
        instances[comp['name']] = inst
        print(f"  {comp['name']} [series] @ ({p['x']:.2f}, {p['y']:.2f}) angle={p['angle']}")

    for comp in shunts:
        p    = placement[comp['name']]
        lcv_ = COMP_LCV.get(comp['type'], de.LCVName('ads_rflib', comp['type'], 'symbol'))
        inst = design.add_instance(lcv_, (p['x'], p['y']),
                                   name=comp['name'], angle=p['angle'])
        instances[comp['name']] = inst
        print(f"  {comp['name']} [shunt] @ ({p['x']:.2f}, {p['y']:.2f}) angle={p['angle']}")

    for gnd_name, p in gnd_markers.items():
        design.add_instance(GND_LCV, (p['x'], p['y']),
                            name=gnd_name, angle=p['angle'])
        print(f"  {gnd_name} [GND] @ ({p['x']:.2f}, {p['y']:.2f})")

    # ── Set component parameter values ─────────────────────────────────────────
    print("\n=== Setting component parameters ===")
    PARAM_KEY = {'R': 'R', 'C': 'C', 'L': 'L'}
    for comp in components:
        inst = instances.get(comp['name'])
        key  = PARAM_KEY.get(comp['type'])
        if not inst or not key:
            continue
        try:
            inst.parameters[key].value = comp['value']
            print(f"  {comp['name']}.{key} = '{comp['value']}'")
        except Exception as e:
            print(f"  [WARN] {comp['name']}.{key} set failed: {e}")

    # ── Add wires ──────────────────────────────────────────────────────────────
    # Port pin positions: left port at x=0, right port at x=final_x
    print("\n=== Adding wires ===")

    left_net  = entry_nodes[0]                                   if ordered else None
    right_net = next(n for n in ordered[-1]['nodes'] if n != entry_nodes[-1]) if ordered else None

    port_x = {}
    for port in ports:
        if port['net'] == left_net:
            port_x[port['net']] = 0.0
        elif port['net'] == right_net:
            port_x[port['net']] = final_x
        else:
            port_x[port['net']] = final_x + GRID_X

    # Main horizontal wire at y=0: left port → right port
    if ordered and left_net and right_net:
        lx = port_x.get(left_net, 0.0)
        rx = port_x.get(right_net, final_x)
        design.add_wire([(lx, 0.0), (rx, 0.0)])
        print(f"  main wire: ({lx:.2f}, 0.0) → ({rx:.2f}, 0.0)")

    # Shunt wires: from main wire (y=0) down through component to GND
    for comp in shunts:
        p     = placement[comp['name']]
        gnd_p = gnd_markers.get(f'GND_{comp["name"]}')
        if gnd_p:
            design.add_wire([(p['x'], 0.0), (p['x'], gnd_p['y'])])
            print(f"  shunt wire: ({p['x']:.2f}, 0.0) → ({p['x']:.2f}, {gnd_p['y']:.2f})")

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

    # ── Create blackbox symbol ─────────────────────────────────────────────────
    print("\n=== Creating blackbox symbol ===")
    try:
        if cell.view_exists('symbol'):
            cell.delete_view('symbol')
            print(f"  deleted existing symbol view")

        symbol_design = db.create_symbol((LIB, cell_name, 'symbol'))
        print(f"  symbol view created: {sym_lcv}")

        sym_view         = cell.view('symbol')
        sym_design_write = sym_view.get_design(DesignMode.WRITE)

        # Place one pin figure per schematic term, evenly spaced vertically
        sch_terms = list(design.terms)
        print(f"  schematic terms: {[t.name for t in sch_terms]}")
        y_spacing = 2.0
        y_start   = (len(sch_terms) - 1) * y_spacing / 2.0
        for idx, term in enumerate(sch_terms):
            y_pos = y_start - (idx * y_spacing)
            sym_design_write.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))
            print(f"    '{term.name}' pin at (0.0, {y_pos})")

        sym_design_write.save_design()
        print(f"  symbol saved: {sym_lcv}")

    except Exception as e:
        print(f"  [ERROR] symbol generation failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print("\n=== Done ===")
    print(f"  Schematic : {lcv}")
    print(f"  Symbol    : {sym_lcv}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python net_to_ads_cell.py <netlist.net>")
        sys.exit(1)
    main(Path(sys.argv[1]))
