---
name: ads-netlist-translator
description: >
  Translate Python-based RF circuit analysis scripts (numpy/ABCD matrix style) into ADS-compatible
  netlists and ADS schematics. Covers both ideal lumped-element circuits and PDK-based schematics
  using WIN_PP1029_DESIGN_KIT (or similar). Use when the user has a Python RF circuit definition
  and wants to reproduce it in Keysight ADS as a schematic for simulation. Handles the full
  3-stage pipeline: raw ideal netlist to annotated prep netlist with @PDK_SWAP tags to ADS
  schematic with real PDK FET components. Also use when asked to "convert Python circuit to ADS",
  "import circuit into ADS", "build ADS schematic from Python model", "swap ideal FETs with PDK
  components", or "build PDK schematic".
---

# ADS Netlist Translator

Translates Python RF circuit definitions → ADS netlists → ADS schematics, with optional PDK component substitution.

## Two Workflows

### Workflow A: Ideal Lumped-Element (quick validation)
`Python model → spdt_switch.net → ads_build_spdt.py → ADS schematic + sim`

Use to validate circuit topology and S-parameters before involving PDK.
Reference: `references/ads-netlist-format.md`, `references/ads-python-api.md`

### Workflow B: Full PDK Pipeline (production schematic)
`Python model → net_prepare.py → net_parse.py → ads_import_netlist.py → ADS schematic with PDK FETs`

Use when the final schematic must use foundry PDK transistor models.
Reference: `references/pdk-pipeline.md`

---

## Workflow A — Ideal Netlist

### Step 1: Write hand-crafted netlist (.net)

Key rules (full spec in `references/ads-netlist-format.md`):
- Port keyword: `Port:` (not `Term:` — Term is the ADS schematic symbol name)
- Ground node: `0`
- Units as suffixes: `7.958 nH`, `65 fF`, `300 Ohm`
- ASCII only — no Unicode (Windows cp1252 encoding)
- S-param controller: use `SweepPlan:` + `OutputPlan:` pattern (see reference)

### Step 2: Build ADS schematic via Python API

Key patterns (full reference in `references/ads-python-api.md`):
- R/L placed at midpoint (cx,cy): P1=(cx-0.5,cy), P2=(cx+0.5,cy)
- C shunt at (x,y) angle=-90: P1=(x,y), P2=(x,y-1)
- Term at (x,y) angle=-90: RF pin=(x,y), GND pin=(x,y-1) — **always add companion GROUND instance**
- lib.defs INCLUDE path must NOT be quoted: `INCLUDE C:\path\lib.defs`
- Wire endpoint must EXACTLY match component pin snap_point to connect
- Workspace delete before recreate; check `workspace.libraries` before `add_library`

### Step 3: Simulate and validate

```python
simulator = edatoolbox_ads.CircuitSimulator()
simulator.run_netlist(netlist_text, output_dir=str(SIM_DIR))
ds = dataset.open(ds_files[0])
df = ds["SP1.SP"].to_dataframe()  # index=freq Hz, cols=S[2,1] etc.
```

---

## Workflow B — Full PDK Pipeline

### Stage 1: net_prepare.py — Annotate raw netlist

Input:  `circuit.net`  (ideal R/L/C model)
Output: `circuit_prep.net`  (same components + `@BLOCK`/`@PDK_SWAP` tags)

Each component group gets a `@BLOCK` with:
- `type=TRANSISTOR|PASSIVE_NETWORK|TLINE|PORT|SIM_CTRL`
- `@PDK_SWAP model=<cell> params="NOF=2 UGW=80" port1=<node> port2=<node> port3=<gate_node> replaces=<comps> keep=<comps>`
- `@KEEP components=<comps>` for passives that stay as-is

### Stage 2: net_parse.py — Substitute PDK components

Input:  `circuit_prep.net`
Output: `circuit_ads_import.net`

Parser reads `@BLOCK`/`@PDK_SWAP` tags and emits:
- PDK FET instances in correct netlist syntax
- Kept passives unchanged
- GBIAS blocks skipped by default until FET connections verified (toggle in net_parse.py)

### Stage 3: ads_import_netlist.py — Build ADS schematic

Input:  `circuit_ads_import.net` (read before workspace wipe)
Output: ADS workspace with PDK schematic

Key behaviours:
- Opens existing workspace if present; deletes cell dir on disk before recreating
- Checks `workspace.libraries` before `add_library` to avoid duplicates
- All components placed on flat y=0 signal line, x increases left to right
- Shunt FETs hang downward (drain on signal line, source below)
- Gate pins left floating until GBIAS blocks re-enabled after visual verification
- Simulate from ADS GUI — PDK models (PP1029_CPW_PDK) not resolvable by standalone hpeesofsim

---

## WIN_PP1029_CPW Pin Layout (CONFIRMED ADS 2026)

Critical — wrong pin order = all nodes short to GND:

```
bbox: (0, -0.5) to (0.68125, 0.5)
P1 = Gate   snap (0.0,  0.0)  -- left pin
P2 = Drain  snap (0.5, +0.5)  -- top pin
P3 = Source snap (0.5, -0.5)  -- bottom pin
Netlist order: gate  drain  source  (P1 P2 P3)
```

**Series FET placement (angle=90):**
- Instance at (drain_x+0.5, y-0.5)
- Drain=(drain_x, y), Source=(drain_x+1, y), Gate=(drain_x+0.5, y-0.5)

**Shunt FET placement (angle=0):**
- Instance at (rf_x-0.5, y-0.5)
- Drain=(rf_x, y), Source=(rf_x, y-1), Gate=(rf_x-0.5, y-0.5)

**WIN_PP1029_MS** (2-port) has source pre-grounded — do NOT use for switch FETs.

---

## ⚠️ Authoritative Skills & Workflows Location

For all net-to-ADS schematic work, the **canonical skills and workflows** are in:
```
~/.openclaw/workspace/jarvis-ads-experiment/
```

Sub-agents MUST read all files from that folder before starting any Stage 3 work:
- `memory/` — project_goal.md, current_scope.md, ads_execution_context.md
- `skills/` — all 6 skill files (ads_python_interface.md contains confirmed pin geometry)
- `workflows/` — ads_import_to_placeplan.md, review_example_net_flow.md
- `schemas/placeplan_schema.md`
- `input/spdt_switch_placeplan.yaml` — filled placement plan

Launch template: `notes/launch_ads_placeplan_subagent.md`

After building schematic, always run connectivity checker:
```
python ~/openclaw/skills/ads-schematic-checker/scripts/check_netlist.py <generated.net>
```
Do NOT report success until ALL CHECKS PASSED ✅.

## SPDT Switch Example (reference project)

Workspace: `C:\Users\jarvis\ads_projects\spdt_pdk_wrk`
Library:   `spdt_switch_lib`
Cell:      `spdt_switch`
Scripts:   `~/.openclaw/workspace/net_prepare.py`, `net_parse.py`, `ads_import_netlist.py`
Netlists:  `spdt_switch.net`, `spdt_switch_prep.net`, `spdt_switch_ads_import.net`

FET topology (PATH A active, Q1a/Q1b series ON, Q3a/Q3b shunt OFF/absorptive):
- Q1a: series 160µm — Drain=n4, Source=n8, Gate=ng_Q1a  (NOF=2 UGW=80)
- Q3a: shunt 100µm  — Drain=n8, Source→Rtrm1→GND, Gate=ng_Q3a (NOF=2 UGW=50)
- Q1b: series 160µm — Drain=n8, Source=n12, Gate=ng_Q1b (NOF=2 UGW=80)
- Q3b: shunt 100µm  — Drain=n12, Source→Rtrm2→GND, Gate=ng_Q3b (NOF=2 UGW=50)

## Known Issues / Lessons Learned

- hpeesofsim crashes on WSL `\\wsl.localhost\...` paths — copy netlists to `C:\Users\...\Temp\`
- PDK models (PP1029_CPW_PDK) only resolve inside ADS GUI — not via standalone CircuitSimulator
- Wire endpoints must EXACTLY match pin snap_points — use confirmed coordinates, not approximations
- vtb.defs/SystemVue warning on workspace open is benign — suppress with `warnings.catch_warnings()`
- ADS workspace lock: delete cell dir on disk (`shutil.rmtree`) instead of via API
- Duplicate library: check `workspace.libraries` list before calling `add_library`

## References

- `references/ads-netlist-format.md` — full netlist syntax, component mappings, examples
- `references/ads-python-api.md` — ADS Python API patterns, pin coordinates, common pitfalls
- `references/pdk-pipeline.md` — 3-stage PDK pipeline detail, @BLOCK tag format, WIN_PP1029 guide
