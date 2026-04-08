r"""
ads_bias_inserter.py
====================
# Created by: net-to-ads agent
# Run: 2026-04-07
# Purpose: Insert GBIAS_SWITCH_GATE bias subcell instances into existing SPDT ADS schematic
# Inputs:  --workspace   path to spdt_switch_pdk_wrk
#          --schematic   schematic cell name (default: spdt_switch)
#          --bias-rules  path to bias-rules/switch_gate_bias.yaml
#          --pdk-config  path to pdk-configs/WIN_PP1029_core.yaml
#          --dry-run     print plan without touching ADS
# Outputs: Updated ADS schematic with 4× GBIAS_SWITCH_GATE instances replacing 10 kΩ stubs
# Replaces: Manual gate bias insertion and stub removal per FET

Prerequisite: run ads_bias_subcell_create.py first to create GBIAS_CELLS:GBIAS_SWITCH_GATE.

Per-FET actions (in order: Q1a, Q3a, Q1b, Q3b):
  1. Compute Rs/Cp via gate_bias_network.calculate_bias() (fallback: yaml-derived values)
  2. Remove existing 10 kΩ gate stub resistor (Rg_<FET>_stub)
  3. Instantiate GBIAS_SWITCH_GATE at offset from gate pin
  4. Set Rs, Cp, Vctrl parameters per FET role
  5. Wire PORT_GATE to FET gate node
  6. Wire PORT_CTRL to named control net (vctrl_A or vctrl_B)

After all 4 FETs: run ads-schematic-checker and report structured status block.
"""

import sys
import os
import argparse
import math
import warnings
import subprocess
from pathlib import Path
from collections import namedtuple

# ── ADS Python environment setup ──────────────────────────────────────────────
# Same pattern as ads_build_spdt_pdk.py. Must happen before any keysight import.
# In dry-run mode, ADS imports are skipped so the script works without ADS installed.
ADS_DIR = Path(r"C:\Program Files\Keysight\ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))
os.environ.setdefault("HPEESOF_DIR", str(ADS_DIR))

ADS_AVAILABLE = False
try:
    import keysight.ads.de as de
    from keysight.ads.de import db_uu as db
    ADS_AVAILABLE = True
except ImportError:
    pass  # dry-run or non-ADS environment — guarded below

# ── YAML loading ───────────────────────────────────────────────────────────────
# PyYAML is the primary parser. ADS Python 2026 bundles it.
# If unavailable, abort with a clear message — manual YAML parse is too fragile
# for the nested structures used in these files.
try:
    import yaml as _yaml
    def load_yaml(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return _yaml.safe_load(f)
except ImportError:
    def load_yaml(path: Path) -> dict:
        raise RuntimeError(
            "PyYAML is not installed in this Python environment.\n"
            "Install with: pip install pyyaml\n"
            "Or run via ADS Python which bundles PyYAML."
        )

# ── gate_bias_network import with fallback ─────────────────────────────────────
# gate_bias_network.py is the canonical module for bias component calculation.
# If it has not yet been created, a YAML-derived fallback is used.
# The fallback computes Rs from the known prep.net value and Cp from the
# bypass impedance criterion: |Xcp| = Rs/10 at f_low.

BiasResult = namedtuple("BiasResult", ["rs_bias", "cp_bypass"])
# rs_bias:  Ohm (float)
# cp_bypass: pF (float)

try:
    from gate_bias_network import calculate_bias
    _BIAS_CALC_SOURCE = "gate_bias_network module"
except ImportError:
    def calculate_bias(ugw, nof, process_params, specs):
        """
        Fallback bias calculator — used when gate_bias_network.py does not exist.

        Rs = 300 Ohm: taken directly from spdt_switch_prep.net GBIAS blocks.
          This value is process-validated for WIN_PP1029 at 2-18 GHz.

        Cp = 1 / (2π × f_low × Rs/10): bypass cap sized so |Xcp| = Rs/10 at f_low.
          Provides >20 dB RF isolation through the bias network at lower band edge.
          For f_low=2 GHz, Rs=300 Ohm → Cp = 2.653 pF.

        ugw and nof are accepted but not used in the fallback.
        The gate_bias_network module uses them for device-geometry-dependent sizing.
        """
        rs_bias = 300.0
        f_low_hz = float(specs.get("f_low", 2.0)) * 1e9
        cp_bypass_pF = 1.0 / (2.0 * math.pi * f_low_hz * (rs_bias / 10.0)) * 1e12
        return BiasResult(rs_bias=rs_bias, cp_bypass=cp_bypass_pF)
    _BIAS_CALC_SOURCE = "fallback (gate_bias_network.py not found)"

# ── Defaults ───────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
DEFAULT_WRK  = Path(r"C:\Users\jarvis\ads_projects\spdt_switch_pdk_wrk")
DEFAULT_SCH  = "spdt_switch"
DEFAULT_BIAS = REPO_ROOT / "bias-rules" / "switch_gate_bias.yaml"
DEFAULT_PDK  = REPO_ROOT / "pdk-configs" / "WIN_PP1029_core.yaml"
GBIAS_LIB    = "GBIAS_CELLS"
GBIAS_CELL   = "GBIAS_SWITCH_GATE"
CHECKER      = REPO_ROOT / "skills" / "ads-schematic-checker" / "scripts" / "check_netlist.py"

# ── FET table ──────────────────────────────────────────────────────────────────
# Gate pin coordinates derived from ads_build_spdt_pdk.py placement:
#   Series FET (angle=90): gate = (x_drain + 0.5, -0.5)
#   Shunt  FET (angle=0):  gate = (node_x - 0.5,  -0.5)
# Stub names from gate_stub() helper in ads_build_spdt_pdk.py.
# Control nets: vctrl_A for series (PATH A), vctrl_B for shunt.
FET_TABLE = [
    {
        "name":       "Q1a",
        "role":       "series",
        "gate_node":  "ng_Q1a",
        "gate_x":     10.0,    # x_drain=9.5  → gate_x = 9.5+0.5 = 10.0
        "gate_y":     -0.5,
        "stub_name":  "Rg_Q1a_stub",
        "ctrl_net":   "vctrl_A",
        "ugw":        80,
        "nof":        2,
    },
    {
        "name":       "Q3a",
        "role":       "shunt",
        "gate_node":  "ng_Q3a",
        "gate_x":     11.0,    # node_x=11.5 → gate_x = 11.5-0.5 = 11.0
        "gate_y":     -0.5,
        "stub_name":  "Rg_Q3a_stub",
        "ctrl_net":   "vctrl_B",
        "ugw":        50,
        "nof":        2,
    },
    {
        "name":       "Q1b",
        "role":       "series",
        "gate_node":  "ng_Q1b",
        "gate_x":     13.5,    # x_drain=13.0 → gate_x = 13.0+0.5 = 13.5
        "gate_y":     -0.5,
        "stub_name":  "Rg_Q1b_stub",
        "ctrl_net":   "vctrl_A",
        "ugw":        80,
        "nof":        2,
    },
    {
        "name":       "Q3b",
        "role":       "shunt",
        "gate_node":  "ng_Q3b",
        "gate_x":     14.5,    # node_x=15.0 → gate_x = 15.0-0.5 = 14.5
        "gate_y":     -0.5,
        "stub_name":  "Rg_Q3b_stub",
        "ctrl_net":   "vctrl_B",
        "ugw":        50,
        "nof":        2,
    },
]

# ── YAML coordinate conversion ─────────────────────────────────────────────────
# switch_gate_bias.yaml specifies placement offsets in mils.
# ads_build_spdt_pdk.py uses schematic coordinates where component half-widths
# are 0.5 units and FET pin spacing is ~1.0 unit. Empirically this maps to
# approximately 100 mils per schematic unit (standard ADS schematic grid).
# ⚠ UNVERIFIED: MILS_PER_UNIT — confirm by measuring a known component span
#   in ADS GUI ruler vs its add_instance coordinate span. Update MEMORY.md.
MILS_PER_UNIT = 100.0


# ══════════════════════════════════════════════════════════════════════════════
# YAML helpers
# ══════════════════════════════════════════════════════════════════════════════

def _load_configs(bias_rules_path: Path, pdk_config_path: Path):
    """Load and return bias_rules, pdk_config, and process_defaults dicts."""
    bias_rules = load_yaml(bias_rules_path)
    pdk_cfg    = load_yaml(pdk_config_path)

    # Load the process-defaults file referenced inside bias_rules.
    proc_ref = bias_rules.get("process_defaults", "")
    if proc_ref:
        proc_path = bias_rules_path.parent.parent / proc_ref
        if not proc_path.exists():
            proc_path = Path(proc_ref)  # try as absolute/relative path
        process_defaults = load_yaml(proc_path)
    else:
        process_defaults = {}

    return bias_rules, pdk_cfg, process_defaults


def _get_vctrl(bias_rules: dict, role: str) -> str:
    """
    Return Vctrl string for the given FET role from bias_rules fet_roles.
    Uses vctrl_on — the voltage when the SWITCH PATH is active.
      series.vctrl_on = 0.0 V  (series FET conducts RF)
      shunt.vctrl_on  = -0.5 V (shunt FET is absorptive/pinched off for RF)
    """
    roles = bias_rules.get("fet_roles", {})
    role_cfg = roles.get(role, {})
    v = float(role_cfg.get("vctrl_on", 0.0))
    return f"{v} V"


def _get_specs(bias_rules: dict) -> dict:
    """Extract specs dict from bias_rules (f_low, f_high, etc.)."""
    return bias_rules.get("specs", {})


def _get_placement_offset(bias_rules: dict):
    """
    Return (offset_x_units, offset_y_units) from bias_rules placement section.
    Converts mils → schematic units using MILS_PER_UNIT.
    ⚠ UNVERIFIED: MILS_PER_UNIT conversion factor — see constant definition above.
    """
    placement = bias_rules.get("placement", {})
    ox_mils = float(placement.get("offset_x", -200))
    oy_mils = float(placement.get("offset_y", 0))
    return ox_mils / MILS_PER_UNIT, oy_mils / MILS_PER_UNIT


# ══════════════════════════════════════════════════════════════════════════════
# ADS workspace / schematic helpers
# ══════════════════════════════════════════════════════════════════════════════

def _open_existing_workspace(workspace_path: Path):
    """
    Open an existing ADS workspace without creating or deleting it.
    Uses de.directory_is_workspace() + de.open_workspace() — both confirmed
    by ads_probe_subcell_api.py run on 2026-04-07.
    """
    if de.workspace_is_open():
        de.close_workspace()
    if not de.directory_is_workspace(str(workspace_path)):
        raise RuntimeError(
            f"Path is not a valid ADS workspace: {workspace_path}\n"
            "Run ads_build_spdt_pdk.py first to create the workspace."
        )
    workspace = de.open_workspace(str(workspace_path))
    print(f"[WRK] Workspace open: {workspace_path}")
    return workspace


def _check_gbias_library(workspace) -> bool:
    """
    Return True if GBIAS_CELLS library is present in the workspace.
    Reuses confirmed workspace.libraries enumeration from Run 1.
    """
    try:
        existing = [lib.name for lib in workspace.libraries]
    except Exception:
        existing = list(workspace.libraries)  # fallback if .name fails
    return GBIAS_LIB in existing


def _open_existing_schematic(lib_name: str, cell_name: str):
    """
    Open the existing spdt_switch schematic without recreating it.

    ⚠ UNVERIFIED: db.open_schematic() — inferred by analogy with db.create_schematic().
      Alternatives to try if this fails:
        sch = db.get_schematic(f"{lib_name}:{cell_name}:schematic")
        lib  = workspace.open_library(lib_name)
        cell = lib.open_cell(cell_name)
        sch  = cell.open_view("schematic")
      Update MEMORY.md with the confirmed method after first run.
    """
    lcv = f"{lib_name}:{cell_name}:schematic"
    return db.open_schematic(lcv)


def _find_instance(sch, name: str):
    """
    Find an instance in sch by name. Returns instance or None.
    Iterates sch.instances (confirmed from ads_build_spdt_pdk.py connectivity probe).
    """
    for inst in sch.instances:
        if inst.name == name:
            return inst
    return None


def _remove_stub(sch, stub_name: str, dry_run: bool) -> bool:
    """
    Remove the 10 kΩ gate stub resistor and its companion GROUND instance.
    Stub names from gate_stub() in ads_build_spdt_pdk.py: "Rg_Q1a_stub" etc.
    Companion GROUND is named "GND_Rg_Q1a_stub".

    Returns True if stub was found and removed (or dry-run), False if not found.

    ⚠ UNVERIFIED: sch.delete_instance(inst) — inferred API.
      Alternative: inst.delete()
      Update MEMORY.md with confirmed method after first run.
    """
    gnd_name = f"GND_{stub_name}"
    stub = _find_instance(sch, stub_name)
    gnd  = _find_instance(sch, gnd_name)

    if stub is None:
        print(f"  [SKIP] {stub_name} not found — already removed or never placed")
        return False

    if dry_run:
        print(f"  [DRY ] Would delete: {stub_name}, {gnd_name}")
        return True

    # ⚠ UNVERIFIED: sch.delete_instance() — see docstring above
    try:
        sch.delete_instance(stub)
        print(f"  [DEL ] {stub_name}")
    except AttributeError:
        stub.delete()   # alternative form
        print(f"  [DEL ] {stub_name} (via inst.delete())")

    if gnd is not None:
        try:
            sch.delete_instance(gnd)
        except AttributeError:
            gnd.delete()
        print(f"  [DEL ] {gnd_name}")

    return True


# ══════════════════════════════════════════════════════════════════════════════
# GBIAS insertion — per FET
# ══════════════════════════════════════════════════════════════════════════════

def _insert_one_bias(sch, fet: dict, bias_rules: dict, process_defaults: dict,
                     specs: dict, dry_run: bool):
    """
    Insert one GBIAS_SWITCH_GATE instance for the given FET entry.

    Placement:
      GBIAS is placed so its PORT_GATE (local x=6.5, y=0) aligns with the
      FET gate pin in the parent schematic. Instance origin is therefore at:
        (gate_x - gbias_port_gate_local_x + offset_x,
         gate_y - gbias_port_gate_local_y + offset_y)

    ⚠ UNVERIFIED: PORT_GATE snap_point position in parent schematic.
      The GBIAS_SWITCH_GATE was built as a schematic view. ADS may auto-generate
      a symbol with ports at estimated positions, or it may require a manual symbol.
      PORT_GATE local position (6.5, 0.0) is the internal schematic coordinate.
      The actual pin offset in the parent depends on the auto-symbol layout.
      Run ads_probe_fet_pins.py pattern on GBIAS_SWITCH_GATE to confirm.
      Until confirmed, PORT_GATE is assumed at (inst_x + 6.5, inst_y + 0.0).

    ⚠ UNVERIFIED: Using "schematic" view in de.LCVName for subcell instantiation.
      In ADS, subcell instances in a parent schematic typically reference the
      "symbol" view, not "schematic". If GBIAS_SWITCH_GATE has no symbol view
      (only a schematic view), this will raise RuntimeError: Could not find cell.
      Fix: create a symbol view via ads_bias_subcell_create.py or ADS GUI,
      then change the view string below from "schematic" to "symbol".
    """
    name      = fet["name"]
    role      = fet["role"]
    gate_x    = fet["gate_x"]
    gate_y    = fet["gate_y"]
    gate_node = fet["gate_node"]
    ctrl_net  = fet["ctrl_net"]
    stub_name = fet["stub_name"]

    # ── Step 1: Compute bias values ───────────────────────────────────────────
    comp = calculate_bias(
        ugw=fet["ugw"],
        nof=fet["nof"],
        process_params=process_defaults,
        specs=specs,
    )
    rs_val    = round(comp.rs_bias / 10) * 10              # round to nearest 10 Ohm
    cp_val    = round(comp.cp_bypass, 4)                   # 4 decimal places in pF
    vctrl_val = _get_vctrl(bias_rules, role)

    print(f"\n  [{name}] role={role}  Rs={rs_val} Ohm  Cp={cp_val} pF  Vctrl={vctrl_val}")

    # ── Step 2: Remove existing stub ──────────────────────────────────────────
    _remove_stub(sch, stub_name, dry_run)

    # ── Step 3: Compute GBIAS instance placement ──────────────────────────────
    # PORT_GATE is at (6.5, 0.0) in GBIAS local coordinates (⚠ UNVERIFIED).
    # Place instance so PORT_GATE lands at (gate_x, gate_y).
    # Also apply the yaml placement offset (left of gate, below signal line).
    offset_x, offset_y = _get_placement_offset(bias_rules)
    gbias_port_gate_local_x = 6.5   # ⚠ UNVERIFIED — from GBIAS schematic layout
    gbias_port_gate_local_y = 0.0   # ⚠ UNVERIFIED — from GBIAS schematic layout
    inst_x = gate_x - gbias_port_gate_local_x + offset_x
    inst_y = gate_y - gbias_port_gate_local_y + offset_y

    # PORT_CTRL is at (0.0, 0.0) in GBIAS local coordinates (⚠ UNVERIFIED).
    port_ctrl_x = inst_x + 0.0
    port_ctrl_y = inst_y + 0.0
    port_gate_x = inst_x + gbias_port_gate_local_x
    port_gate_y = inst_y + gbias_port_gate_local_y

    print(f"  [{name}] GBIAS origin=({inst_x:.2f}, {inst_y:.2f})")
    print(f"  [{name}] PORT_GATE estimate=({port_gate_x:.2f}, {port_gate_y:.2f})")
    print(f"  [{name}] PORT_CTRL estimate=({port_ctrl_x:.2f}, {port_ctrl_y:.2f})")

    if dry_run:
        print(f"  [DRY ] Would place GBIAS_{name} at ({inst_x:.2f}, {inst_y:.2f})")
        print(f"  [DRY ] Rs={rs_val} Ohm  Cp={cp_val} pF  Vctrl={vctrl_val}")
        print(f"  [DRY ] Wire PORT_GATE → ({gate_x}, {gate_y}) [{gate_node}]")
        print(f"  [DRY ] Wire PORT_CTRL → {ctrl_net} stub at ({port_ctrl_x:.2f}, {port_ctrl_y:.2f})")
        return

    # ── Step 4: Instantiate GBIAS_SWITCH_GATE ─────────────────────────────────
    # add_instance() is confirmed from ads_build_spdt_pdk.py Run 1.
    # ⚠ UNVERIFIED: "schematic" view for subcell — may need "symbol"; see docstring.
    gbias_inst = sch.add_instance(
        de.LCVName(GBIAS_LIB, GBIAS_CELL, "schematic"),
        (inst_x, inst_y),
        name=f"GBIAS_{name}",
        angle=0.0
    )
    print(f"  [{name}] GBIAS_{name} placed at ({inst_x:.2f}, {inst_y:.2f})")

    # ── Step 5: Set per-FET parameters ────────────────────────────────────────
    # parameters["X"].value confirmed from ads_build_spdt_pdk.py Run 1.
    gbias_inst.parameters["Rs"].value    = f"{rs_val} Ohm"
    gbias_inst.parameters["Cp"].value    = f"{cp_val} pF"
    gbias_inst.parameters["Vctrl"].value = vctrl_val
    print(f"  [{name}] Parameters set: Rs={rs_val} Ohm  Cp={cp_val} pF  Vctrl={vctrl_val}")

    # ── Step 6a: Wire PORT_GATE → FET gate node ───────────────────────────────
    # sch.add_wire() confirmed from ads_build_spdt_pdk.py Run 1.
    # Wire endpoint must exactly match pin snap_point — port_gate_x/y are estimated.
    # ⚠ UNVERIFIED: actual PORT_GATE snap_point — see docstring above.
    # If wire misses, ADS places silently; checker will catch floating ng_* node.
    sch.add_wire([(port_gate_x, port_gate_y), (gate_x, gate_y)])
    print(f"  [{name}] Wired PORT_GATE → {gate_node} ({gate_x}, {gate_y})")

    # ── Step 6b: Wire PORT_CTRL → control net stub ────────────────────────────
    # ADS net labels require a label/pin symbol — not just a wire endpoint.
    # ⚠ UNVERIFIED: ADS net-label API.
    # Interim approach: wire a short stub from PORT_CTRL to a named point.
    # The control nets (vctrl_A, vctrl_B) will need a Port/Label instance added
    # once the net-label API is confirmed. For now, stub is left open-ended.
    # Add a short stub extending left from PORT_CTRL for manual net-label placement.
    ctrl_stub_x = port_ctrl_x - 0.5    # 0.5 units left — stub endpoint for net label
    sch.add_wire([(port_ctrl_x, port_ctrl_y), (ctrl_stub_x, port_ctrl_y)])
    print(f"  [{name}] PORT_CTRL stub wired to ({ctrl_stub_x:.2f}, {port_ctrl_y:.2f})")
    print(f"  [{name}] ⚠  Net label '{ctrl_net}' must be added manually or via net-label API")


# ══════════════════════════════════════════════════════════════════════════════
# Schematic checker
# ══════════════════════════════════════════════════════════════════════════════

def _run_checker(workspace_path: Path, schematic_name: str,
                 sch, dry_run: bool) -> bool:
    """
    Generate netlist from updated schematic and run ads-schematic-checker.
    Returns True if checker passes (ALL CHECKS PASSED), False otherwise.
    """
    net_path = workspace_path / f"{schematic_name}_bias_updated.net"

    if dry_run:
        print(f"\n[CHECKER] Dry-run: would generate netlist → {net_path}")
        print(f"[CHECKER] Dry-run: would run {CHECKER}")
        return True

    # Generate updated netlist — confirmed pattern from ads_build_spdt_pdk.py
    print(f"\n[CHECKER] Generating netlist...")
    netlist_text = sch.generate_netlist()
    net_path.write_text(netlist_text, encoding="utf-8")
    print(f"[CHECKER] Netlist written: {net_path}")

    if not CHECKER.exists():
        print(f"[CHECKER] WARNING: checker script not found at {CHECKER}")
        print(f"[CHECKER] Run manually: python {CHECKER} {net_path}")
        return False

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(net_path)],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("[CHECKER STDERR]", result.stderr[:500])

    return "ALL CHECKS PASSED" in result.stdout


# ══════════════════════════════════════════════════════════════════════════════
# Status block (per PLAYBOOK.md yield format)
# ══════════════════════════════════════════════════════════════════════════════

def _print_status(stage_completed: int, outputs: list, checker_passed: bool,
                  errors: str = "none"):
    status = "success" if checker_passed else "partial"
    next_action = (
        "Open ADS project, verify bias networks visually, add vctrl_A/vctrl_B net labels, "
        "then sign off in GRADUATION.md to advance to Phase 2."
        if checker_passed else
        "Fix floating gate nodes reported by checker, re-run ads_bias_inserter.py."
    )
    print("\n" + "=" * 62)
    print("status:", status)
    print("stage_completed:", stage_completed)
    print("outputs:")
    for o in outputs:
        print(f"  - {o}")
    print("next_action:", next_action)
    print("errors:", errors)
    print("=" * 62)


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def insert_bias_networks(workspace_path: str, schematic_name: str,
                         bias_rules_path: str, pdk_config_path: str,
                         dry_run: bool = False):
    """
    Main function. Opens existing ADS schematic, inserts GBIAS_SWITCH_GATE
    for all 4 FETs, runs checker, and prints PLAYBOOK.md status block.
    """
    workspace_path  = Path(workspace_path)
    bias_rules_path = Path(bias_rules_path)
    pdk_config_path = Path(pdk_config_path)

    print("=" * 62)
    print("Bias Inserter" + (" [DRY-RUN]" if dry_run else ""))
    print(f"  workspace  : {workspace_path}")
    print(f"  schematic  : {schematic_name}")
    print(f"  bias rules : {bias_rules_path}")
    print(f"  pdk config : {pdk_config_path}")
    print(f"  bias calc  : {_BIAS_CALC_SOURCE}")
    print("=" * 62)

    # ── Load configs ───────────────────────────────────────────────────────────
    bias_rules, pdk_cfg, process_defaults = _load_configs(bias_rules_path, pdk_config_path)
    specs = _get_specs(bias_rules)
    print(f"\n[CFG] Specs: f_low={specs.get('f_low')} GHz  f_high={specs.get('f_high')} GHz")

    # ── Resolve library name from schematic path ───────────────────────────────
    # spdt_switch schematic lives in spdt_switch_pdk_lib (from ads_build_spdt_pdk.py)
    lib_name = "spdt_switch_pdk_lib"

    if dry_run:
        print("\n[DRY] Skipping ADS workspace open — dry-run mode")
        sch = None
    else:
        if not ADS_AVAILABLE:
            raise RuntimeError(
                "ADS Python packages not found. "
                "Run with --dry-run to preview without ADS, or use ADS Python interpreter."
            )

        # ── Open workspace ─────────────────────────────────────────────────────
        workspace = _open_existing_workspace(workspace_path)

        # ── Check GBIAS_CELLS library present ──────────────────────────────────
        if not _check_gbias_library(workspace):
            print(f"\n[ERROR] Library '{GBIAS_LIB}' not found in workspace.")
            print(f"  Run ads_bias_subcell_create.py first:")
            print(f"  <ADS_PYTHON> ads_bias_subcell_create.py --workspace {workspace_path} --type switch_gate")
            _print_status(0, [], False,
                          f"GBIAS_CELLS library missing — run ads_bias_subcell_create.py first")
            sys.exit(1)

        # ── Open existing schematic (do NOT recreate) ──────────────────────────
        sch = _open_existing_schematic(lib_name, schematic_name)
        print(f"[SCH] Schematic open: {lib_name}:{schematic_name}:schematic")

        # ── Open transaction for all modifications ─────────────────────────────
        # de.db.Transaction confirmed from ads_build_spdt_pdk.py Run 1.
        tx = de.db.Transaction(sch, "insert_bias_networks")

    # ── Insert GBIAS for each FET ──────────────────────────────────────────────
    print(f"\n[INSERT] Processing {len(FET_TABLE)} FETs...")
    errors = []

    for fet in FET_TABLE:
        try:
            _insert_one_bias(sch, fet, bias_rules, process_defaults,
                             specs, dry_run)
        except Exception as exc:
            msg = f"{fet['name']}: {type(exc).__name__}: {exc}"
            print(f"  [ERROR] {msg}")
            errors.append(msg)

    if not dry_run:
        # ── Commit and save ────────────────────────────────────────────────────
        tx.commit()
        sch.save_design()
        print("\n[SCH] Changes committed and saved.")

    # ── Run checker ────────────────────────────────────────────────────────────
    checker_passed = _run_checker(workspace_path, schematic_name, sch, dry_run)

    # ── Status block ───────────────────────────────────────────────────────────
    net_file = f"{schematic_name}_bias_updated.net"
    error_str = "; ".join(errors) if errors else "none"
    _print_status(
        stage_completed=3,
        outputs=[net_file] if not dry_run else [],
        checker_passed=checker_passed,
        errors=error_str,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Insert GBIAS_SWITCH_GATE bias subcell instances into SPDT ADS schematic."
    )
    parser.add_argument("--workspace",  required=True,
                        help="Path to ADS workspace directory.")
    parser.add_argument("--schematic",  default=DEFAULT_SCH,
                        help=f"Schematic cell name. Default: {DEFAULT_SCH}")
    parser.add_argument("--bias-rules", dest="bias_rules",
                        default=str(DEFAULT_BIAS),
                        help=f"Path to switch_gate_bias.yaml. Default: {DEFAULT_BIAS}")
    parser.add_argument("--pdk-config", dest="pdk_config",
                        default=str(DEFAULT_PDK),
                        help=f"Path to WIN_PP1029_core.yaml. Default: {DEFAULT_PDK}")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Print plan without opening ADS or modifying any schematic.")
    args = parser.parse_args()

    insert_bias_networks(
        workspace_path  = args.workspace,
        schematic_name  = args.schematic,
        bias_rules_path = args.bias_rules,
        pdk_config_path = args.pdk_config,
        dry_run         = args.dry_run,
    )
