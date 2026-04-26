"""
fet_bias_preprocessor.py
========================
Pre-processor for netlists containing abstract FET placeholders (SW elements).

For each SW element in the netlist:
  1. Classifies role: series or shunt (from topology)
  2. Looks up typical FET sizing from PDK core YAML
  3. Calculates gate bias Rs/Cp using gate_bias_network.calculate_bias()
  4. Assigns control voltage: on=0V, off=-1.5V (PP10 confirmed values)

Outputs:
  - <example_dir>/fetbias_sw_gate/fetbias_sw_gate_research.net
      One reusable fetbias cell. R uses 'R=Rs', C uses 'C=Cp' so they
      reference ADS design variables. Default values = series FET calculated.
  - <example_dir>/<stem>_sw_map.yaml
      Per-instance annotation: FET size, role, Vgate, Rs, Cp.
      Consumed by ads_mapper.py during SPDT build plan generation.

Switch role classification
--------------------------
  series  : SW where both nodes are signal nodes (not ground, not termination)
  shunt   : SW where the downstream path leads to a termination resistor to GND

This logic is switch-topology specific. For amplifier gate bias, add a
_classify_amp_roles() function below — the bias calculation and netlist
generation machinery is reused unchanged.

Usage
-----
  python translator/fet_bias_preprocessor.py \\
      examples/spdt_switch/spdt_switch_research.net \\
      --pdk-config path/to/WIN_PP1029_core.yaml \\
      --bias-rules path/to/switch_gate_bias.yaml

  Or call process_switch_netlist() directly from net2ads.py.
"""

import argparse
import math
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Repo paths — allow imports from jarvis-eda-learning without installation
# ---------------------------------------------------------------------------
_THIS_DIR    = Path(__file__).resolve().parent
_SUBAGENT    = _THIS_DIR.parent
_LEARNING    = _SUBAGENT.parent / "jarvis-eda-learning" / "workspace-scripts"
if str(_LEARNING) not in sys.path:
    sys.path.insert(0, str(_LEARNING))

# gate_bias_network lives in jarvis-eda-learning
try:
    from gate_bias_network import FETParams, BiasSpecs, calculate_bias
    _BIAS_AVAILABLE = True
except ImportError:
    _BIAS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Default PDK / bias config paths (relative to subagent root)
# ---------------------------------------------------------------------------
_DEFAULT_PDK_CONFIG  = _SUBAGENT / "ads_pdk" / "pdk_configs" / "WIN_PP1029_core.yaml"
_DEFAULT_BIAS_RULES  = (_SUBAGENT.parent / "jarvis-eda-learning" /
                        "bias-rules" / "switch_gate_bias.yaml")

# Control voltages for PP10 process (user-confirmed 2026-04-26)
VGATE_ON  =  0.0   # V  FET on-state
VGATE_OFF = -1.5   # V  FET off-state


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class SwInstance:
    """One SW element from the parsed netlist."""
    name:   str       # e.g. SW_SERIES_A
    node1:  str
    node2:  str
    state:  str       # 'ON' or 'OFF'


@dataclass
class FetMapping:
    """Full annotation for one SW → FET substitution."""
    sw_name:   str
    role:      str       # 'series' or 'shunt'
    nof:       int
    ugw_um:    float     # total gate periphery µm
    vgate:     float     # V
    rs_ohm:    float     # calculated Rs bias resistor
    cp_ff:     float     # calculated Cp bypass capacitor in fF
    ads_lib:   str
    ads_cell:  str


# ---------------------------------------------------------------------------
# Netlist parsing helpers (minimal — only extracts SW elements + ground refs)
# ---------------------------------------------------------------------------
def _parse_sw_elements(net_path: Path) -> List[SwInstance]:
    """Extract SW lines from research netlist. Returns list of SwInstance."""
    instances = []
    with open(net_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.upper().startswith("SW:"):
                tokens = line.split()
                type_name = tokens[0]            # SW:SW_SERIES_A
                name      = type_name.split(":")[1]
                node1     = tokens[1]
                node2     = tokens[2]
                params    = {k: v for t in tokens[3:]
                             if "=" in t for k, v in [t.split("=", 1)]}
                state     = params.get("State", "ON").upper()
                instances.append(SwInstance(name=name, node1=node1,
                                            node2=node2, state=state))
    return instances


def _parse_all_nodes(net_path: Path) -> Dict[str, List[str]]:
    """
    Build a map of node → list of component names connected to it.
    Used for shunt classification (detect termination chain to GND).
    """
    node_map: Dict[str, List[str]] = {}
    with open(net_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            if line.upper().startswith((".SUBCKT", ".ENDS", "PORT:")):
                continue
            tokens = line.split()
            if len(tokens) < 3 or ":" not in tokens[0]:
                continue
            name = tokens[0]
            for node in tokens[1:]:
                if "=" in node:
                    break
                node_map.setdefault(node, []).append(name)
    return node_map


# ---------------------------------------------------------------------------
# Role classification
# ---------------------------------------------------------------------------
def _is_shunt_sw(sw: SwInstance, node_map: Dict[str, List[str]]) -> bool:
    """
    A SW is shunt if its far node (node2) leads to a termination resistor
    that connects to ground (node '0'). Walk one hop from node2.

    Series SW: both nodes are internal signal nodes (no GND path via R).
    """
    far_node = sw.node2
    neighbors = node_map.get(far_node, [])
    for comp in neighbors:
        # Skip the SW itself
        if sw.name in comp:
            continue
        # If a resistor connects the far node to GND → shunt
        if comp.upper().startswith("R:"):
            # Check if GND (node '0') is reachable from this resistor
            for node, comps in node_map.items():
                if node == "0" and comp in comps:
                    return True
    return False


def classify_roles(sw_list: List[SwInstance],
                   node_map: Dict[str, List[str]]) -> Dict[str, str]:
    """Return {sw_name: 'series'|'shunt'} for each SW element."""
    roles = {}
    for sw in sw_list:
        roles[sw.name] = "shunt" if _is_shunt_sw(sw, node_map) else "series"
    return roles


# ---------------------------------------------------------------------------
# PDK config loading
# ---------------------------------------------------------------------------
def _load_pdk_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _typical_fet_size(pdk: dict, role: str):
    """
    Return (nof, ugw_um) from pdk component_map typical_params.
    role: 'series' or 'shunt'
    """
    key = "series_switch" if role == "series" else "shunt_switch"
    for entry in pdk.get("component_map", []):
        tp = entry.get("typical_params", {})
        if key in tp:
            rec = tp[key]
            nof = int(rec.get("NOF", 2))
            ugw_str = str(rec.get("UGW", "80 um"))
            ugw_um  = float(ugw_str.replace("um", "").replace("µm", "").strip())
            total_ugw = nof * ugw_um
            return nof, total_ugw
    # Fallback
    return (2, 160.0) if role == "series" else (2, 100.0)


def _ads_lcv_for_role(pdk: dict, role: str):
    """Return (ads_lib, ads_cell) for the given switch role."""
    rfscikit = ("TRANSISTOR_SWITCH_SERIES" if role == "series"
                else "TRANSISTOR_SWITCH_SHUNT")
    for entry in pdk.get("component_map", []):
        if entry.get("rfscikit_type") == rfscikit:
            return entry["ads_lib"], entry["ads_cell"]
    return "WIN_PP1029_DESIGN_KIT", "WIN_PP1029_CPW"


# ---------------------------------------------------------------------------
# Bias calculation
# ---------------------------------------------------------------------------
def _calc_bias(nof: int, ugw_um: float, bias_specs: dict) -> tuple:
    """
    Calculate (Rs_ohm, Cp_ff) for a FET with given total gate periphery.
    Returns rounded values suitable for netlist / design variables.
    """
    if not _BIAS_AVAILABLE:
        # Fallback: simple heuristic when gate_bias_network not importable
        cgs_ff = ugw_um * 0.75 + 10.0
        rs = max(1000.0, 10.0 / (2 * math.pi * 18e9 * cgs_ff * 1e-15))
        cp = 30.0 * (10.0 / (2 * math.pi * 2e9 * rs))
        return round(rs, 1), round(cp, 2)

    fet = FETParams(
        ugw           = ugw_um,
        nof           = nof,
        ugw_per_finger= ugw_um / nof,
        cgs_um        = 0.75,
        cgd_um        = 0.15,
        cstray        = 10.0,
    )
    specs = BiasSpecs(
        f_low  = bias_specs.get("specs", {}).get("f_low",  2.0),
        f_high = bias_specs.get("specs", {}).get("f_high", 18.0),
        t_sw   = bias_specs.get("specs", {}).get("t_sw",   1.0),
        r_ctrl = bias_specs.get("specs", {}).get("r_ctrl", 50.0),
    )
    comp = calculate_bias(fet, specs)
    return round(comp.rs_bias, 1), round(comp.cp_bypass, 2)


# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------
def process_switch_netlist(
    net_path:    Path,
    pdk_config:  Path = _DEFAULT_PDK_CONFIG,
    bias_rules:  Path = _DEFAULT_BIAS_RULES,
) -> List[FetMapping]:
    """
    Process a research netlist containing SW elements.

    Returns list of FetMapping (one per SW), and writes:
      - <net_dir>/fetbias_sw_gate/fetbias_sw_gate_research.net
      - <net_dir>/<stem>_sw_map.yaml

    The fetbias .net uses series FET Rs/Cp as default design variable values.
    Shunt FET instances in the parent schematic override Rs/Cp at instance level.
    """
    pdk   = _load_pdk_config(pdk_config)
    bias  = yaml.safe_load(open(bias_rules, encoding="utf-8")) if bias_rules.exists() else {}

    sw_list  = _parse_sw_elements(net_path)
    node_map = _parse_all_nodes(net_path)
    roles    = classify_roles(sw_list, node_map)

    if not sw_list:
        print("[fet_bias_preprocessor] No SW elements found — nothing to do.")
        return []

    print(f"[fet_bias_preprocessor] Found {len(sw_list)} SW elements:")

    mappings: List[FetMapping] = []
    for sw in sw_list:
        role = roles[sw.name]
        nof, ugw_um = _typical_fet_size(pdk, role)
        ads_lib, ads_cell = _ads_lcv_for_role(pdk, role)
        rs, cp = _calc_bias(nof, ugw_um, bias)
        vgate  = VGATE_ON if sw.state == "ON" else VGATE_OFF

        m = FetMapping(
            sw_name  = sw.name,
            role     = role,
            nof      = nof,
            ugw_um   = ugw_um,
            vgate    = vgate,
            rs_ohm   = rs,
            cp_ff    = cp,
            ads_lib  = ads_lib,
            ads_cell = ads_cell,
        )
        mappings.append(m)
        print(f"  {sw.name:<20} role={role:<6}  UGW={ugw_um:.0f}um  "
              f"Rs={rs:.1f}Ohm  Cp={cp:.2f}fF  Vgate={vgate:+.1f}V")

    _write_sw_map(net_path, mappings)
    _write_fetbias_netlist(net_path, mappings)
    return mappings


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def _write_sw_map(net_path: Path, mappings: List[FetMapping]) -> Path:
    """Write <stem>_sw_map.yaml alongside the netlist."""
    stem    = net_path.stem.replace("_research", "")
    out     = net_path.parent / f"{stem}_sw_map.yaml"
    payload = {
        "source_netlist": str(net_path),
        "sw_mappings": [
            {
                "sw_name":   m.sw_name,
                "role":      m.role,
                "nof":       m.nof,
                "ugw_um":    m.ugw_um,
                "vgate_v":   m.vgate,
                "rs_ohm":    m.rs_ohm,
                "cp_ff":     m.cp_ff,
                "ads_lib":   m.ads_lib,
                "ads_cell":  m.ads_cell,
            }
            for m in mappings
        ],
    }
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(payload, f, default_flow_style=False, sort_keys=False)
    print(f"[fet_bias_preprocessor] wrote sw_map : {out}")
    return out


def _write_fetbias_netlist(net_path: Path, mappings: List[FetMapping]) -> Path:
    """
    Write fetbias_sw_gate_research.net into a fetbias_sw_gate/ subfolder.

    Uses series FET Rs/Cp as the default design variable values.
    R component uses 'R=Rs' and C uses 'C=Cp' so they reference ADS
    design variables — allowing per-instance override in the parent SPDT
    schematic.
    """
    # Pick series FET values as the cell defaults
    series = [m for m in mappings if m.role == "series"]
    shunt  = [m for m in mappings if m.role == "shunt"]

    if series:
        rs_default = series[0].rs_ohm
        cp_default = series[0].cp_ff
        rs_shunt   = shunt[0].rs_ohm if shunt else rs_default
        cp_shunt   = shunt[0].cp_ff  if shunt else cp_default
    else:
        rs_default = mappings[0].rs_ohm
        cp_default = mappings[0].cp_ff
        rs_shunt   = rs_default
        cp_shunt   = cp_default

    out_dir = net_path.parent / "fetbias_sw_gate"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "fetbias_sw_gate_research.net"

    lines = [
        "; ================================================================",
        "; fetbias_sw_gate_research.net",
        "; Gate bias subcell for GaAs pHEMT RF switch.",
        "; Generated by fet_bias_preprocessor.py",
        ";",
        "; Topology:",
        ";   VCTRL --[RS]-- GATE",
        ";     |",
        ";    [CP]",
        ";     |",
        ";    GND",
        ";",
        "; Rs and Cp are ADS design variables — same single cell used for",
        "; all FET instances. Override Rs/Cp per instance in parent schematic.",
        f"; Default values (series FET, UGW={series[0].ugw_um if series else '?'}um):",
        f";   Rs = {rs_default:.1f} Ohm",
        f";   Cp = {cp_default:.2f} fF",
        f"; Shunt FET override values (UGW={shunt[0].ugw_um if shunt else '?'}um):",
        f";   Rs = {rs_shunt:.1f} Ohm",
        f";   Cp = {cp_shunt:.2f} fF",
        "; ================================================================",
        "",
        ".SUBCKT FETBIAS_SW_GATE VCTRL GATE 0",
        "",
        "; -- Ports -------------------------------------------------------",
        "PORT:VCTRL  VCTRL",
        "PORT:GATE   GATE",
        "",
        "; -- Gate bias network -------------------------------------------",
        "; Rs and Cp reference ADS design variables set on this cell.",
        "; Default values = series FET sizing; override per instance for shunt.",
        f".VAR Rs {rs_default:.1f} Ohm",
        f".VAR Cp {cp_default:.2f} fF",
        f"R:RS   VCTRL   GATE   R=Rs",
        f"C:CP   VCTRL   0      C=Cp",
        "",
        ".ENDS FETBIAS_SW_GATE",
        "",
    ]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[fet_bias_preprocessor] wrote fetbias: {out}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args():
    p = argparse.ArgumentParser(
        description="Pre-process SW elements: classify roles, calc gate bias, emit fetbias.net"
    )
    p.add_argument("netlist", help="Research netlist (.net) containing SW elements")
    p.add_argument("--pdk-config", default=str(_DEFAULT_PDK_CONFIG),
                   help="PDK core YAML (default: WIN_PP1029_core.yaml)")
    p.add_argument("--bias-rules", default=str(_DEFAULT_BIAS_RULES),
                   help="Bias rules YAML (default: switch_gate_bias.yaml)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    mappings = process_switch_netlist(
        net_path   = Path(args.netlist).resolve(),
        pdk_config = Path(args.pdk_config).resolve(),
        bias_rules = Path(args.bias_rules).resolve(),
    )
    print(f"\n[fet_bias_preprocessor] Done — {len(mappings)} SW elements mapped.")
