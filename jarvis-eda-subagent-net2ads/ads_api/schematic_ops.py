"""
ads_api/schematic_ops.py
========================
Build schematic content: place components, ports, ground, and wires.

All functions take a `design` object (returned by cell_ops.open_or_create_schematic)
and a `session` object (from ads_session.get_ads_session).

Coordinate system (confirmed from net_to_ads_cell.py and ads_build_spdt_pdk.py):
  - Signal path runs left to right at y = 0.0
  - Shunt components at y = 0.0, hanging down to GND at y = −1.0
  - Port 1 (input, left):  x = 1.375
  - First shunt component: x = 2.875
  - First series component: x = 4.25  (when preceded by a shunt branch)
  - Component spacing: 2.0 schematic units between consecutive placements

Angle conventions (confirmed from ads_build_spdt_pdk.py mkR/mkC/mkGnd):
  R series:     angle = 0.0    (horizontal)
  L series:     angle = 0.0    (horizontal, confirmed 2026-04-15 ADS2026_Update1.2)
  C shunt:      angle = −90.0  (vertical, pin1 at signal node)
  GND:          angle = −90.0
  C series:     angle = 0.0

API status notes (all sourced from ADS_API_REFERENCE.md):
  design.find_or_add_net()       ✅ CONFIRMED (§5)
  design.add_term()              ✅ CONFIRMED (§6)
  design.add_instance()          ✅ CONFIRMED (§4)
  inst.parameters[key].value     ✅ CONFIRMED (§4)
  design.add_wire(points)        ✅ CONFIRMED (§8)
  de.LCVName('ads_rflib','R','symbol')  ✅ CONFIRMED (§11)
  de.LCVName('ads_rflib','C','symbol')  ✅ CONFIRMED (§11)
  de.LCVName('ads_rflib','GROUND','symbol') ✅ CONFIRMED (§11)
  de.LCVName('ads_rflib','L','symbol')  ✅ CONFIRMED 2026-04-15 (ADS2026_Update1.2, full pipeline)

Port implementation:
  design.add_term() creates a generic sub-cell pin — NOT a simulation Term with
  impedance. See CONSTRAINTS.md C1a. No 50 Ω or any impedance value is assigned.

Usage:
    from ads_api.ads_session import get_ads_session
    from ads_api.schematic_ops import place_port, place_resistor, place_capacitor, connect

    session = get_ads_session()
    # ... get design from cell_ops.open_or_create_schematic ...

    place_port(session, design, "P1", x=1.375, y=0.0)
    place_resistor(session, design, "R1_SER", value="50 Ohm", x=4.25, y=0.0, angle=0.0)
    place_capacitor(session, design, "C1_SH", value="2.0 pF", x=2.875, y=0.0, angle=-90.0)
    place_ground(session, design, "GND_C1_SH", x=2.875, y=-1.0)
    # Correct wiring: separate segments; ADS connects only at wire ENDPOINTS.
    # Do NOT draw a single polyline through component positions — it shorts them.
    # Do NOT draw an explicit shunt wire (P1→P2) — place_ground() handles the GND wire.
    connect(design, [(1.375, 0.0), (2.875, 0.0)])   # P1_port → C1_SH.P1 tap
    connect(design, [(2.875, 0.0), (4.25, 0.0)])    # C1_SH.P1 tap → R1_SER.P1
    # R1_SER.P2 (5.25) co-locates with P2 port (5.25) — no wire needed
"""

from ads_api.ads_session import ADSSession


# ── Ports ──────────────────────────────────────────────────────────────────────

def place_port(session: ADSSession, design, name: str, x: float, y: float, angle: float = 0.0):
    """
    Create a generic sub-cell pin (terminal) at the given position.

    This creates an electrical terminal on the cell interface — NOT a simulation
    Term component with an impedance value. See CONSTRAINTS.md C1a.

    Creates an electrical terminal AND a visible schematic pin marker via
    add_dot_for_pin + add_pin (confirmed locally 2026-04-14).

    Convention for angle:
        Left-side port (P1, input):   angle=180.0  (pin points left, outward)
        Right-side port (P2, output): angle=0.0    (pin points right, outward)

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : port name — used as both the ADS net name and term name
        x, y    : pin position in schematic units
        angle   : pin orientation — 180.0 for left ports, 0.0 for right ports

    Returns:
        term object

    API status:
        design.find_or_add_net(name)              ✅ CONFIRMED
        design.add_term(net, name, TermType)       ✅ CONFIRMED
        TermType.INPUT_OUTPUT from _pde.db         ✅ CONFIRMED
        design.add_dot_for_pin((x, y))             ✅ CONFIRMED locally 2026-04-14
        design.add_pin(term, dot, angle, annot)    ✅ CONFIRMED locally 2026-04-14
    """
    net  = design.find_or_add_net(name)                              # ✅ CONFIRMED
    term = design.add_term(net, name, session.TermType.INPUT_OUTPUT) # ✅ CONFIRMED

    # Attempt to create a visible schematic pin marker at (x, y).
    # add_dot_for_pin + add_pin are ⚠️ UNCONFIRMED (§12).  Non-fatal if unsupported.
    try:
        dot = design.add_dot_for_pin((x, y))
        design.add_pin(term, dot, angle=angle, add_annot=True)
        print(f"[port] '{name}' at ({x}, {y}) angle={angle} — pin marker added")
    except Exception as exc:
        print(f"[port] '{name}' at ({x}, {y}) — term only (pin marker failed: {exc})")

    return term


# ── Ground ─────────────────────────────────────────────────────────────────────

def place_ground(session: ADSSession, design, name: str, x: float, y: float):
    """
    Place an ads_rflib:GROUND symbol with angle=-90, offset one unit below (x, y),
    and draw an explicit wire from (x, y) down to the GND pin.

    IMPORTANT: y is the shunt component's P2 connection point (where the wire
    should land), NOT the GND instance origin. The GND is placed at (x, y-1.0)
    and an explicit wire connects (x, y) → (x, y-1.0).

    Pure co-location (two pins at the same coordinate with no wire) is NOT
    stitched by the ADS netlister — this causes "spare nodes/devices" in
    simulation. The explicit wire guarantees connectivity.
    # IMPROVED 2026-04-14: offset GND by -1 and add explicit wire to fix
    # "3 spare nodes / 3 spare devices" simulation stitching failure.

    Name convention: "GND_<companion_component_id>" (e.g., "GND_C1_SH").

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name for the ground symbol
        x, y    : connection point (shunt component P2 pin position)

    Returns:
        ground instance

    API status:
        de.LCVName('ads_rflib','GROUND','symbol')  ✅ CONFIRMED
        design.add_instance(lcv, (x,y), name, angle)  ✅ CONFIRMED
        design.add_wire(points)                        ✅ CONFIRMED
    """
    gnd_y = y - 1.0
    inst = design.add_instance(
        session.de.LCVName("ads_rflib", "GROUND", "symbol"),  # ✅ CONFIRMED
        (x, gnd_y),
        name=name,
        angle=-90.0,   # confirmed from ads_build_spdt_pdk.py mkGnd()
    )
    design.add_wire([(x, y), (x, gnd_y)])  # explicit wire: shunt.P2 → GND.P1
    print(f"[gnd] '{name}' at ({x}, {gnd_y}), wire ({x},{y})->({x},{gnd_y})")
    return inst


# ── Passive components ─────────────────────────────────────────────────────────

def place_resistor(
    session: ADSSession,
    design,
    name: str,
    value: str,
    x: float,
    y: float,
    angle: float = 0.0,
):
    """
    Place an ads_rflib:R resistor and set its R parameter.

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name (e.g. "R1_SER")
        value   : resistance string with unit (e.g. "50 Ohm", "1000 Ohm")
        x, y    : placement origin in schematic units
        angle   : rotation in degrees — 0.0 for series (horizontal), default

    Returns:
        resistor instance

    API status:
        de.LCVName('ads_rflib','R','symbol')    ✅ CONFIRMED
        inst.parameters["R"].value = expr       ✅ CONFIRMED
    """
    inst = design.add_instance(
        session.de.LCVName("ads_rflib", "R", "symbol"),  # ✅ CONFIRMED
        (x, y),
        name=name,
        angle=angle,
    )
    inst.parameters["R"].value = value   # ✅ CONFIRMED
    print(f"[R] '{name}' R={value} at ({x}, {y}) angle={angle}")
    return inst


def place_capacitor(
    session: ADSSession,
    design,
    name: str,
    value: str,
    x: float,
    y: float,
    angle: float = -90.0,
):
    """
    Place an ads_rflib:C capacitor and set its C parameter.

    Default angle is -90.0 (shunt orientation: pin1 at signal node, pointing down).
    For a series capacitor, pass angle=0.0 explicitly.

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name (e.g. "C1_SH")
        value   : capacitance string with unit (e.g. "2.0 pF", "1.2 pF")
        x, y    : placement origin in schematic units
        angle   : -90.0 (shunt, confirmed) or 0.0 (series)

    Returns:
        capacitor instance

    API status:
        de.LCVName('ads_rflib','C','symbol')    ✅ CONFIRMED
        inst.parameters["C"].value = expr       ✅ CONFIRMED
    """
    inst = design.add_instance(
        session.de.LCVName("ads_rflib", "C", "symbol"),  # ✅ CONFIRMED
        (x, y),
        name=name,
        angle=angle,
    )
    inst.parameters["C"].value = value   # ✅ CONFIRMED
    print(f"[C] '{name}' C={value} at ({x}, {y}) angle={angle}")
    return inst


def place_inductor(
    session: ADSSession,
    design,
    name: str,
    value: str,
    x: float,
    y: float,
    angle: float = 0.0,
):
    """
    Place an ads_rflib:L inductor and set its L parameter.

    CONFIRMED: de.LCVName('ads_rflib','L','symbol') verified 2026-04-15 on
    ADS2026_Update1.2 via full pipeline run (verify_phase1.py). L param key = "L".
    See MEMORY.md OI-02 (resolved).

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name (e.g. "L1_SER")
        value   : inductance string with unit (e.g. "3.3 nH", "7.958 nH")
        x, y    : placement origin in schematic units
        angle   : 0.0 for series (horizontal), default

    Returns:
        inductor instance

    API status:
        de.LCVName('ads_rflib','L','symbol')    ✅ CONFIRMED 2026-04-15
        inst.parameters["L"].value = expr       ✅ CONFIRMED 2026-04-15
    """
    inst = design.add_instance(
        session.de.LCVName("ads_rflib", "L", "symbol"),  # ✅ CONFIRMED
        (x, y),
        name=name,
        angle=angle,
    )
    inst.parameters["L"].value = value   # ✅ CONFIRMED; key "L"
    print(f"[L] '{name}' L={value} at ({x}, {y}) angle={angle}")
    return inst


# ── Generic instance dispatch ─────────────────────────────────────────────────

# Registry: ads_cell name -> (param_key, default_value, placer_function)
# Add entries here when new component types are confirmed (e.g. TLIN in Phase 2).
_PASSIVE_PLACER_REGISTRY: dict = {}   # populated after function definitions below


def place_instance(session: "ADSSession", design, inst) -> object:
    """
    Dispatch a PlacedInstance to the correct place_* function by inst.ads_cell.

    Handles GND role first, then looks up the component type in the placer
    registry. Raises ValueError for unknown types — the error message names
    the exact function to update (_PASSIVE_PLACER_REGISTRY in schematic_ops.py).

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        inst    : PlacedInstance from placement_engine.compute_placement()
                  Must have: .role, .ads_cell, .id, .x, .y, .angle, .params

    Returns:
        The placed instance object (from the underlying place_* call).

    Extending for new component types:
        Add a handler to _PASSIVE_PLACER_REGISTRY at the bottom of schematic_ops.py:
            _PASSIVE_PLACER_REGISTRY["TLIN"] = _place_TLIN

    API status:
        All dispatched calls use CONFIRMED API patterns — see individual place_*
        functions above.
    """
    if inst.role == "gnd":
        return place_ground(session, design, inst.id, x=inst.x, y=inst.y)

    handler = _PASSIVE_PLACER_REGISTRY.get(inst.ads_cell)
    if handler is None:
        raise ValueError(
            f"No placer registered for ads_cell='{inst.ads_cell}' (instance '{inst.id}').\n"
            "Add a handler to _PASSIVE_PLACER_REGISTRY in ads_api/schematic_ops.py."
        )
    return handler(session, design, inst)


def _ph_R(session, design, inst):
    return place_resistor(session, design, inst.id,
                          value=inst.params.get("R", "0 Ohm"),
                          x=inst.x, y=inst.y, angle=inst.angle)


def _ph_L(session, design, inst):
    return place_inductor(session, design, inst.id,
                          value=inst.params.get("L", "1 nH"),
                          x=inst.x, y=inst.y, angle=inst.angle)


def _ph_C(session, design, inst):
    return place_capacitor(session, design, inst.id,
                           value=inst.params.get("C", "1 pF"),
                           x=inst.x, y=inst.y, angle=inst.angle)


# Register all confirmed passive component types (Phase 1)
_PASSIVE_PLACER_REGISTRY["R"] = _ph_R   # ✅ CONFIRMED
_PASSIVE_PLACER_REGISTRY["L"] = _ph_L   # ✅ CONFIRMED 2026-04-15
_PASSIVE_PLACER_REGISTRY["C"] = _ph_C   # ✅ CONFIRMED


# ── Phase 2: PDK transmission line placer ─────────────────────────────────────

def _place_pdk_tline(session: "ADSSession", design, inst) -> object:
    """
    Generic placer for PDK microstrip transmission line cells.

    Places any PDK tline cell (e.g. PP1029_mlin from WIN_PP1029_DESIGN_KIT) using
    the confirmed design.add_instance() + inst.parameters[key].value pattern.

    Parameters in inst.params are set one by one with individual try/except so
    that a missing or renamed parameter does not abort the whole placement.
    Unknown parameter names are logged as warnings, not fatal errors.

    API status:
        de.LCVName(ads_lib, ads_cell, "symbol")    ✅ CONFIRMED (same as ads_rflib)
        design.add_instance(lcv, (x,y), name, angle) ✅ CONFIRMED
        inst.parameters[key].value = expr            ✅ CONFIRMED
    """
    ads_inst = design.add_instance(
        session.de.LCVName(inst.ads_lib, inst.ads_cell, inst.ads_view),  # ✅ CONFIRMED
        (inst.x, inst.y),
        name=inst.id,
        angle=inst.angle,
    )
    set_ok = []
    set_fail = []
    for k, v in inst.params.items():
        try:
            ads_inst.parameters[k].value = v   # ✅ CONFIRMED
            set_ok.append(f"{k}={v}")
        except (KeyError, AttributeError) as exc:
            set_fail.append(f"{k}={v} ({exc})")

    print(f"[tline] '{inst.id}' {inst.ads_lib}:{inst.ads_cell} "
          f"@ ({inst.x}, {inst.y}) angle={inst.angle}")
    if set_ok:
        print(f"  params set   : {', '.join(set_ok)}")
    if set_fail:
        print(f"  params FAILED: {', '.join(set_fail)}")
        print(f"  NOTE: Probe actual param names via build_pdk_yaml.py and update ads_mapping.yaml")
    return ads_inst


# Register Phase 2: PDK microstrip tline cell
_PASSIVE_PLACER_REGISTRY["PP1029_mlin"] = _place_pdk_tline


# ── Sub-circuit instances ──────────────────────────────────────────────────────

def place_subcircuit(
    session: ADSSession,
    design,
    name: str,
    lib_name: str,
    cell_name: str,
    x: float,
    y: float,
    angle: float = 0.0,
    view: str = "symbol",
):
    """
    Place a sub-circuit instance (a cell from any open library).

    Uses the same de.LCVName / add_instance API as ads_rflib components.
    The sub-circuit must already exist with the requested view in lib_name.

    Args:
        session   : ADSSession
        design    : schematic design object (WRITE mode)
        name      : instance name (e.g. "I_RC")
        lib_name  : library that owns the cell (e.g. "net2ads_lib")
        cell_name : cell name (e.g. "rc_series_shunt")
        x, y      : placement origin in schematic units
        angle     : rotation in degrees (default 0.0)
        view      : view name (default "symbol")

    Returns:
        instance object

    API status:
        de.LCVName(lib_name, cell_name, view)              ✅ CONFIRMED (same as ads_rflib)
        design.add_instance(lcv, (x,y), name, angle)       ✅ CONFIRMED
    """
    inst = design.add_instance(
        session.de.LCVName(lib_name, cell_name, view),
        (x, y),
        name=name,
        angle=angle,
    )
    print(f"[subckt] '{name}' ({lib_name}:{cell_name}:{view}) @ ({x}, {y}) angle={angle}")
    return inst


# ── Wiring ─────────────────────────────────────────────────────────────────────

def connect(design, points: list) -> None:
    """
    Draw a wire polyline through the given list of (x, y) coordinate pairs.

    One call to connect() = one polyline segment in ADS.
    ADS auto-connects wire endpoints to component pins and terms when
    coordinates match exactly — no explicit net assignment needed.

    Wire endpoint coordinates must EXACTLY match component pin snap_points.
    ADS places components silently even when wires miss pins — always use
    confirmed coordinate values from MEMORY.md Section 2.

    Args:
        design : schematic design object (WRITE mode)
        points : list of (x, y) tuples, e.g. [(1.375, 0.0), (2.875, 0.0), (4.25, 0.0)]

    API status:
        design.add_wire([(x1,y1),(x2,y2),...])   ✅ CONFIRMED
    """
    design.add_wire(points)   # ✅ CONFIRMED
    print(f"[wire] {points}")


# ── Design variables ───────────────────────────────────────────────────────────

def set_design_variables(design, variables: list) -> None:
    """
    Write cell-level design variables (parametric defaults).

    Only needed when component parameter values reference variable names
    (e.g., value="Rs" referencing variable Rs="1000 Ohm"). For Phase 1
    (literal values like "50 Ohm"), this call can be skipped.

    Args:
        design    : schematic design object (WRITE mode)
        variables : list of (name, value_string) tuples
                    e.g. [("Rs", "1000 Ohm"), ("Cp", "1 pF")]

    API status:
        design.cell.write_design_variables([...])   ✅ CONFIRMED
    """
    if not variables:
        return
    design.cell.write_design_variables(variables)  # ✅ CONFIRMED
    for name, value in variables:
        print(f"[var] {name} = {value}")
