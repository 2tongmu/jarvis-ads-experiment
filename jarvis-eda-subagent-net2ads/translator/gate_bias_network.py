"""
gate_bias_network.py
====================
Gate bias network for GaAs pHEMT RF switch — netlist generator and
component value calculator.

Topology
--------
                    Rs_bias
V_ctrl ---+---[Rs_bias]--- G ---|< FET (Cgs to S/GND)
          |
        [Cp_bypass]
          |
         GND

  - Cp_bypass  : RF bypass cap, shunts control node to GND
  - Rs_bias    : series gate resistor, provides RF isolation and
                 defines the gate switching time constant
  - FET gate   : presents Cgs load (plus stray) to Rs_bias

Time constants
--------------
  tau_gate  = Rs_bias * Cgs_total          (gate charge, determines t_sw)
  tau_ctrl  = R_ctrl  * Cp_bypass          (control node settling)
  t_sw(10-90%) = 2.2 * tau_gate

Design rules (in priority order)
---------------------------------
  1. Stability  : Rs_bias >= 1000 Ω  (Cgd feedback / negative-Gm floor)
  2. RF isolation: Rs_bias >= 10 / (2*pi*f_high*Cgs)
  3. Switching speed: Rs_bias <= t_sw_target / (2.2 * Cgs)
  4. RF bypass  : Xc(Cp_bypass) < Rs_bias/10  at f_low
                  => Cp_bypass > 10 / (2*pi*f_low*Rs_bias)
  5. Ctrl speed : tau_ctrl < t_sw_target / 4   (ctrl node not the bottleneck)

Usage
-----
  # Basic: FET size only, defaults apply
  python gate_bias_network.py --ugw 160

  # Full spec:
  python gate_bias_network.py --ugw 160 --nof 2 --flow 2 --fhigh 18 \
      --tsw 10 --rctrl 50 --cgs_um 0.75 --cgd_um 0.15 --cstray 10

  # Generate netlist only:
  python gate_bias_network.py --ugw 100 --netlist_only

  # Suppress netlist, show only values:
  python gate_bias_network.py --ugw 160 --no_netlist
"""

import argparse
import math
import sys
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Physical / process constants (WIN Semi PP1029 defaults)
# ---------------------------------------------------------------------------
PP1029_CGS_UM   = 0.75   # fF/µm  intrinsic gate-source capacitance density
PP1029_CGD_UM   = 0.15   # fF/µm  gate-drain capacitance density (~20% of Cgs)
DEFAULT_CSTRAY  = 10.0   # fF     stray cap at gate metal node (via + pad)

# Stability floor — hard constraint for GaAs pHEMT (Cgd feedback / neg-Gm)
RS_STABILITY_FLOOR = 1000.0   # Ω

# RF bypass quality factor: Xc(Cp) < Rs/Q_bypass at f_low
Q_BYPASS = 10

# Switching time margin: ctrl node must settle in < t_sw / CTRL_MARGIN
CTRL_MARGIN = 4


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class FETParams:
    """Intrinsic FET parameters derived from process and geometry."""
    ugw:      float          # µm  total gate periphery
    nof:      int            # number of fingers
    ugw_per_finger: float    # µm  unit gate width
    cgs_um:   float          # fF/µm
    cgd_um:   float          # fF/µm
    cstray:   float          # fF  stray at gate node
    cgs:      float = field(init=False)   # fF  intrinsic Cgs
    cgd:      float = field(init=False)   # fF  intrinsic Cgd
    cgs_total: float = field(init=False)  # fF  Cgs + stray (effective load)

    def __post_init__(self):
        self.cgs       = self.ugw * self.cgs_um
        self.cgd       = self.ugw * self.cgd_um
        self.cgs_total = self.cgs + self.cstray


@dataclass
class BiasSpecs:
    """Target specifications for the bias network."""
    f_low:   float   # GHz  lower RF frequency
    f_high:  float   # GHz  upper RF frequency
    t_sw:    float   # ns   switching time (10–90%)
    r_ctrl:  float   # Ω    bias driver output impedance


@dataclass
class BiasComponents:
    """Calculated component values and design checks."""
    rs_bias:     float    # Ω
    cp_bypass:   float    # fF
    # Derived quantities
    tau_gate:    float    # ps
    t_sw_actual: float    # ns
    tau_ctrl:    float    # ps
    t_ctrl:      float    # ns
    xc_cp_flow:  float    # Ω   Xc of Cp_bypass at f_low
    xl_rs_flow:  float    # Ω   impedance Rs vs Zgate at f_low (isolation check)
    # Rule boundaries
    rs_min:      float    # Ω
    rs_max:      float    # Ω
    cp_min:      float    # fF
    cp_max:      Optional[float]  # fF  (None if driver is low-Z)
    # Pass/fail
    rs_ok:       bool
    cp_ok:       bool
    t_sw_ok:     bool
    t_ctrl_ok:   bool


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------
def calculate_bias(fet: FETParams, specs: BiasSpecs) -> BiasComponents:
    """
    Calculate Rs_bias and Cp_bypass from FET parameters and target specs.

    Returns a BiasComponents object with recommended values, design window
    boundaries, and pass/fail flags for every rule.
    """
    two_pi = 2.0 * math.pi
    Cgs_F  = fet.cgs_total * 1e-15   # convert fF -> F
    f_low  = specs.f_low  * 1e9       # GHz -> Hz
    f_high = specs.f_high * 1e9
    t_sw_s = specs.t_sw   * 1e-9      # ns  -> s

    # ------------------------------------------------------------------
    # Rs_bias design window
    # ------------------------------------------------------------------
    # Floor 1: stability (Cgd / neg-Gm) — process hard rule
    rs_floor_stability = RS_STABILITY_FLOOR

    # Floor 2: RF isolation  Rs >> |Zgate| at f_high
    #   |Zgate| = 1 / (2*pi*f_high*Cgs)   (capacitive gate)
    zgate_high = 1.0 / (two_pi * f_high * Cgs_F)
    rs_floor_isolation = 10.0 * zgate_high

    rs_min = max(rs_floor_stability, rs_floor_isolation)

    # Ceiling: switching speed  Rs <= t_sw / (2.2 * Cgs)
    rs_max = t_sw_s / (2.2 * Cgs_F)

    # Recommended: lowest value that clears both floors (maximises speed)
    if rs_max > rs_min:
        rs_recommended = rs_min          # tightest compliant value
    else:
        # Spec conflict: switching time too tight for this FET + stability rule
        rs_recommended = rs_min          # still use min; flag below

    # ------------------------------------------------------------------
    # Cp_bypass design window
    # ------------------------------------------------------------------
    # RF bypass floor: Xc(Cp) < Rs_bias / Q_bypass  at f_low
    #   => Cp > Q_bypass / (2*pi*f_low*Rs_recommended)
    cp_min_F = float(Q_BYPASS) / (two_pi * f_low * rs_recommended)
    cp_min   = cp_min_F * 1e15   # F -> fF

    # Speed ceiling (only meaningful if R_ctrl is non-negligible)
    if specs.r_ctrl >= 10.0:
        cp_max_F = (t_sw_s / CTRL_MARGIN) / (2.2 * specs.r_ctrl)
        cp_max   = cp_max_F * 1e15
    else:
        cp_max_F = None
        cp_max   = None

    # Recommended Cp: 3× the RF floor (good bypass margin), capped by speed
    cp_recommended = 3.0 * cp_min
    if cp_max is not None and cp_recommended > cp_max:
        cp_recommended = cp_max

    # ------------------------------------------------------------------
    # Time constants with recommended values
    # ------------------------------------------------------------------
    tau_gate_s    = rs_recommended * Cgs_F
    t_sw_actual   = 2.2 * tau_gate_s * 1e9   # ns

    if cp_max_F is not None:
        cp_for_ctrl = cp_recommended * 1e-15
    else:
        cp_for_ctrl = cp_recommended * 1e-15
    tau_ctrl_s    = specs.r_ctrl * cp_for_ctrl
    t_ctrl        = 2.2 * tau_ctrl_s * 1e9   # ns

    # ------------------------------------------------------------------
    # Verification quantities
    # ------------------------------------------------------------------
    xc_cp_flow = 1.0 / (two_pi * f_low * cp_recommended * 1e-15)
    xl_rs_flow = rs_recommended   # Rs is resistive; compare to Zgate at f_low
    zgate_low  = 1.0 / (two_pi * f_low * Cgs_F)

    # ------------------------------------------------------------------
    # Pass / fail
    # ------------------------------------------------------------------
    rs_ok    = (rs_min <= rs_recommended <= rs_max)
    cp_ok    = (cp_recommended >= cp_min) and \
               (cp_max is None or cp_recommended <= cp_max)
    t_sw_ok  = t_sw_actual <= specs.t_sw
    t_ctrl_ok = (specs.r_ctrl < 10.0) or (t_ctrl <= specs.t_sw / 2.0)

    return BiasComponents(
        rs_bias      = rs_recommended,
        cp_bypass    = cp_recommended,
        tau_gate     = tau_gate_s * 1e12,   # ps
        t_sw_actual  = t_sw_actual,
        tau_ctrl     = tau_ctrl_s * 1e12,   # ps
        t_ctrl       = t_ctrl,
        xc_cp_flow   = xc_cp_flow,
        xl_rs_flow   = xl_rs_flow,
        rs_min       = rs_min,
        rs_max       = rs_max,
        cp_min       = cp_min,
        cp_max       = cp_max,
        rs_ok        = rs_ok,
        cp_ok        = cp_ok,
        t_sw_ok      = t_sw_ok,
        t_ctrl_ok    = t_ctrl_ok,
    )


# ---------------------------------------------------------------------------
# Netlist generation
# ---------------------------------------------------------------------------
def generate_netlist(fet: FETParams, specs: BiasSpecs,
                     comp: BiasComponents, fet_name: str = "FET1") -> str:
    """
    Emit a SPICE-compatible netlist for the gate bias network.

    Node naming convention:
      ctrl    — V_ctrl terminal (bias supply)
      bias    — junction of Cp_bypass top plate and Rs_bias input
                (same node if Cp is right at the source side)
      gate    — FET gate terminal
      gnd     — ground / reference

    For this topology the ctrl node and bias node are the same:

        V_ctrl ──[Rs_bias]──── gate
                    |
                 [Cp_bypass]
                    |
                   gnd

    The FET Cgs is modelled as a shunt cap from gate to gnd.
    """
    rs_ohm  = comp.rs_bias
    cp_F    = comp.cp_bypass * 1e-15
    cgs_F   = fet.cgs_total  * 1e-15

    lines = []
    lines.append("* ============================================================")
    lines.append("* Gate bias network — GaAs pHEMT RF switch")
    lines.append(f"* FET: {fet_name}  UGW={fet.ugw:.0f}µm  NOF={fet.nof}")
    lines.append(f"* Process: WIN Semi PP1029 (CPW)")
    lines.append(f"* RF band: {specs.f_low:.1f}–{specs.f_high:.1f} GHz")
    lines.append(f"* t_sw target: {specs.t_sw:.1f} ns")
    lines.append("* ============================================================")
    lines.append("*")
    lines.append("* Nodes:")
    lines.append("*   ctrl  — bias control voltage input")
    lines.append("*   gate  — FET gate terminal")
    lines.append("*   0     — ground")
    lines.append("*")
    lines.append("* Topology:")
    lines.append("*")
    lines.append("*   ctrl ──[Rs_bias]──── gate ──┤ FET")
    lines.append("*     |                    |")
    lines.append("*  [Cp_bypass]           [Cgs_model]")
    lines.append("*     |                    |")
    lines.append("*    GND                  GND")
    lines.append("*")
    lines.append(f"* Rs_bias  : {_fmt_ohm(rs_ohm)}")
    lines.append(f"* Cp_bypass: {_fmt_cap(cp_F)}")
    lines.append(f"* Cgs_total: {_fmt_cap(cgs_F)}  (model only, not placed)")
    lines.append("* ============================================================")
    lines.append("")

    # Bias supply (ideal voltage source, AC = 0 for bias network analysis)
    lines.append("* Bias control source")
    lines.append("Vctrl  ctrl  0  DC -0.5  AC 0")
    lines.append("")

    # Cp_bypass: control node to GND
    lines.append("* RF bypass capacitor — shunts control node to GND")
    lines.append(f"Cp_bypass  ctrl  0  {cp_F:.4e}")
    lines.append("")

    # Rs_bias: control node to gate
    lines.append("* Gate series resistor — RF isolation + time constant")
    lines.append(f"Rs_bias  ctrl  gate  {rs_ohm:.1f}")
    lines.append("")

    # Cgs model: gate to GND (behavioural model of FET input)
    lines.append("* FET gate input capacitance (behavioural — replace with full model)")
    lines.append(f"Cgs_model  gate  0  {cgs_F:.4e}")
    lines.append("")

    # Optional: FET subcircuit call placeholder
    lines.append("* FET instance (connect drain/source to RF network)")
    lines.append(f"* X{fet_name}  drain  gate  source  WIN_PP1029_CPW")
    lines.append(f"* + UGW={fet.ugw_per_finger:.0f}  NOF={fet.nof}")
    lines.append("")

    lines.append(".tran 0.01n 20n  ; transient: observe gate switching")
    lines.append(".ac   dec 100 1e6 50e9  ; AC: verify bias impedance vs frequency")
    lines.append("")
    lines.append(".end")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _fmt_ohm(v: float) -> str:
    if v >= 1e6:  return f"{v/1e6:.2f} MΩ"
    if v >= 1e3:  return f"{v/1e3:.2f} kΩ"
    return f"{v:.1f} Ω"

def _fmt_cap(v: float) -> str:
    """Format capacitance in SI prefix notation."""
    if v >= 1e-9:  return f"{v*1e9:.3f} nF"
    if v >= 1e-12: return f"{v*1e12:.3f} pF"
    if v >= 1e-15: return f"{v*1e15:.3f} fF"
    return f"{v:.3e} F"

def _fmt_time(v_ns: float) -> str:
    if v_ns >= 1e3:  return f"{v_ns/1e3:.2f} µs"
    if v_ns >= 1:    return f"{v_ns:.3f} ns"
    return f"{v_ns*1e3:.2f} ps"

def _pass(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------
def print_report(fet: FETParams, specs: BiasSpecs, comp: BiasComponents,
                 show_netlist: bool, netlist: str) -> None:
    W = 62

    def hdr(title):
        print(f"\n{'─'*W}")
        print(f"  {title}")
        print(f"{'─'*W}")

    def row(label, value, status=None):
        stat = f"  [{_pass(status)}]" if status is not None else ""
        print(f"  {label:<36} {value}{stat}")

    print(f"\n{'═'*W}")
    print(f"  Gate Bias Network — GaAs pHEMT RF Switch")
    print(f"  WIN Semi PP1029 CPW Process")
    print(f"{'═'*W}")

    hdr("FET Parameters")
    row("Total gate periphery (UGW)",  f"{fet.ugw:.0f} µm")
    row("Number of fingers (NOF)",     f"{fet.nof}")
    row("Unit gate width",             f"{fet.ugw_per_finger:.0f} µm")
    row("Cgs density",                 f"{fet.cgs_um:.2f} fF/µm")
    row("Cgd density",                 f"{fet.cgd_um:.2f} fF/µm")
    row("Intrinsic Cgs",               f"{fet.cgs:.1f} fF")
    row("Gate node stray cap",         f"{fet.cstray:.1f} fF")
    row("Cgs_total (Cgs + stray)",     f"{fet.cgs_total:.1f} fF")

    hdr("Target Specifications")
    row("RF frequency range",          f"{specs.f_low:.1f} – {specs.f_high:.1f} GHz")
    row("Switching time (10–90%)",     f"{specs.t_sw:.1f} ns")
    row("Bias driver impedance",       f"{specs.r_ctrl:.0f} Ω")

    hdr("Design Rules & Windows")
    zgate = 1/(2*math.pi*specs.f_high*1e9*fet.cgs_total*1e-15)
    row("Rule 1 — Stability floor",    "Rs_bias ≥ 1000 Ω  (Cgd / neg-Gm)")
    row("Rule 2 — RF isolation floor", f"Rs_bias ≥ 10×|Zgate| = {10*zgate:.0f} Ω")
    row("Rule 3 — Rs_bias minimum",    f"{comp.rs_min:.0f} Ω  (max of rules 1&2)")
    row("Rule 3 — Rs_bias maximum",    f"{comp.rs_max:.0f} Ω  (switching ceiling)")
    row("Rule 4 — Cp_bypass minimum",  f"{comp.cp_min:.1f} fF  (RF bypass @ f_low)")
    if comp.cp_max is not None:
        row("Rule 4 — Cp_bypass maximum",
            f"{comp.cp_max:.1f} fF  (ctrl settling ceiling)")
    else:
        row("Rule 4 — Cp_bypass maximum",  "no limit (low-Z driver)")

    if comp.rs_max < comp.rs_min:
        print(f"\n  *** SPEC CONFLICT ***")
        print(f"  Rs window is infeasible: min={comp.rs_min:.0f} Ω > max={comp.rs_max:.0f} Ω")
        print(f"  => Increase t_sw, reduce UGW, or accept a slower switch.")

    hdr("Recommended Component Values")
    row("Rs_bias",     _fmt_ohm(comp.rs_bias))
    row("Cp_bypass",   _fmt_cap(comp.cp_bypass * 1e-15))

    hdr("Verification")
    row("τ_gate = Rs × Cgs_total",
        f"{comp.tau_gate:.1f} ps")
    row("t_sw (10–90%) = 2.2 × τ_gate",
        f"{_fmt_time(comp.t_sw_actual)}  (target {specs.t_sw:.1f} ns)",
        comp.t_sw_ok)
    row("Xc(Cp_bypass) @ f_low",
        f"{comp.xc_cp_flow:.1f} Ω  vs Rs={comp.rs_bias:.0f} Ω",
        comp.cp_ok)
    if specs.r_ctrl >= 10:
        row("τ_ctrl = R_ctrl × Cp",
            f"{comp.tau_ctrl:.1f} ps")
        row("t_ctrl (10–90%)",
            f"{_fmt_time(comp.t_ctrl)}  (< t_sw/2 = {specs.t_sw/2:.1f} ns?)",
            comp.t_ctrl_ok)
    row("Rs_bias within design window",
        f"{comp.rs_min:.0f}–{comp.rs_max:.0f} Ω",
        comp.rs_ok)

    overall = comp.rs_ok and comp.cp_ok and comp.t_sw_ok and comp.t_ctrl_ok
    print(f"\n  {'─'*W}")
    print(f"  Overall: {'ALL RULES SATISFIED' if overall else 'CHECK FLAGGED ITEMS'}")
    print(f"  {'─'*W}")

    if show_netlist:
        print(f"\n{'═'*W}")
        print(f"  SPICE Netlist")
        print(f"{'═'*W}\n")
        print(netlist)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Gate bias network calculator & netlist generator for "
                    "GaAs pHEMT RF switch (WIN Semi PP1029).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # FET geometry
    p.add_argument("--ugw",     type=float, required=True,
                   help="Total gate periphery in µm (e.g. 160 for 2×80)")
    p.add_argument("--nof",     type=int,   default=2,
                   help="Number of gate fingers (default: 2)")

    # Process parameters (optional, defaults to PP1029)
    p.add_argument("--cgs_um",  type=float, default=PP1029_CGS_UM,
                   help=f"Cgs density in fF/µm (default: {PP1029_CGS_UM})")
    p.add_argument("--cgd_um",  type=float, default=PP1029_CGD_UM,
                   help=f"Cgd density in fF/µm (default: {PP1029_CGD_UM})")
    p.add_argument("--cstray",  type=float, default=DEFAULT_CSTRAY,
                   help=f"Gate node stray cap in fF (default: {DEFAULT_CSTRAY})")

    # Specs
    p.add_argument("--flow",    type=float, default=2.0,
                   help="Lower RF frequency in GHz (default: 2.0)")
    p.add_argument("--fhigh",   type=float, default=18.0,
                   help="Upper RF frequency in GHz (default: 18.0)")
    p.add_argument("--tsw",     type=float, default=1.0,
                   help="Switching time target in ns (default: 1.0)")
    p.add_argument("--rctrl",   type=float, default=50.0,
                   help="Bias driver output impedance in Ω (default: 50)")

    # Output control
    p.add_argument("--netlist_only", action="store_true",
                   help="Print only the SPICE netlist, suppress design report")
    p.add_argument("--no_netlist",   action="store_true",
                   help="Suppress netlist, print only the design report")
    p.add_argument("--fet_name",     type=str, default="FET1",
                   help="FET instance name in netlist (default: FET1)")

    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()

    # Build objects
    ugw_per_finger = args.ugw / args.nof

    fet = FETParams(
        ugw            = args.ugw,
        nof            = args.nof,
        ugw_per_finger = ugw_per_finger,
        cgs_um         = args.cgs_um,
        cgd_um         = args.cgd_um,
        cstray         = args.cstray,
    )

    specs = BiasSpecs(
        f_low   = args.flow,
        f_high  = args.fhigh,
        t_sw    = args.tsw,
        r_ctrl  = args.rctrl,
    )

    comp    = calculate_bias(fet, specs)
    netlist = generate_netlist(fet, specs, comp, fet_name=args.fet_name)

    if args.netlist_only:
        print(netlist)
    elif args.no_netlist:
        print_report(fet, specs, comp, show_netlist=False, netlist=netlist)
    else:
        print_report(fet, specs, comp, show_netlist=True, netlist=netlist)


if __name__ == "__main__":
    main()
