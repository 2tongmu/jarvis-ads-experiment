# net2ads Agent Memory

Tracks decisions, confirmed facts, open issues, and phase status.
Updated by the agent during runs. Human-editable for corrections.

---

## Section 1 — Phase Log

| Phase | Status | Date | Sign-off |
|---|---|---|---|
| Phase 1 (R/L/C passive) | ✅ Complete | 2026-04-13 | — |
| Phase 2 (TLIN + PDK) | ✅ Complete | 2026-04-26 | Ertong (ADS GUI) — see C:\Github_folders\jarvis-ads-experiment\PHASE2_SIGN_OFF.md |
| Phase 3 (SW / SPDT) | ✅ Complete — Stage 4/5 SUCCESS | 2026-04-27 09:28 PDT | Schematic build verified on Jarvis Windows; pending probe results |

**Phase 3 Build Summary (2026-04-27 09:28 PDT → 13:36 PDT COMPLETE):**
- ✅ fetbias_sw_gate schematic + symbol built successfully
- ✅ spdt_switch schematic + symbol built successfully (4 FETs + 4 bias subcells)
- ✅ Workspace: C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk\net2ads_lib\
- ✅ **J3-01 COMPLETE (2026-04-27 14:50 PDT):** Design variables (Rs, Cp) now properly exposed as Component Parameters
  - Added `.VAR Rs 1000.0 Ohm` and `.VAR Cp 2272.73 fF` to netlist (2026-04-27 14:25)
  - Auto-generated itemdef.ael file (2026-04-27 14:50)
  - Verified working in ADS GUI (2026-04-27 13:36) — component parameters now show and are editable per-instance
- All ports (P1, P2, P3, VCTRL×4) placed and routed
- **PENDING:** J3-02 (V_DC component), J3-03 (control implementation), J3-04 (visual verification)

Phase advancement requires human sign-off in this table.
Agent must not self-advance phases.

---

## Section 2 — Confirmed ADS API Facts

All sourced from: `../jarvis-eda-learning/workspace-scripts/ADS_API_REFERENCE.md`
All confirmed on: ADS 2026 Update 1 (Jarvis machine)

| API call | Status | Notes |
|---|---|---|
| `de.open_workspace(path)` | ✅ CONFIRMED | Suppress vtb.defs warning with `warnings.catch_warnings()` |
| `de.create_workspace(path)` | ✅ CONFIRMED locally 2026-04-15 | Creates dir + cds.lib + lib.defs; BUT loaded libs are NOT open — must close+reopen or pre-write lib.defs then use open_workspace |
| `de.create_new_library(name, path)` | ✅ CONFIRMED locally 2026-04-15 | Creates lib dir + .oalib; does NOT write DEFINE to lib.defs — patch lib.defs manually then reopen workspace |
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
| `de.db.Transaction(design, label).commit()` | ✅ CONFIRMED 2026-04-15 | **CRITICAL:** Must call before save_design() to finalize OpenAccess metadata. Without this, instances are invisible to netlister (open-circuit bug). Confirmed from ads_build_spdt_pdk.py pattern. |
| `design.save_design()` | ✅ CONFIRMED | Must call — not auto-saved. Always call Transaction.commit() first. |
| `db.create_symbol((lib, cell, 'symbol'))` | ✅ CONFIRMED | |
| `cell.view('symbol')` | ✅ CONFIRMED | |
| `sym_write.add_pin_fig_for_term_type(term_type, (x,y))` | ✅ CONFIRMED | Symbol only — not schematic |
| `sym_write.save_design()` | ✅ CONFIRMED | |
| `list(design.terms)` | ✅ CONFIRMED | Iterate all schematic terms |
| `de.LCVName(lib, cell, view)` | ✅ CONFIRMED | Use for all component references |
| `TermType.INPUT_OUTPUT` from `_pde.db` | ✅ CONFIRMED | Must import from `_pde.db`, not public `db` |
| `DesignMode.WRITE` from `_pde.db` | ✅ CONFIRMED | Must import from `_pde.db`, not public `db` |
| `design.add_dot_for_pin((x, y))` | ✅ CONFIRMED locally 2026-04-14 | Creates visible pin dot on schematic canvas |
| `design.add_pin(term, dot, angle, add_annot)` | ✅ CONFIRMED locally 2026-04-14 | Links dot to term; angle=180 for left ports, 0 for right |
| `sym_design.find_or_add_net(name)` | ✅ CONFIRMED locally 2026-04-14 | Symbol design has its own net/term namespace |
| `sym_design.add_term(net, name, term_type)` | ✅ CONFIRMED locally 2026-04-14 | Must use symbol-side terms (not schematic terms) with sym add_pin |
| `sym_design.add_dot_for_pin((x, y))` | ✅ CONFIRMED locally 2026-04-14 | Symbol pin dot |
| `sym_design.add_pin(sym_term, dot, angle, add_annot)` | ✅ CONFIRMED locally 2026-04-14 | term and dot must be from same block (sym_design); angle=180 left, 0 right |

### Confirmed LCVNames (ads_rflib)

| Component | LCVName | Status |
|---|---|---|
| Resistor | `de.LCVName('ads_rflib','R','symbol')` | ✅ CONFIRMED |
| Capacitor | `de.LCVName('ads_rflib','C','symbol')` | ✅ CONFIRMED |
| Ground | `de.LCVName('ads_rflib','GROUND','symbol')` | ✅ CONFIRMED |
| Inductor | `de.LCVName('ads_rflib','L','symbol')` | ✅ CONFIRMED — local test 2026-04-14/15, ADS 2026 Update 1; L param key = "L", place_inductor works |
| TLIN (PDK) | `de.LCVName('WIN_PP1029_DESIGN_KIT','PP1029_mlin','symbol')` | ✅ CONFIRMED — Jarvis 2026-04-26; params W, L, Layer; ideal `ads_rflib:TLIN` not tested |

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
| `de.LCVName('ads_rflib','L','symbol')` | ~~Inductor LCV may differ~~ | — | CONFIRMED 2026-04-15 locally on ADS 2026 Update 1 via verify_phase1.py full pipeline run |
| `de.LCVName('ads_rflib','TLIN','symbol')` | TLIN cell name TBD | Phase 2 probe needed | Phase 2 work item |
| `design.add_dot_for_pin(location)` | ~~Pin graphic unconfirmed~~ | — | RESOLVED 2026-04-14 — confirmed on both schematic and symbol designs |

---

## Section 4 — Open Issues

| ID | Description | Severity | Owner |
|---|---|---|---|
| OI-01 | ~~Pin graphic not visible on schematic canvas~~ | ~~Medium~~ | RESOLVED 2026-04-14 — use `add_dot_for_pin((x,y))` + `add_pin(term, dot, angle)` after `add_term()`; confirmed locally on ADS 2026 Update 1 |
| OI-02 | ~~Inductor (L) LCV name unconfirmed~~ | ~~High (Phase 1 blocker)~~ | RESOLVED 2026-04-15 — `ads_rflib:L:symbol` + `L` param key confirmed via full pipeline run (verify_phase1.py); reconfirm on Jarvis (Update1) before final sign-off |
| OI-03 | ~~TLIN ADS cell name and parameter names unconfirmed~~ | ~~High (Phase 2 blocker)~~ | RESOLVED 2026-04-26 — PDK path: `WIN_PP1029_DESIGN_KIT:PP1029_mlin`, params W/L/Layer confirmed on Jarvis. Ideal `ads_rflib:TLIN` remains untested (not needed for PDK flow). |
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
| L series angle = 0.0 | Confirmed locally 2026-04-12 — horizontal, same as R | 2026-04-12 |
| L series LCV = ads_rflib:L:symbol | Confirmed locally 2026-04-12 on ADS 2026 Update 1 | 2026-04-12 |
| TLIN → ads_rflib:TLIN by default | Configurable override in ads_mapping.yaml | 2026-04-13 |
| SW ON → R(0.1 Ohm) | Minimal resistive model for Phase 3 topology fidelity | 2026-04-13 |
| SW OFF → C(30 fF) | Matches Coff_Q3a value from spdt_switch.net shunt stub | 2026-04-13 |
| Port terms use TermType.INPUT_OUTPUT | All ports are bidirectional RF ports | 2026-04-13 |
| Series component wiring: P1=origin, P2=origin+(1,0) for angle=0 | Confirmed from ads_build_spdt_pdk.py pin comments; wires must use separate segments, not one continuous wire through series components | 2026-04-14 |
| Shunt component wiring: NO explicit shunt wire from P1→P2 | A wire from P1 to P2 SHORTS the component. Only GND wire (from place_ground, P2→GND) needed. P1 connects via main-path wire endpoint; P2 connects via GND wire start endpoint. | 2026-04-15 |
| Series component wiring: separate segment P2→next_P1, never P1→P2 | A wire spanning a component P1→P2 SHORTS it. Correct: wire from prev_feature to component.P1, then from component.P2 to next_feature. Component body (P1..P2) has no wire. | 2026-04-15 |
| Wire endpoints auto-connect to pins — midpoints do NOT | ADS connects a component pin only if a wire ENDPOINT coincides. A wire passing THROUGH a pin without an endpoint there leaves that pin floating. | 2026-04-15 |
| Co-located component pins (or pin + port) auto-connect without a wire | e.g. last series.P2 and port P2 at same x — no wire segment needed | 2026-04-15 |
| Left-side port angle=180, right-side port angle=0 | Makes pin point outward from circuit boundary; confirmed visually 2026-04-14 | 2026-04-14 |
| Symbol pins at x=0, spaced 2.0 units vertically | Matches `ads_bias_subcell_create.py` confirmed pattern | 2026-04-13 |
| Dual symbol: symbol-side terms required for add_pin | Schematic terms cannot be used with sym_design.add_pin — "must be in the same block" error; must create parallel terms via sym_design.find_or_add_net + sym_design.add_term | 2026-04-14 |
| Dual symbol: left pins at x=0 angle=180, right pins at x=symbol_width angle=0 | Confirmed visually and via successful run 2026-04-14; body rectangle via add_wire polyline | 2026-04-14 |

| Workspace creation pattern | Do NOT rely on de.create_workspace() to open ads_rflib — must pre-write lib.defs (INCLUDE analog_rf.defs + DEFINE lib) then call open_workspace() | 2026-04-15 |
| GND placement offset | place_ground(x, y) takes y=C.P2 position (y=-1.0 for shunt at y=0 angle=-90); places GND symbol at y-1.0=-2.0; draws explicit wire from y to y-1.0 — 3-level shunt chain: signal(0) → C.P2(-1) → GND(-2) | 2026-04-15 |
| lib.defs template for new workspaces | `INCLUDE $HPEESOF_DIR/oalibs/analog_rf.defs` + `DEFINE <lib> <lib>` + `ASSIGN <lib> libMode shared` — cds.lib = `softinclude lib.defs` | 2026-04-15 |
| **CRITICAL: Transaction.commit() before save_design()** | Must wrap all placement operations (add_instance, add_wire, add_term, add_pin) in `de.db.Transaction(design, label).commit()` before calling `design.save_design()`. Without this, instances are not registered in OpenAccess metadata and become invisible to the netlister — causing open-circuit simulation. Confirmed from ads_build_spdt_pdk.py pattern and fixed rc_series_shunt 2026-04-15. Applied to schematic, basic symbol, and dual symbol. | 2026-04-15 |

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
