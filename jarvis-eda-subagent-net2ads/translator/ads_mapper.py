"""
translator/ads_mapper.py
========================
Stage 2 — ADS component mapper for the net2ads pipeline.

Maps an IR (from ir_builder.py) to an ADS build plan using the rules
in schemas/ads_mapping.yaml. The build plan is the direct input for
placement_engine.py and the ADS Python API calls.

Output: <name>_buildplan.yaml (written to disk — CONSTRAINTS.md C5)

Phase gating:
  - Phase 1: R, L, C mapped to ads_rflib equivalents
  - Phase 2: TLIN mapped (configurable via pdk_override in ads_mapping.yaml)
  - Phase 3: SW mapped to resistive/capacitive placeholder
  Components beyond active phase emit a warning but ARE included in the
  build plan so the downstream steps can handle them gracefully.

PDK override:
  Set pdk_override.enabled: true in the relevant ads_mapping.yaml entry to
  substitute a PDK component in place of the default ads_rflib component.

Usage:
    from translator.ads_mapper import map_ir_to_buildplan, write_buildplan
    plan = map_ir_to_buildplan(ir, mapping_config)
    write_buildplan(plan, output_dir=Path("examples/rc_series_shunt"))
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
import datetime

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from translator.ir_builder import IR, IRComponent


# ── Build plan data structures ─────────────────────────────────────────────────

@dataclass
class BuildInstance:
    """One ADS component instance to be placed."""
    id: str                     # ADS instance name
    ads_lib: str                # e.g., "ads_rflib"
    ads_cell: str               # e.g., "R", "C", "TLIN"
    ads_view: str               # always "symbol"
    params: dict                # {ads_param_name: value_string}
    role: str                   # series | shunt | gnd | tline | switch
    nodes: list                 # [node1, node2] from IR
    phase_required: int
    api_status: str             # CONFIRMED | UNCONFIRMED


@dataclass
class BuildPort:
    """One ADS schematic terminal (sub-cell pin)."""
    name: str                   # term name (used as ADS net + term name)
    node: str                   # IR node name
    number: int                 # port number (1-indexed)


@dataclass
class BuildPlan:
    """Full output of Stage 2 — input to placement_engine.py."""
    cell_name: str
    source_ir: str
    generation_timestamp: str
    phase_required: int
    ports: list                 # list of BuildPort
    instances: list             # list of BuildInstance
    warnings: list              # accumulated from IR + mapping stage
    design_variables: list      # list of (name, value) tuples for parameterized cells


# ── Mapping config loader ──────────────────────────────────────────────────────

def load_mapping_config(config_path: Path) -> dict:
    """
    Load ads_mapping.yaml from disk.
    Returns the parsed dict, or raises RuntimeError if YAML unavailable.
    """
    if not _YAML_AVAILABLE:
        raise RuntimeError(
            "PyYAML not available — cannot load mapping config.\n"
            "Install: pip install pyyaml"
        )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sw_map(sw_map_path: Path) -> Optional[List[dict]]:
    """
    Load spdt_switch_sw_map.yaml produced by fet_bias_preprocessor.py.
    Returns list of sw_mapping dicts, or None if path not provided / not found.
    """
    if sw_map_path is None or not Path(sw_map_path).exists():
        return None
    if not _YAML_AVAILABLE:
        return None
    with open(sw_map_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sw_mappings", [])


def _get_component_map(config: dict) -> dict:
    """
    Return a dict keyed by research_type from the component_map list.
    """
    result = {}
    for entry in config.get("component_map", []):
        rt = entry.get("research_type", "").upper()
        result[rt] = entry
    return result


# ── Parameter mapping ──────────────────────────────────────────────────────────

def _map_params(ir_params: dict, param_map_list: list) -> dict:
    """
    Translate IR parameter names to ADS parameter names using param_map_list.
    If unit_passthrough=true, value string is passed unchanged.
    Parameters not in the map are passed through with original name.
    """
    result = {}
    mapped_keys = set()
    for rule in param_map_list:
        research_key = rule.get("research_param", "")
        ads_key      = rule.get("ads_param", research_key)
        if research_key in ir_params:
            result[ads_key] = ir_params[research_key]
            mapped_keys.add(research_key)
    # Pass through any unmapped params
    for k, v in ir_params.items():
        if k not in mapped_keys:
            result[k] = v
    return result


# ── Tline physical dimension synthesis ───────────────────────────────────────

def _tline_calc_params(
    ir_comp: IRComponent,
    pdk_override: dict,
    warnings: list,
) -> dict:
    """
    Synthesize PDK microstrip parameters (W, L) from TLIN electrical specs.

    Reads Z0, ELength, Fref from ir_comp.params, calls tline_calc.microstrip_w_l_from_strings(),
    and returns a dict with keys W and L as ADS unit strings (e.g. "39.6 um", "2388.2 um").

    Args:
        ir_comp      : IRComponent with type=TLIN and params {Z0, ELength, Fref}
        pdk_override : pdk_override block from ads_mapping.yaml (provides pdk_name, subst_name)
        warnings     : mutable warnings list — errors are appended here

    Returns:
        dict of ADS parameter values, e.g. {"W": "39.6 um", "L": "2388.2 um"}
        Falls back to {"W": "50 um", "L": "1000 um"} on failure.
    """
    try:
        from design_utils.tline_calc import microstrip_w_l_from_strings
    except ImportError as exc:
        warnings.append(
            f"[WARN] TLIN '{ir_comp.id}': tline_calc not available ({exc}). "
            "Using fallback W=50um, L=1000um."
        )
        return {"W": "50 um", "L": "1000 um"}

    Z0_str  = ir_comp.params.get("Z0", "50 Ohm")
    EL_str  = ir_comp.params.get("ELength", "90 deg")
    FR_str  = ir_comp.params.get("Fref", "10 GHz")
    pdk     = pdk_override.get("pdk_name", "WIN_PP1029_DESIGN_KIT")

    try:
        W_um, L_um = microstrip_w_l_from_strings(Z0_str, EL_str, FR_str, pdk_name=pdk)
    except Exception as exc:
        warnings.append(
            f"[WARN] TLIN '{ir_comp.id}': tline_calc failed ({exc}). "
            "Using fallback W=50um, L=1000um."
        )
        return {"W": "50 um", "L": "1000 um"}

    params = {
        "W": f"{W_um:.2f} um",
        "L": f"{L_um:.2f} um",
    }
    # Add substrate param if pdk_override specifies a non-empty subst_name
    subst = pdk_override.get("subst_name", "")
    if subst:
        params["Subst"] = subst

    print(f"  [tline_calc] {ir_comp.id}: Z0={Z0_str} EL={EL_str} Fref={FR_str}  "
          f"-> W={params['W']}  L={params['L']}")
    return params


# ── Component mapping ──────────────────────────────────────────────────────────

def _map_component(
    ir_comp: IRComponent,
    comp_map: dict,
    warnings: list,
    gnd_config: dict,
) -> list:
    """
    Map one IR component to one or more BuildInstance entries.
    Returns a list because shunt components also generate a GND symbol companion.
    """
    ctype = ir_comp.type.upper()
    instances = []

    # ── Phase 3: SW element mapping ───────────────────────────────────────────
    if ctype == "SW":
        entry = comp_map.get("SW")
        if entry is None:
            warnings.append(f"[WARN] No mapping for SW element '{ir_comp.id}' — skipped")
            return []

        state = ir_comp.params.get("State", ir_comp.params.get("state", "ON")).upper()
        strategy = entry.get("mapping_strategy", "resistive")

        pdk_override = entry.get("pdk_override", {})
        if pdk_override.get("enabled", False):
            # PDK FET substitution — future; emit warning and fall through to resistive
            warnings.append(
                f"[WARN] SW '{ir_comp.id}': pdk_override is enabled but not yet implemented. "
                "Falling back to resistive model."
            )

        state_config = entry.get("state_map", {}).get(state, {})
        if not state_config:
            warnings.append(f"[WARN] SW '{ir_comp.id}': unknown State='{state}' — defaulted to ON (R=0.1 Ohm)")
            state_config = {"ads_lib": "ads_rflib", "ads_cell": "R", "ads_view": "symbol",
                            "params": {"R": "0.1 Ohm"}}

        instances.append(BuildInstance(
            id=ir_comp.id,
            ads_lib=state_config["ads_lib"],
            ads_cell=state_config["ads_cell"],
            ads_view=state_config.get("ads_view", "symbol"),
            params=dict(state_config.get("params", {})),
            role=ir_comp.role,
            nodes=ir_comp.nodes,
            phase_required=ir_comp.phase_required,
            api_status=entry.get("api_status", "CONFIRMED"),
        ))
        return instances

    # ── Phase 2: TLIN element mapping ─────────────────────────────────────────
    if ctype == "TLIN":
        entry = comp_map.get("TLIN")
        if entry is None:
            warnings.append(f"[WARN] No mapping for TLIN element '{ir_comp.id}' — skipped")
            return []

        pdk_override = entry.get("pdk_override", {})
        if pdk_override.get("enabled", False) and pdk_override.get("ads_lib"):
            ads_lib  = pdk_override["ads_lib"]
            ads_cell = pdk_override["ads_cell"]
            ads_view = pdk_override.get("ads_view", "symbol")
            api_status = "UNCONFIRMED"

            # PDK microstrip synthesis: compute W/L from Z0/ELength/Fref
            transform = pdk_override.get("param_transform", "")
            if transform == "tline_calc_microstrip":
                mapped_params = _tline_calc_params(ir_comp, pdk_override, warnings)
            else:
                param_map_list = pdk_override.get("param_map", entry.get("param_map", []))
                mapped_params  = _map_params(ir_comp.params, param_map_list)
        else:
            ads_lib  = entry["ads_lib"]
            ads_cell = entry["ads_cell"]
            ads_view = entry.get("ads_view", "symbol")
            param_map_list = entry.get("param_map", [])
            api_status = entry.get("api_status", "UNCONFIRMED")
            mapped_params = _map_params(ir_comp.params, param_map_list)

        instances.append(BuildInstance(
            id=ir_comp.id,
            ads_lib=ads_lib,
            ads_cell=ads_cell,
            ads_view=ads_view,
            params=mapped_params,
            role=ir_comp.role,
            nodes=ir_comp.nodes,
            phase_required=ir_comp.phase_required,
            api_status=api_status,
        ))
        return instances

    # ── Phase 1: R, L, C mapping ──────────────────────────────────────────────
    entry = comp_map.get(ctype)
    if entry is None:
        warnings.append(f"[WARN] No mapping defined for element type '{ctype}' ('{ir_comp.id}') — skipped")
        return []

    if entry.get("api_status", "CONFIRMED") == "UNCONFIRMED":
        warnings.append(
            f"[WARN] Component '{ir_comp.id}' uses UNCONFIRMED ADS API "
            f"({entry['ads_lib']}:{entry['ads_cell']}). "
            "See MEMORY.md Section 3."
        )

    param_map_list = entry.get("param_map", [])
    mapped_params = _map_params(ir_comp.params, param_map_list)

    instances.append(BuildInstance(
        id=ir_comp.id,
        ads_lib=entry["ads_lib"],
        ads_cell=entry["ads_cell"],
        ads_view=entry.get("ads_view", "symbol"),
        params=mapped_params,
        role=ir_comp.role,
        nodes=ir_comp.nodes,
        phase_required=ir_comp.phase_required,
        api_status=entry.get("api_status", "CONFIRMED"),
    ))

    # GND companion for shunt components
    if ir_comp.role == "shunt" and gnd_config:
        gnd_name_pattern = gnd_config.get("name_pattern", "GND_{component_id}")
        gnd_name = gnd_name_pattern.replace("{component_id}", ir_comp.id)
        instances.append(BuildInstance(
            id=gnd_name,
            ads_lib=gnd_config.get("ads_lib", "ads_rflib"),
            ads_cell=gnd_config.get("ads_cell", "GROUND"),
            ads_view=gnd_config.get("ads_view", "symbol"),
            params={},
            role="gnd",
            nodes=[],           # GND position derived from shunt component in placement engine
            phase_required=1,
            api_status="CONFIRMED",
        ))

    return instances


# ── SW → PDK FET mapping ──────────────────────────────────────────────────────

def _map_sw_to_fet(
    ir_comp: IRComponent,
    sw_entry: dict,
    warnings: list,
    next_port_number: list,  # mutable [int] counter
) -> tuple:
    """
    Map one SW element to a FET instance + fetbias_sw_gate subcell (1-port).

    fetbias_sw_gate now has internal V_DC source. Gate voltage is controlled
    via per-instance Vgate parameter (no external VCTRL port needed).

    Returns (list[BuildInstance], None).
    """
    ads_lib  = sw_entry["ads_lib"]
    ads_cell = sw_entry["ads_cell"]
    role     = sw_entry["role"]             # 'series' or 'shunt'
    nof      = sw_entry["nof"]
    ugw_um   = sw_entry["ugw_um"]
    rs_ohm   = sw_entry["rs_ohm"]
    cp_ff    = sw_entry["cp_ff"]

    instances = []

    # 1. FET instance (WIN_PP1029_CPW)
    fet_role = "fet_series" if role == "series" else "fet_shunt"
    instances.append(BuildInstance(
        id=f"Q_{ir_comp.id}",
        ads_lib=ads_lib,
        ads_cell=ads_cell,
        ads_view="symbol",
        params={
            "NOF": str(nof),
            "UGW": f"{ugw_um:.0f} um",
        },
        role=fet_role,
        nodes=ir_comp.nodes,
        phase_required=3,
        api_status="UNCONFIRMED",
    ))

    # 2. fetbias subcell instance (1-port: GATE only, V_DC internal)
    gate_net  = f"GATE_{ir_comp.id}"
    instances.append(BuildInstance(
        id=f"BIAS_{ir_comp.id}",
        ads_lib="net2ads_lib",
        ads_cell="fetbias_sw_gate",
        ads_view="symbol",
        params={
            "Rs": f"{rs_ohm:.1f} Ohm",
            "Cp": f"{cp_ff:.2f} fF",
            "Vgate": f"{sw_entry.get('vgate', 0):.1f} V",
        },
        role="fetbias",
        nodes=[gate_net],  # 1-port: GATE only (V_DC is internal)
        phase_required=3,
        api_status="CONFIRMED 2026-04-27",
    ))

    # 3. No external VCTRL port (V_DC is internal to fetbias_sw_gate)
    # Gate voltage controlled per-instance via Vgate parameter

    return instances, None


# ── Main mapper ────────────────────────────────────────────────────────────────

def map_ir_to_buildplan(ir: IR, mapping_config: dict,
                        sw_map: Optional[list] = None) -> BuildPlan:
    """
    Translate an IR to an ADS build plan using the provided mapping config.
    Returns a BuildPlan ready for placement_engine.py.
    """
    warnings = list(ir.metadata.warnings)  # carry forward IR warnings
    comp_map = _get_component_map(mapping_config)
    gnd_config = mapping_config.get("gnd_symbol", {})

    # ── sw_map index: sw_name → FetMapping dict ───────────────────────────────
    sw_map_index = {}
    if sw_map:
        for entry in sw_map:
            sw_map_index[entry["sw_name"]] = entry

    # ── Ports → BuildPort ─────────────────────────────────────────────────────
    build_ports = [
        BuildPort(name=p.name, node=p.node, number=p.number)
        for p in ir.ports
    ]

    # ── Components → BuildInstance ────────────────────────────────────────────
    all_instances = []
    vctrl_ports = []  # extra ports for VCTRL pins (one per SW)
    next_vctrl = [len(ir.ports) + 1]  # mutable counter for port numbering

    for comp in ir.components:
        if comp.type == "SW" and comp.id in sw_map_index:
            mapped, vctrl = _map_sw_to_fet(comp, sw_map_index[comp.id], warnings, next_vctrl)
            all_instances.extend(mapped)
            if vctrl:
                vctrl_ports.append(vctrl)
        else:
            mapped = _map_component(comp, comp_map, warnings, gnd_config)
            all_instances.extend(mapped)

    build_ports.extend(vctrl_ports)

    # ── Design variables ──────────────────────────────────────────────────────
    # Populated from .VAR declarations in the research netlist.
    design_variables = list(ir.design_variables)

    return BuildPlan(
        cell_name=ir.cell_name,
        source_ir=ir.source_file,
        generation_timestamp=datetime.datetime.now().isoformat(timespec="seconds"),
        phase_required=ir.phase_required,
        ports=build_ports,
        instances=all_instances,
        warnings=warnings,
        design_variables=design_variables,
    )


# ── YAML serialization ─────────────────────────────────────────────────────────

def _buildplan_to_dict(plan: BuildPlan) -> dict:
    return {
        "cell_name": plan.cell_name,
        "source_ir": plan.source_ir,
        "generation_timestamp": plan.generation_timestamp,
        "phase_required": plan.phase_required,
        "ports": [
            {"name": p.name, "node": p.node, "number": p.number}
            for p in plan.ports
        ],
        "instances": [
            {
                "id": inst.id,
                "ads_lib": inst.ads_lib,
                "ads_cell": inst.ads_cell,
                "ads_view": inst.ads_view,
                "params": inst.params,
                "role": inst.role,
                "nodes": inst.nodes,
                "phase_required": inst.phase_required,
                "api_status": inst.api_status,
            }
            for inst in plan.instances
        ],
        "design_variables": plan.design_variables,
        "warnings": plan.warnings,
    }


def write_buildplan(plan: BuildPlan, output_dir: Path) -> Path:
    """Write build plan to <output_dir>/<cell_name_lower>_buildplan.yaml."""
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not available — cannot write build plan.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{plan.cell_name.lower()}_buildplan.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(_buildplan_to_dict(plan), f, default_flow_style=False, sort_keys=False)
    return out_path


# ── CLI usage ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from translator.parser import parse_research_netlist
    from translator.ir_builder import build_ir, write_ir

    if len(sys.argv) < 3:
        print("Usage: python ads_mapper.py <research_netlist.net> <ads_mapping.yaml> [output_dir]")
        sys.exit(1)

    net_path    = Path(sys.argv[1])
    config_path = Path(sys.argv[2])
    out_dir     = Path(sys.argv[3]) if len(sys.argv) > 3 else net_path.parent

    config  = load_mapping_config(config_path)
    parsed  = parse_research_netlist(net_path)
    ir      = build_ir(parsed)
    write_ir(ir, out_dir)

    plan = map_ir_to_buildplan(ir, config)
    out_path = write_buildplan(plan, out_dir)

    print(f"Build plan: {out_path}")
    print(f"Instances:  {len(plan.instances)}")
    for inst in plan.instances:
        print(f"  {inst.role:<8} {inst.id:<25} {inst.ads_lib}:{inst.ads_cell}  params={inst.params}")
    print(f"Warnings:   {len(plan.warnings)}")
    for w in plan.warnings:
        print(f"  {w}")
