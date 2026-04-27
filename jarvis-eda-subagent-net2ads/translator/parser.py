"""
translator/parser.py
====================
Stage 1a — Research netlist parser for the net2ads pipeline.

Accepts ONLY the research netlist dialect defined in schemas/research_netlist.yaml.
Does NOT accept generic SPICE, ADS hpeesofsim format, or Spectre format.
See CONSTRAINTS.md C2.

Supported syntax:
    ; comment
    .SUBCKT <name> <port1> <port2> ... 0
    PORT:<name>  <node>
    <Type>:<InstanceName>  <node1>  <node2>  <param>=<value> ...
    .VAR <name> <value> [<unit>]
    .ENDS <name>

Unsupported constructs (logged as warnings, not errors):
    .AC .DC .TRAN .SP .HB SweepPlan: OutputPlan: Term: .model .include

Phase-gated elements:
    Phase 1: R, L, C
    Phase 2: TLIN
    Phase 3: SW
    Elements outside active phase emit a warning and are included in parse output
    with a flag so ir_builder can decide how to handle them.

Usage:
    from translator.parser import parse_research_netlist
    result = parse_research_netlist(Path("examples/rc_series_shunt/rc_series_shunt_research.net"))
    # result is a ParseResult namedtuple
"""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ── Phase gate ─────────────────────────────────────────────────────────────────
PHASE_BY_TYPE = {
    "R": 1, "L": 1, "C": 1,
    "TLIN": 2,
    "SW": 3, "V": 3,  # V = voltage source (Phase 3 — gate control, biasing)
}

# Constructs that are valid in the research dialect but are simulation-only — skip them.
SIMULATION_KEYWORDS = {
    ".ac", ".dc", ".tran", ".sp", ".hb",
    "s_param:", "sweepplan:", "outputplan:", "term:",
    ".model", ".include", ".lib", ".options", "options",
}


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ParsedComponent:
    """One component instance from the research netlist."""
    id: str                         # instance name (e.g., "R1_SER")
    type: str                       # element type (e.g., "R", "C", "TLIN", "SW")
    nodes: list                     # [node1, node2, ...] — strings
    params: dict                    # {param_name: value_string}
    phase_required: int             # phase needed to map this element
    source_line: int                # 1-indexed line number in source file
    raw: str                        # original line text (for debugging)


@dataclass
class ParsedPort:
    """One PORT: declaration from the research netlist."""
    name: str                       # port name and ADS term name
    node: str                       # internal node this port connects to
    source_line: int


@dataclass
class ParseResult:
    """Full output of the parser — handed to ir_builder."""
    cell_name: str
    subckt_ports: list              # port names from .SUBCKT header (ordered)
    ports: list                     # list of ParsedPort
    components: list                # list of ParsedComponent
    warnings: list                  # list of warning strings
    source_file: str
    design_variables: list          # list of (name, value_string) from .VAR declarations


# ── Unit normalization ─────────────────────────────────────────────────────────

def _normalize_value(value_str: str) -> str:
    """
    Normalize a parameter value string.
    Strips leading/trailing whitespace; preserves unit suffix.
    Does NOT convert to SI — the ADS API accepts unit strings directly.
    Example: "  50 Ohm  " -> "50 Ohm"
    """
    return value_str.strip()


# ── Line parsing helpers ───────────────────────────────────────────────────────

def _parse_params(tokens: list) -> dict:
    """
    Extract key=value parameter pairs from a list of token strings.
    Tokens that are not key=value pairs are ignored (they are nodes).
    Example: ["P1", "N_OUT", "R=50 Ohm"] -> {"R": "50 Ohm"}
    Note: value may contain spaces (e.g., "50 Ohm") so we rejoin after first '='.
    """
    params = {}
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
            params[key.strip()] = _normalize_value(val)
    return params


def _parse_nodes(tokens: list) -> list:
    """
    Extract node names from tokens — everything before the first key=value token.
    Returns list of node strings.
    """
    nodes = []
    for tok in tokens:
        if "=" in tok:
            break
        nodes.append(tok)
    return nodes


def _parse_component_line(line: str, lineno: int, warnings: list) -> Optional[ParsedComponent]:
    """
    Parse a component line of the form:
        <Type>:<InstanceName>  <node1>  <node2>  [<param>=<value> ...]

    Returns ParsedComponent or None if the line cannot be parsed as a component.
    """
    # Must start with Type:Name pattern
    m = re.match(r'^([A-Za-z]+):([A-Za-z0-9_]+)\s+(.*)', line.strip())
    if not m:
        return None

    elem_type = m.group(1).upper()
    instance_name = m.group(2)
    rest = m.group(3).strip()

    # Split remainder on whitespace for node/param extraction
    # Handle multi-word values like "50 Ohm" by treating them as key=value where
    # the value may have trailing unit tokens. The format is strict: nodes come
    # first (no "="), then params (contain "=").
    # But "50 Ohm" is a problem if split naively — the YAML examples show "R=50 Ohm"
    # where the value is everything after the "=". We split on regex to handle this.
    tokens = re.split(r'\s+', rest)
    nodes = _parse_nodes(tokens)
    params = {}

    # Re-extract params by scanning for "key=value" patterns in the original rest string
    # This handles multi-word values (e.g., "Z0=50 Ohm") correctly by consuming
    # everything from key= to the next key= or end of string.
    for m2 in re.finditer(r'([A-Za-z_]\w*)\s*=\s*([^=]+?)(?=\s+[A-Za-z_]\w*\s*=|$)', rest):
        params[m2.group(1).strip()] = _normalize_value(m2.group(2))

    phase_req = PHASE_BY_TYPE.get(elem_type, 99)
    if phase_req == 99:
        warnings.append(f"[WARN] Line {lineno}: Unknown element type '{elem_type}' — skipped")
        return None

    return ParsedComponent(
        id=instance_name,
        type=elem_type,
        nodes=nodes,
        params=params,
        phase_required=phase_req,
        source_line=lineno,
        raw=line,
    )


def _is_simulation_keyword(line_lower: str) -> bool:
    """Return True if this line starts with a simulation-only keyword."""
    for kw in SIMULATION_KEYWORDS:
        if line_lower.startswith(kw):
            return True
    return False


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_research_netlist(path: Path) -> ParseResult:
    """
    Parse a research netlist file and return a ParseResult.

    Raises:
        ValueError  — if no .SUBCKT declaration is found
        FileNotFoundError — if path does not exist
    """
    if not path.exists():
        raise FileNotFoundError(f"Netlist not found: {path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    cell_name = ""
    subckt_ports = []
    ports = []
    components = []
    warnings = []
    design_variables = []
    in_subckt = False

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith(";") or line.startswith("*"):
            continue

        line_lower = line.lower()

        # .SUBCKT header
        if line_lower.startswith(".subckt"):
            tokens = line.split()
            if len(tokens) < 2:
                warnings.append(f"[WARN] Line {lineno}: Malformed .SUBCKT — skipped")
                continue
            cell_name = tokens[1]
            # ports are everything between .SUBCKT name and trailing "0"
            raw_ports = tokens[2:]
            subckt_ports = [p for p in raw_ports if p != "0"]
            in_subckt = True
            continue

        # .ENDS
        if line_lower.startswith(".ends"):
            in_subckt = False
            continue

        if not in_subckt:
            if not _is_simulation_keyword(line_lower):
                warnings.append(
                    f"[WARN] Line {lineno}: Content outside .SUBCKT block — skipped: {line[:60]}"
                )
            continue

        # Simulation keywords — skip with warning (CONSTRAINTS.md C1)
        if _is_simulation_keyword(line_lower):
            warnings.append(
                f"[WARN] Line {lineno}: Simulation construct skipped (out of scope): {line[:60]}"
            )
            continue

        # .VAR declaration — design variable with default value
        # Syntax: .VAR <name> <value> [<unit>]
        # Example: .VAR Rs 1000.0 Ohm  or  .VAR Cp 2272.73 fF
        if line_lower.startswith(".var"):
            tokens = line.split(None, 3)  # .VAR name value [unit]
            if len(tokens) >= 3:
                var_name  = tokens[1]
                var_value = " ".join(tokens[2:]).strip()
                design_variables.append((var_name, var_value))
            else:
                warnings.append(f"[WARN] Line {lineno}: Malformed .VAR declaration — skipped: {line}")
            continue

        # PORT: declaration
        if line_lower.startswith("port:"):
            m = re.match(r'^PORT:(\S+)\s+(\S+)', line, re.IGNORECASE)
            if m:
                ports.append(ParsedPort(
                    name=m.group(1),
                    node=m.group(2),
                    source_line=lineno,
                ))
            else:
                warnings.append(f"[WARN] Line {lineno}: Malformed PORT declaration — skipped: {line}")
            continue

        # Component line: Type:Name node1 node2 params
        if ":" in line.split()[0] if line.split() else False:
            comp = _parse_component_line(line, lineno, warnings)
            if comp is not None:
                components.append(comp)
            continue

        # Anything else that isn't a component or known keyword
        warnings.append(f"[WARN] Line {lineno}: Unrecognized line — skipped: {line[:60]}")

    if not cell_name:
        raise ValueError(
            f"No .SUBCKT declaration found in {path.name}. "
            "Research netlists must use .SUBCKT / .ENDS wrapper."
        )

    return ParseResult(
        cell_name=cell_name,
        subckt_ports=subckt_ports,
        ports=ports,
        components=components,
        warnings=warnings,
        source_file=str(path),
        design_variables=design_variables,
    )


# ── CLI usage ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python parser.py <research_netlist.net>")
        sys.exit(1)

    result = parse_research_netlist(Path(sys.argv[1]))

    print(f"Cell:       {result.cell_name}")
    print(f"Ports:      {result.subckt_ports}")
    print(f"Components: {len(result.components)}")
    for c in result.components:
        print(f"  {c.type:<6} {c.id:<20} nodes={c.nodes}  params={c.params}  phase={c.phase_required}")
    print(f"Warnings:   {len(result.warnings)}")
    for w in result.warnings:
        print(f"  {w}")
