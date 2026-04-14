# net2ads Constraints

Hard constraints that govern every decision this agent makes.
Violating these constraints — even partially — is not permitted without explicit human sign-off.

---

## C1 — No Simulation Setup

**Rule:** Do not place, generate, or include any simulation controller in output schematics or netlists.

**Prohibited constructs:**

| Netlist keyword | ADS component | Reason blocked |
|---|---|---|
| `.AC` | AC controller | simulation bench only |
| `.DC` | DC controller | simulation bench only |
| `.TRAN` | Transient controller | simulation bench only |
| `.SP` / `S_Param:` | S-parameter controller | simulation bench only |
| `.HB` | Harmonic balance controller | simulation bench only |
| `SweepPlan:` | Sweep definition | simulation bench only |
| `OutputPlan:` | Output definition | simulation bench only |
| `Term:` (ADS simulation port) | Simulation Term symbol | bench coupling only |

**Reason:** Output cells must be reusable subcircuits. Simulation definitions embedded in a cell
prevent it from being instantiated in a different simulation context (e.g., the same LPF cell
used in S-param and large-signal benches). Simulation setup belongs in a separate simulation
template cell — out of scope for this agent.

**Exception:** `.port` declarations in research netlists are parsed and translated to
`design.add_term()` calls (sub-cell pins) — not to `Term:` simulation symbols.

---

## C1a — Use Generic Ports, Not 50 Ω Terminations

**Rule:** When creating an ADS schematic cell, ports must be implemented as generic
sub-cell pins (`design.add_term()`). Do NOT place 50 Ω `Term:` termination symbols
or any impedance-specific port component in the cell schematic.

**Correct implementation:**
```python
net  = design.find_or_add_net("P1")
term = design.add_term(net, "P1", TermType.INPUT_OUTPUT)   # ✅ generic pin
```

**Prohibited:**
```python
# ❌ DO NOT place Term: simulation symbol with Z=50 Ohm in the cell
design.add_instance(de.LCVName("ads_simulation", "Term", "symbol"), ...)
```

**Reason:** A cell with hardcoded 50 Ω terminations is no longer a reusable subcircuit —
it becomes a fixed-impedance simulation bench. The port impedance (50 Ω or otherwise)
belongs in the parent simulation template, not in the circuit cell itself.
The cell's ports must remain generic so they can be driven by any impedance in
any simulation context (S-param, large-signal, time-domain, etc.).

---

## C2 — Restricted Netlist Dialect Only

**Rule:** The parser (`translator/parser.py`) accepts ONLY the research netlist dialect
defined in `schemas/research_netlist.yaml`. It must not attempt to parse generic SPICE,
ADS hpeesofsim format, or Spectre format.

**Dialect summary:**
- Comments: `;` (semicolon)
- Subcircuit wrapper: `.SUBCKT <name> <ports> 0` / `.ENDS <name>`
- Component syntax: `<Type>:<InstanceName>  <node1>  <node2>  <param>=<value> ...`
- Port declarations: `PORT:<name>  <node>`
- Supported element types: `R`, `L`, `C`, `TLIN`, `SW` (phase-gated)
- Ground node: `0`
- Unit suffixes: `Ohm`, `nH`, `pH`, `pF`, `fF`, `GHz`, `MHz`, `deg`
- No `.AC`, `.DC`, `.TRAN`, `.SP`, `.HB`, `SweepPlan:`, `OutputPlan:`, `Term:`

**When an unsupported construct is encountered:**
- Log a warning to stdout: `[WARN] Unsupported construct skipped: <line>`
- Record in the IR `metadata.warnings` list
- Continue parsing; do not abort

---

## C3 — Phase-Gated Element Support

**Rule:** Element types are only supported from their designated phase onward.
Using a Phase 2 or Phase 3 element in a Phase 1 run must produce a warning, not a crash.

| Element | Phase introduced | Behavior before phase |
|---|---|---|
| `R`, `L`, `C` | Phase 1 | Fully supported |
| `TLIN` | Phase 2 | Warning: "TLIN requires Phase 2 mapping" |
| `SW` | Phase 3 | Warning: "SW requires Phase 3 mapping" |

---

## C4 — Deterministic Output

**Rule:** Given identical inputs (netlist + mapping config + placement config), the agent must
produce bit-identical output artifacts on every run.

**Implications:**
- No random component name generation
- No timestamp-based placement offsets
- Component ordering follows netlist parse order, then alphabetical tiebreak
- Floating-point coordinates rounded to 4 decimal places

---

## C5 — Traceable Intermediate Artifacts

**Rule:** Every run must write all intermediate artifacts to disk before proceeding to the next stage.

| Stage | Artifact written |
|---|---|
| After parse | `<name>_ir.yaml` |
| After mapping | `<name>_buildplan.yaml` |
| After placement | `<name>_placement.yaml` |
| After ADS build | `<name>_ads_generated.net` (via checker) |

**Reason:** Enables debugging without re-running the full pipeline. If ADS crashes mid-build,
the placement plan is already on disk for inspection.

---

## C6 — ADS API: Confirmed Calls Only

**Rule:** Production ADS API calls must be tagged ✅ CONFIRMED in
`../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md`.

Unconfirmed calls (⚠️ UNCONFIRMED) must be:
1. Isolated in a `try/except` block with a descriptive fallback message
2. Flagged in MEMORY.md Section 3 (unconfirmed API calls in use)
3. Never used in the critical path without a confirmed alternative or explicit human sign-off

---

## C7 — Cell Output Only, No Top-Level Schematic Modification

**Rule:** The agent creates new cells in the target library. It does not modify, delete, or
overwrite existing cells unless explicitly instructed with `--force-recreate`.

**Safe recreate pattern (confirmed):**
```python
if cell.view_exists('schematic'):
    cell.delete_view('schematic')
sch_view = de.View.create(cell, 'schematic', 'schematic')
design = sch_view.get_design(DesignMode.WRITE)
```

The agent must NEVER call `shutil.rmtree` on a workspace or library directory without explicit
`--destroy-workspace` flag and human confirmation.

---

## C8 — No Hardcoded Paths in Production Code

**Rule:** ADS workspace path, library name, and PDK paths must be passed as arguments or
loaded from config files. They must not be hardcoded in `translator/` scripts.

Reference defaults live in `schemas/ads_mapping.yaml` (PDK config block).
CLI defaults are defined in each script's `argparse` section.
