# net2ads Agent Memory

Tracks decisions, confirmed facts, open issues, and phase status.
Updated by the agent during runs. Human-editable for corrections.

---

## Section 1 — Phase Log

| Phase | Status | Date | Sign-off |
|---|---|---|---|
| Phase 1 (R/L/C passive) | 🔵 Active — implementation in progress | 2026-04-13 | — |
| Phase 2 (TLIN + PDK) | ⏳ Planned | — | — |
| Phase 3 (SW / SPDT) | ⏳ Planned | — | — |

Phase advancement requires human sign-off in this table.
Agent must not self-advance phases.

---

## Section 2 — Confirmed ADS API Facts

All sourced from: `../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md`
All confirmed on: ADS 2026 Update 1 (Jarvis machine)

| API call | Status | Notes |
|---|---|---|
| `de.open_workspace(path)` | ✅ CONFIRMED | Suppress vtb.defs warning with `warnings.catch_warnings()` |
| `de.get_open_library(name)` | ✅ CONFIRMED | Library must exist in workspace lib.defs |
| `lib.cell_exists(name)` | ✅ CONFIRMED | |
| `lib.cell(name)` | ✅ CONFIRMED | |
| `de.Cell.create(lib, name)` | ✅ CONFIRMED | |
| `cell.view_exists('schematic')` | ✅ CONFIRMED | |
| `cell.delete_view('schematic')` | ✅ CONFIRMED | |
| `de.View.create(cell, 'schematic', 'schematic')` | ✅ CONFIRMED | |
| `sch_view.get_design(DesignMode.WRITE)` | ✅ CONFIRMED | Default is READ_ONLY — always use WRITE |
| `design.find_or_add_net(name)` | ✅ CONFIRMED | Idempotent |
| `design.add_term(net, name, TermType.INPUT_OUTPUT)` | ✅ CONFIRMED | Sub-cell pin; no graphic on canvas |
| `design.add_instance(LCVName(...), (x,y), name=, angle=)` | ✅ CONFIRMED | |
| `inst.parameters[key].value = expr` | ✅ CONFIRMED | String with unit suffix preferred |
| `design.add_wire([(x1,y1),(x2,y2),...])` | ✅ CONFIRMED | One call = one polyline |
| `design.cell.write_design_variables([...])` | ✅ CONFIRMED | |
| `design.save_design()` | ✅ CONFIRMED | Must call — not auto-saved |
| `db.create_symbol((lib, cell, 'symbol'))` | ✅ CONFIRMED | |
| `cell.view('symbol')` | ✅ CONFIRMED | |
| `sym_write.add_pin_fig_for_term_type(term_type, (x,y))` | ✅ CONFIRMED | Symbol only — not schematic |
| `sym_write.save_design()` | ✅ CONFIRMED | |
| `list(design.terms)` | ✅ CONFIRMED | Iterate all schematic terms |
| `de.LCVName(lib, cell, view)` | ✅ CONFIRMED | Use for all component references |
| `TermType.INPUT_OUTPUT` from `_pde.db` | ✅ CONFIRMED | Must import from `_pde.db`, not public `db` |
| `DesignMode.WRITE` from `_pde.db` | ✅ CONFIRMED | Must import from `_pde.db`, not public `db` |

### Confirmed LCVNames (ads_rflib)

| Component | LCVName | Status |
|---|---|---|
| Resistor | `de.LCVName('ads_rflib','R','symbol')` | ✅ CONFIRMED |
| Capacitor | `de.LCVName('ads_rflib','C','symbol')` | ✅ CONFIRMED |
| Ground | `de.LCVName('ads_rflib','GROUND','symbol')` | ✅ CONFIRMED |
| Inductor | `de.LCVName('ads_rflib','L','symbol')` | ⚠️ UNCONFIRMED — assumed by analogy |
| TLIN | `de.LCVName('ads_rflib','TLIN','symbol')` | ⚠️ UNCONFIRMED — Phase 2 item |

### Confirmed placement angles

| Component | Angle | Source |
|---|---|---|
| R (series, horizontal) | 0.0 | `ads_build_spdt_pdk.py` mkR() |
| L (series, horizontal) | 0.0 | assumed by analogy with R |
| C (shunt, vertical, pin1 at top) | −90.0 | `ads_build_spdt_pdk.py` mkC() |
| GND symbol | −90.0 | `ads_build_spdt_pdk.py` mkGnd() |

### Confirmed coordinate conventions

| Reference point | x | y | Source |
|---|---|---|---|
| Port 1 (left) wire endpoint | 1.375 | 0.0 | `net_to_ads_cell.py` _PORT_LEFT |
| Port 2 (right) wire endpoint | 5.25 | 0.0 | `net_to_ads_cell.py` _PORT_RIGHT (1-shunt, 1-series) |
| First shunt component | 2.875 | 0.0 | `net_to_ads_cell.py` _SHUNT_X[0] |
| First series component | 4.25 | 0.0 | `net_to_ads_cell.py` _SERIES_X[0] |
| GND below shunt | shunt_x | −1.0 | `ads_bias_subcell_create.py` |

---

## Section 3 — Unconfirmed API Calls in Use

Any API call below marked ⚠️ must be isolated in try/except and investigated before
relying on it in production builds.

| API call | Risk | Fallback | Investigation status |
|---|---|---|---|
| `de.LCVName('ads_rflib','L','symbol')` | Inductor LCV may differ | Log error; skip | Not yet run on Jarvis |
| `de.LCVName('ads_rflib','TLIN','symbol')` | TLIN cell name TBD | Phase 2 probe needed | Phase 2 work item |
| `design.add_dot_for_pin(location)` | Pin graphic — unconfirmed path | Use `add_pin_fig_for_term_type` on symbol | §12 of ADS_API_REFERENCE.md |

---

## Section 4 — Open Issues

| ID | Description | Severity | Owner |
|---|---|---|---|
| OI-01 | Pin graphic not visible on schematic canvas — `add_term()` creates no graphic | Medium | Deferred: use symbol view instead |
| OI-02 | Inductor (L) LCV name `ads_rflib:L:symbol` unconfirmed — needs Jarvis probe run | High (Phase 1 blocker) | Agent — must probe before Phase 1 sign-off |
| OI-03 | TLIN ADS cell name and parameter names unconfirmed | High (Phase 2 blocker) | Agent — Phase 2 start |
| OI-04 | SW element mapping for SPDT is resistive/capacitive placeholder only | Low (Phase 3 known) | Human — PDK FET substitution is future work |
| OI-05 | `ads_schematic_ports_ic:iopin` not confirmed as usable for schematic pin graphics | Low | Deferred — investigate in Phase 1 |
| OI-06 | Multi-shunt topology placement (>1 shunt component) not yet generalized | Medium | Phase 1 — only single-shunt circuits in scope initially |
| OI-07 | 3-port placement geometry (SPDT) not yet defined | Medium | Phase 3 work item |
| OI-08 | `MILS_PER_UNIT` conversion factor in `ads_bias_inserter.py` unverified | Low (external) | Human — measure in ADS GUI |

---

## Section 5 — Mapping Decisions

| Decision | Rationale | Date |
|---|---|---|
| R series angle = 0.0 | Confirmed from `ads_build_spdt_pdk.py` mkR() | 2026-04-13 |
| C shunt angle = −90.0 | Confirmed from `ads_build_spdt_pdk.py` mkC() | 2026-04-13 |
| GND angle = −90.0 | Confirmed from `ads_build_spdt_pdk.py` mkGnd() | 2026-04-13 |
| L series angle = 0.0 | Assumed same as R — not yet Jarvis-confirmed | 2026-04-13 |
| L series LCV = ads_rflib:L:symbol | Assumed by analogy with R/C — needs probe | 2026-04-13 |
| TLIN → ads_rflib:TLIN by default | Configurable override in ads_mapping.yaml | 2026-04-13 |
| SW ON → R(0.1 Ohm) | Minimal resistive model for Phase 3 topology fidelity | 2026-04-13 |
| SW OFF → C(30 fF) | Matches Coff_Q3a value from spdt_switch.net shunt stub | 2026-04-13 |
| Port terms use TermType.INPUT_OUTPUT | All ports are bidirectional RF ports | 2026-04-13 |
| Symbol pins at x=0, spaced 2.0 units vertically | Matches `ads_bias_subcell_create.py` confirmed pattern | 2026-04-13 |

---

## Section 6 — Future Extensions (Not In Scope)

| Extension | Trigger |
|---|---|
| Full PDK FET substitution for SW elements | Phase 3 completion + human sign-off |
| Simulation bench generation (separate cell) | Phase 4 — post Phase 3 sign-off |
| Layout integration (GDS export) | Phase 5 — post simulation validation |
| Multi-port S-param cell (>2 ports) generalized placement | Phase 3 SPDT work |
| net-label API (`vctrl_A`, `vctrl_B`) | When ADS net-label Python API is confirmed |
| Bias network auto-insertion (GBIAS_SWITCH_GATE) | Post Phase 3 — calls `gate_bias_network.py` |
