"""
translator/placement_checker.py
================================
Post-placement connectivity checker for the net2ads pipeline.

Verifies that every non-ground pin in a PlacementPlan is connected to at
least one other pin on the same net — either by co-location (same x,y) or
by an explicit wire endpoint at the same position.

Pin positions are computed from ads_pdk/pin_offsets.yaml (data-driven).
Components not in the registry fall back to a role-based heuristic with a
warning, so new cells don't silently break the checker.

Called from net2ads.py after Stage 4 (write_placement).

Usage:
    from translator.placement_checker import check_placement
    errors = check_placement(build_plan, placement)
    for msg in errors:
        print(msg)
"""

from pathlib import Path
from translator.ads_mapper import BuildPlan
from translator.placement_engine import PlacementPlan, COMP_WIDTH, _is_ground_node

_TOL = 1e-4   # coordinate equality tolerance (grid is 0.001 unit minimum)

# Path to the pin offsets registry (relative to this file's package root)
_PIN_OFFSETS_YAML = Path(__file__).resolve().parent.parent / "ads_pdk" / "pin_offsets.yaml"

# Module-level cache so the YAML is loaded only once per interpreter session
_PIN_OFFSETS_CACHE: dict = {}


# ── Pin offset registry loader ────────────────────────────────────────────────

def _load_pin_offsets() -> dict:
    """
    Load ads_pdk/pin_offsets.yaml into a nested dict:
      {(ads_lib, ads_cell): {angle_float: [[dx,dy], ...]}}

    Returns empty dict if YAML unavailable.  Cached after first load.
    """
    global _PIN_OFFSETS_CACHE
    if _PIN_OFFSETS_CACHE:
        return _PIN_OFFSETS_CACHE

    try:
        import yaml
    except ImportError:
        return {}

    if not _PIN_OFFSETS_YAML.exists():
        return {}

    try:
        with open(_PIN_OFFSETS_YAML, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except Exception:
        return {}

    result: dict = {}
    for key, entry in raw.get("pin_offsets", {}).items():
        parts = key.split(":", 1)
        if len(parts) != 2:
            continue
        ads_lib, ads_cell = parts
        offsets_by_angle: dict = {}
        for angle_str, offsets in entry.get("offsets_by_angle", {}).items():
            offsets_by_angle[float(angle_str)] = offsets
        result[(ads_lib, ads_cell)] = {
            "pins": entry.get("pins", []),
            "offsets_by_angle": offsets_by_angle,
        }

    _PIN_OFFSETS_CACHE = result
    return result


def reload_pin_offsets() -> None:
    """Force reload of pin_offsets.yaml (useful after probe_pin_offsets.py runs)."""
    global _PIN_OFFSETS_CACHE
    _PIN_OFFSETS_CACHE = {}
    _load_pin_offsets()


# ── Pin position computation ──────────────────────────────────────────────────

def _get_pin_positions(bi, pi, registry: dict, fallback_warnings: list) -> list:
    """
    Return list of (node_name, x, y) for a BuildInstance given its PlacedInstance.

    Lookup order:
      1. Registry (ads_pdk/pin_offsets.yaml) for (ads_lib, ads_cell, angle)
      2. Role-based heuristic fallback (with warning)

    Ground nodes ('0', 'gnd', ...) are excluded — they connect via GND companions.
    """
    results = []
    key = (pi.ads_lib, pi.ads_cell)
    entry = registry.get(key)

    if entry:
        offsets_map = entry["offsets_by_angle"]
        pins_meta   = entry["pins"]
        angle_key   = round(pi.angle, 1)

        # Find closest registered angle (handles floating-point representation)
        matched_angle = None
        for reg_angle in offsets_map:
            if abs(reg_angle - pi.angle) < 0.5:
                matched_angle = reg_angle
                break

        if matched_angle is not None:
            offsets = offsets_map[matched_angle]
            for pin_meta, (dx, dy) in zip(pins_meta, offsets):
                nodes_idx = pin_meta.get("nodes_idx")
                if nodes_idx is None:
                    continue  # gate pin, GROUND P1, etc. — no IR node to check
                if nodes_idx >= len(bi.nodes):
                    continue
                node = bi.nodes[nodes_idx]
                if not _is_ground_node(node):
                    results.append((node, round(pi.x + dx, 4), round(pi.y + dy, 4)))
            return results
        else:
            fallback_warnings.append(
                f"[CHECK-WARN] {bi.id} ({pi.ads_lib}:{pi.ads_cell}): "
                f"no offset entry for angle={pi.angle} in pin_offsets.yaml — "
                "using heuristic fallback"
            )
    else:
        fallback_warnings.append(
            f"[CHECK-WARN] {bi.id} ({pi.ads_lib}:{pi.ads_cell}): "
            "not in pin_offsets.yaml — using heuristic fallback"
        )

    # ── Heuristic fallback ────────────────────────────────────────────────────
    return _heuristic_pin_positions(bi, pi)


def _heuristic_pin_positions(bi, pi) -> list:
    """
    Role-based fallback pin positions when component is not in pin_offsets.yaml.

    Series (angle=0): P1=(0,0), P2=(COMP_WIDTH,0)
    Shunt  (angle=-90): P1=(0,0) [P2 is GND, excluded]
    Vsource (angle=-90): P1=(0,0) [P2 is GND, excluded]
    FET series (angle=90): drain=(-0.5,0.5), source=(0.5,0.5)
    FET shunt  (angle=0):  drain=(0.5,0.5),  source=(0.5,-0.5)
    fetbias: GATE=(2.0,0)
    """
    x, y = pi.x, pi.y
    results = []

    if bi.role in ("series", "tline", "switch") and len(bi.nodes) >= 2:
        if not _is_ground_node(bi.nodes[0]):
            results.append((bi.nodes[0], round(x, 4), round(y, 4)))
        if not _is_ground_node(bi.nodes[1]):
            results.append((bi.nodes[1], round(x + COMP_WIDTH, 4), round(y, 4)))

    elif bi.role in ("shunt", "vsource") and bi.nodes:
        tap = next((n for n in bi.nodes if not _is_ground_node(n)), None)
        if tap:
            results.append((tap, round(x, 4), round(y, 4)))

    elif bi.role == "fetbias" and bi.nodes:
        results.append((bi.nodes[0], round(x + 2.0, 4), round(y, 4)))

    elif bi.role == "fet_series" and len(bi.nodes) >= 2:
        # Find fetbias companion for gate net
        results.append((bi.nodes[0], round(x - 0.5, 4), round(y + 0.5, 4)))  # drain
        results.append((bi.nodes[1], round(x + 0.5, 4), round(y + 0.5, 4)))  # source

    elif bi.role == "fet_shunt" and len(bi.nodes) >= 2:
        results.append((bi.nodes[0], round(x + 0.5, 4), round(y + 0.5, 4)))  # drain
        results.append((bi.nodes[1], round(x + 0.5, 4), round(y - 0.5, 4)))  # source

    return results


# ── Connectivity check ────────────────────────────────────────────────────────

def _approx_eq(a: float, b: float) -> bool:
    return abs(a - b) < _TOL


def _pt_eq(p1: tuple, p2: tuple) -> bool:
    return _approx_eq(p1[0], p2[0]) and _approx_eq(p1[1], p2[1])


def _pin_on_wire(pin: tuple, wire) -> bool:
    """Return True if pin (x,y) lies on wire (any point on the segment, not just endpoints)."""
    pts = wire.points
    if len(pts) < 2:
        return False
    wx1, wy1 = round(pts[0][0], 4), round(pts[0][1], 4)
    wx2, wy2 = round(pts[-1][0], 4), round(pts[-1][1], 4)
    px, py = pin
    # Horizontal wire
    if _approx_eq(wy1, wy2) and _approx_eq(py, wy1):
        lo, hi = min(wx1, wx2), max(wx1, wx2)
        return lo - _TOL <= px <= hi + _TOL
    # Vertical wire
    if _approx_eq(wx1, wx2) and _approx_eq(px, wx1):
        lo, hi = min(wy1, wy2), max(wy1, wy2)
        return lo - _TOL <= py <= hi + _TOL
    return False


def check_placement(build_plan: BuildPlan, placement: PlacementPlan) -> list:
    """
    Check placement connectivity: every non-ground pin must be reachable from
    at least one other pin on the same net via co-location or wire.

    Returns list of error/warning strings. Empty list = all pins connected.

    Pin positions are looked up from ads_pdk/pin_offsets.yaml. Components not
    in the registry use a heuristic fallback and emit [CHECK-WARN] messages.
    """
    errors: list = []
    fallback_warnings: list = []

    registry = _load_pin_offsets()
    inst_map  = {pi.id: pi for pi in placement.instances}

    # ── 1. Collect pin positions per net ──────────────────────────────────────
    # net_pins: {node_name: [(x, y), ...]}
    net_pins: dict = {}

    def _add(node: str, x: float, y: float) -> None:
        if node and not _is_ground_node(node):
            net_pins.setdefault(node, []).append((round(x, 4), round(y, 4)))

    # Ports
    for port in placement.ports:
        if not port.name.startswith("VCTRL"):
            _add(port.node, port.x, port.y)

    # Component instances
    for bi in build_plan.instances:
        pi = inst_map.get(bi.id)
        if pi is None or bi.role == "gnd":
            continue
        for node, px, py in _get_pin_positions(bi, pi, registry, fallback_warnings):
            _add(node, px, py)

    # FET gate nodes: fetbias GATE pin and FET origin are co-located by design.
    # The fetbias entry in registry covers the GATE pin. The FET gate isn't in
    # bi.nodes, so we register it here by cross-referencing fetbias → FET id.
    for bi in build_plan.instances:
        if bi.role not in ("fet_series", "fet_shunt"):
            continue
        pi = inst_map.get(bi.id)
        if pi is None:
            continue
        # FET id = "Q_{suffix}", fetbias id = "BIAS_{suffix}"
        bias_id = "BIAS_" + bi.id[2:] if bi.id.startswith("Q_") else None
        if not bias_id:
            continue
        bias_bi = next((b for b in build_plan.instances if b.id == bias_id and b.nodes), None)
        if bias_bi:
            # FET gate is at FET origin — register gate node there so it can
            # co-locate with the fetbias GATE pin (also computed from registry).
            gate_node = bias_bi.nodes[0]
            _add(gate_node, pi.x, pi.y)

    # ── 2. Collect wire endpoints ─────────────────────────────────────────────
    wire_endpoints: set = set()
    for wire in placement.wires:
        for pt in wire.points:
            wire_endpoints.add((round(pt[0], 4), round(pt[1], 4)))

    # ── 3. Emit fallback warnings ─────────────────────────────────────────────
    errors.extend(fallback_warnings)

    # ── 4. Check each net ─────────────────────────────────────────────────────
    for node, pins in sorted(net_pins.items()):
        if not pins:
            continue

        for pin in pins:
            connected = False

            # (a) Co-located with another pin on the same net
            for other in pins:
                if other is not pin and _pt_eq(pin, other):
                    connected = True
                    break

            # (b) Pin is a wire endpoint
            if not connected and pin in wire_endpoints:
                connected = True

            # (c) Pin lies on any wire segment (catches mid-wire taps)
            if not connected:
                for wire in placement.wires:
                    if _pin_on_wire(pin, wire):
                        connected = True
                        break

            if not connected:
                errors.append(
                    f"[CHECK] net '{node}': pin at {pin} is floating "
                    f"(no co-located pin or wire on this net)"
                )

    return errors
