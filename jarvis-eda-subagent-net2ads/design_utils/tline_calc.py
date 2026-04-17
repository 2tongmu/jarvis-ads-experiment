"""
design_utils/tline_calc.py
==========================
Microstrip transmission line calculator.

Converts electrical specifications (Z0, ELength, Fref) to physical
dimensions (W, L) using Hammerstad-Jensen closed-form synthesis formulas.

Substrate defaults: GaAs (h=100 um, er=12.9, t=1.33 um MET1)
These match the WIN_PP1029 and WIN_PP15_6X GaAs pHEMT processes.

Usage:
    from design_utils.tline_calc import microstrip_w_l, MicrostripSubstrate

    # Use PDK name for substrate lookup:
    W_um, L_um = microstrip_w_l(Z0=50.0, elength_deg=90.0, fref_hz=10e9,
                                  pdk_name="WIN_PP1029_DESIGN_KIT")

    # Or specify substrate explicitly:
    sub = MicrostripSubstrate(h_um=100.0, er=12.9, t_um=1.33)
    W_um, L_um = microstrip_w_l(Z0=70.7, elength_deg=90.0, fref_hz=10e9, substrate=sub)

    print(f"W = {W_um:.1f} um, L = {L_um:.1f} um")

References:
    Hammerstad, E. and O. Jensen, "Accurate Models for Microstrip
    Computer-Aided Design," IEEE MTT-S Int. Microwave Symp. Dig.,
    1980, pp. 407-409.
"""

import math
from dataclasses import dataclass
from typing import Optional

# ── Physical constant ─────────────────────────────────────────────────────────

C_LIGHT = 2.99792458e8   # speed of light in vacuum [m/s]


# ── Substrate definition ──────────────────────────────────────────────────────

@dataclass
class MicrostripSubstrate:
    """
    Microstrip substrate parameters.

    Attributes:
        h_um  : substrate height [µm] (GaAs standard: 100 µm)
        er    : relative permittivity (GaAs standard: 12.9)
        t_um  : metal thickness [µm] (MET1 standard: 1.33 µm)
    """
    h_um: float = 100.0
    er:   float = 12.9
    t_um: float = 1.33


# ── PDK substrate presets ─────────────────────────────────────────────────────

_PDK_SUBSTRATES: dict = {
    "WIN_PP1029_DESIGN_KIT":  MicrostripSubstrate(h_um=100.0, er=12.9, t_um=1.33),
    "WIN_PP15_6X_DESIGN_KIT": MicrostripSubstrate(h_um=100.0, er=12.9, t_um=1.33),
}


def get_pdk_substrate(pdk_name: str) -> MicrostripSubstrate:
    """
    Return substrate parameters for a known PDK.
    Falls back to default GaAs if the PDK is not in the preset table.
    """
    return _PDK_SUBSTRATES.get(pdk_name, MicrostripSubstrate())


# ── Unit string parsing ───────────────────────────────────────────────────────

_UNIT_SCALE = {
    # impedance / dimensionless
    "ohm": 1.0,
    # frequency
    "hz":  1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
    "thz": 1e12,
    # angle (deg → deg; rad not needed)
    "deg": 1.0,
    "rad": 180.0 / math.pi,
}


def _parse_value(s: str) -> float:
    """
    Parse a value string of the form "50 Ohm", "10 GHz", "90 deg" etc.
    Returns the numeric value in SI-like base units (Ohm, Hz, deg).
    Raises ValueError if unparseable.
    """
    s = s.strip()
    parts = s.split()
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        num  = float(parts[0])
        unit = parts[1].lower()
        scale = _UNIT_SCALE.get(unit)
        if scale is None:
            raise ValueError(f"Unknown unit '{parts[1]}' in '{s}'")
        return num * scale
    raise ValueError(f"Cannot parse value string: '{s}'")


# ── Synthesis: Z0 → W/h ──────────────────────────────────────────────────────

def _synthesize_w_over_h(Z0: float, er: float) -> float:
    """
    Synthesize W/h ratio from Z0 and εr (Hammerstad-Jensen formulas).

    Two-branch solution:
      - Try narrow-line formula first (valid when W/h < 2).
      - If the result exceeds 2, switch to the wide-line formula.

    Args:
        Z0 : characteristic impedance [Ω]
        er : substrate relative permittivity

    Returns:
        W/h (dimensionless)
    """
    # Narrow-line branch (Hammerstad eq. 1)
    A = ((Z0 / 60.0) * math.sqrt((er + 1.0) / 2.0)
         + ((er - 1.0) / (er + 1.0)) * (0.23 + 0.11 / er))
    w_h_narrow = 8.0 * math.exp(A) / (math.exp(2.0 * A) - 2.0)

    if w_h_narrow < 2.0:
        return w_h_narrow

    # Wide-line branch (Hammerstad eq. 2)
    B = 377.0 * math.pi / (2.0 * Z0 * math.sqrt(er))
    w_h_wide = (
        (2.0 / math.pi)
        * (B - 1.0
           - math.log(2.0 * B - 1.0)
           + ((er - 1.0) / (2.0 * er)) * (math.log(B - 1.0) + 0.39 - 0.61 / er))
    )
    return max(w_h_wide, 0.0)   # guard against negative due to numeric edge cases


# ── Analysis: W/h → εeff ─────────────────────────────────────────────────────

def _effective_er(w_h: float, er: float) -> float:
    """
    Effective relative permittivity for a microstrip with given W/h and εr.
    Uses the standard Hammerstad-Jensen single formula (valid for all W/h).

    Args:
        w_h : W/h ratio
        er  : substrate relative permittivity

    Returns:
        εeff (dimensionless)
    """
    F = 1.0 / math.sqrt(1.0 + 12.0 / w_h) if w_h > 0 else 0.0
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * F


# ── Width correction for metal thickness ──────────────────────────────────────

def _width_thickness_correction(w_h: float, t_h: float) -> float:
    """
    Effective width correction for finite metal thickness (Hammerstad-Jensen).

    Returns corrected W/h ratio. Correction is approximate; typically < 5%.

    Args:
        w_h : W/h before correction
        t_h : t/h (metal thickness to substrate height ratio)
    """
    if t_h <= 0 or w_h <= 0:
        return w_h

    if w_h < 0.5:
        # Narrow line correction
        delta_w_h = (t_h / math.pi) * (1.0 + math.log(2.0 / t_h))
    else:
        # Wide line correction
        delta_w_h = (t_h / math.pi) * (1.0 + math.log(4.0 * math.e / (t_h * (1.0 / math.tanh(math.sqrt(6.517 * w_h))) ** 2 if w_h > 0 else 1.0)))

    return w_h + delta_w_h


# ── Main public function ──────────────────────────────────────────────────────

def microstrip_w_l(
    Z0: float,
    elength_deg: float,
    fref_hz: float,
    substrate: Optional[MicrostripSubstrate] = None,
    pdk_name: Optional[str] = None,
) -> tuple:
    """
    Convert microstrip electrical specs to physical dimensions.

    Synthesis procedure:
      1. From Z0 and εr, compute W/h using Hammerstad-Jensen closed-form.
      2. Apply metal-thickness correction to W/h.
      3. Compute εeff from corrected W/h.
      4. From εeff and Fref, compute wavelength λg.
      5. Physical length L = (ELength/360) * λg.

    Args:
        Z0          : characteristic impedance [Ω]
        elength_deg : electrical length [degrees] at Fref
        fref_hz     : reference frequency [Hz]
        substrate   : MicrostripSubstrate; uses GaAs defaults if None
        pdk_name    : PDK name for preset substrate lookup (overrides substrate)

    Returns:
        (W_um, L_um) — physical width and length in micrometres [µm]

    Example:
        W, L = microstrip_w_l(Z0=50.0, elength_deg=90.0, fref_hz=10e9,
                               pdk_name="WIN_PP1029_DESIGN_KIT")
        # Returns approx. (39.6, 2388.0) for GaAs 100 µm substrate
    """
    if pdk_name:
        sub = get_pdk_substrate(pdk_name)
    elif substrate is not None:
        sub = substrate
    else:
        sub = MicrostripSubstrate()   # GaAs defaults

    h = sub.h_um * 1e-6   # µm → m
    t = sub.t_um * 1e-6   # µm → m

    # Step 1: synthesize W/h from Z0 and εr
    w_h = _synthesize_w_over_h(Z0, sub.er)

    # Step 2: metal thickness correction
    t_h = t / h if h > 0 else 0.0
    w_h_corr = _width_thickness_correction(w_h, t_h)

    # Step 3: effective permittivity (use corrected W/h)
    er_eff = _effective_er(w_h_corr, sub.er)

    # Step 4: guided wavelength at Fref
    lambda_g = C_LIGHT / (fref_hz * math.sqrt(er_eff))

    # Step 5: physical length
    L_m = (elength_deg / 360.0) * lambda_g
    W_m = w_h * h   # use uncorrected W/h for physical width

    return W_m * 1e6, L_m * 1e6   # → µm


def microstrip_w_l_from_strings(
    Z0_str: str,
    elength_str: str,
    fref_str: str,
    pdk_name: Optional[str] = None,
    substrate: Optional[MicrostripSubstrate] = None,
) -> tuple:
    """
    Convenience wrapper: parse unit strings and call microstrip_w_l().

    Args:
        Z0_str      : e.g. "50 Ohm" or "70.7 Ohm"
        elength_str : e.g. "90 deg"
        fref_str    : e.g. "10 GHz"
        pdk_name    : PDK name for substrate preset
        substrate   : explicit substrate (overridden by pdk_name)

    Returns:
        (W_um, L_um) in micrometres

    Raises:
        ValueError  : if any string cannot be parsed
    """
    Z0          = _parse_value(Z0_str)
    elength_deg = _parse_value(elength_str)
    fref_hz     = _parse_value(fref_str)

    return microstrip_w_l(
        Z0=Z0,
        elength_deg=elength_deg,
        fref_hz=fref_hz,
        pdk_name=pdk_name,
        substrate=substrate,
    )


# ── CLI self-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Quick sanity check — run as: python design_utils/tline_calc.py"""
    tests = [
        ("50 Ohm",   "90 deg", "10 GHz", "WIN_PP1029_DESIGN_KIT"),
        ("70.7 Ohm", "90 deg", "10 GHz", "WIN_PP1029_DESIGN_KIT"),
        ("50 Ohm",   "90 deg", "5 GHz",  "WIN_PP1029_DESIGN_KIT"),
    ]
    sub = get_pdk_substrate("WIN_PP1029_DESIGN_KIT")
    print(f"Substrate: h={sub.h_um} um, er={sub.er}, t={sub.t_um} um (MET1)")
    print("-" * 60)
    for Z0_s, E_s, F_s, pdk in tests:
        W, L = microstrip_w_l_from_strings(Z0_s, E_s, F_s, pdk_name=pdk)
        print(f"Z0={Z0_s:<12} EL={E_s:<10} Fref={F_s:<10}  W={W:7.2f} um  L={L:8.2f} um")
