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
  L series:     angle = 0.0    (horizontal, assumed — not yet Jarvis-confirmed)
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
  de.LCVName('ads_rflib','L','symbol')  ⚠️ UNCONFIRMED (§11) — needs Jarvis probe

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
    connect(design, [(1.375, 0.0), (2.875, 0.0), (4.25, 0.0), (5.25, 0.0)])
    connect(design, [(2.875, 0.0), (2.875, -1.0)])
"""

from ads_api.ads_session import ADSSession


# ── Ports ──────────────────────────────────────────────────────────────────────

def place_port(session: ADSSession, design, name: str, x: float, y: float):
    """
    Create a generic sub-cell pin (terminal) at the given position.

    This creates an electrical terminal on the cell interface — NOT a simulation
    Term component with an impedance value. See CONSTRAINTS.md C1a.

    The terminal position is implicit: it is established by the wire endpoint
    that lands at (x, y). ADS connects wires to terms by net name, not by
    graphical pin position (for sub-cell pins created via add_term).

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : port name — used as both the ADS net name and term name
        x, y    : wire endpoint coordinates (schematic units) — place a wire
                  endpoint here in connect() to associate the port with the net

    Returns:
        term object

    API status:
        design.find_or_add_net(name)              ✅ CONFIRMED
        design.add_term(net, name, TermType)       ✅ CONFIRMED
        TermType.INPUT_OUTPUT from _pde.db         ✅ CONFIRMED
    """
    net  = design.find_or_add_net(name)                              # ✅ CONFIRMED
    term = design.add_term(net, name, session.TermType.INPUT_OUTPUT) # ✅ CONFIRMED
    print(f"[port] '{name}' at ({x}, {y})")
    return term


# ── Ground ─────────────────────────────────────────────────────────────────────

def place_ground(session: ADSSession, design, name: str, x: float, y: float):
    """
    Place an ads_rflib:GROUND symbol at (x, y) with angle=-90.

    The standard GND position is y=-1.0 (one unit below the signal path at y=0).
    Name convention: "GND_<companion_component_id>" (e.g., "GND_C1_SH").

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name for the ground symbol
        x, y    : placement origin in schematic units

    Returns:
        ground instance

    API status:
        de.LCVName('ads_rflib','GROUND','symbol')  ✅ CONFIRMED
        design.add_instance(lcv, (x,y), name, angle)  ✅ CONFIRMED
    """
    inst = design.add_instance(
        session.de.LCVName("ads_rflib", "GROUND", "symbol"),  # ✅ CONFIRMED
        (x, y),
        name=name,
        angle=-90.0,   # confirmed from ads_build_spdt_pdk.py mkGnd()
    )
    print(f"[gnd] '{name}' at ({x}, {y})")
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

    ⚠️ UNCONFIRMED: de.LCVName('ads_rflib','L','symbol') — the LCV name for
    inductors has not yet been verified by Jarvis execution (ADS_API_REFERENCE.md §11).
    This call is wrapped in a try/except so a failed probe is surfaced clearly
    rather than silently corrupting the schematic.

    Action required: run on Jarvis and update MEMORY.md OI-02 with the result.

    Args:
        session : ADSSession
        design  : schematic design object (WRITE mode)
        name    : instance name (e.g. "L1_SER")
        value   : inductance string with unit (e.g. "3.3 nH", "7.958 nH")
        x, y    : placement origin in schematic units
        angle   : 0.0 for series (horizontal), default

    Returns:
        inductor instance

    Raises:
        RuntimeError : if ads_rflib:L:symbol is not found in ADS
    """
    try:
        inst = design.add_instance(
            session.de.LCVName("ads_rflib", "L", "symbol"),  # ⚠️ UNCONFIRMED
            (x, y),
            name=name,
            angle=angle,
        )
        inst.parameters["L"].value = value   # ✅ CONFIRMED pattern; key "L" assumed
        print(f"[L] '{name}' L={value} at ({x}, {y}) angle={angle}")
        return inst
    except Exception as exc:
        raise RuntimeError(
            f"Failed to place inductor '{name}' via ads_rflib:L:symbol.\n"
            f"Error: {exc}\n"
            "This LCV name is UNCONFIRMED. Verify the correct ADS cell name for "
            "inductors in ads_rflib and update MEMORY.md OI-02."
        ) from exc


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
