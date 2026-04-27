# Phase 3 SPDT Execution Plan
**Date:** 2026-04-27 09:20 PDT  
**Target:** Build SPDT_SWITCH + fetbias_sw_gate ADS schematics (Stage 4/5)  
**Environment:** Windows (Jarvis machine) with ADS 2026 Update 1

---

## Executive Summary

The net2ads offline pipeline (Stages 1–3) has completed successfully. All artifacts are staged and ready for Windows ADS build execution (Stages 4–5).

**What will happen:**
1. Run `net2ads.py` on spdt_switch_research.net
2. Pipeline creates SPDT_SWITCH ADS schematic with 4 FET instances + 4 fetbias subcells
3. Exports netlist + placement artifacts
4. Run ads-schematic-checker to verify connectivity
5. Generate success/failure report

**Expected duration:** <2 minutes (ADS operations)  
**Expected output files:**
- `examples/spdt_switch/spdt_switch_ads_generated.net` (netlist)
- ADS workspace at `C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk\`
- Connectivity report (stdout)

---

## Environment Confirmation

### Jarvis Machine Details
- **OS:** Windows 10/11
- **ADS:** Keysight ADS 2026 Update 1
- **ADS Path:** `C:\Program Files\Keysight\ADS2026_Update1\`
- **Python:** `C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe`
- **ADS packages:** `C:\Program Files\Keysight\ADS2026_Update1\tools\python\packages\keysight\`

### Pre-Flight Checks ✅

- [x] ADS 2026 Update 1 installed at standard path
- [x] Python packages available at standard location
- [x] net2ads repository synced to Windows: `C:\Users\jarvis\jarvis-ads-experiment\`
- [x] Input netlist ready: `examples/spdt_switch/spdt_switch_research.net`
- [x] SW map ready: `examples/spdt_switch/spdt_switch_sw_map.yaml`
- [x] Phase 2 artifacts verified (no blockers from earlier phases)

---

## Execution Steps

### Step 1: Open Windows Command Prompt or PowerShell

```powershell
# Navigate to repository root
cd C:\Users\jarvis\jarvis-ads-experiment
```

### Step 2: Run Stage 1–4 Dry-Run (Verify Offline Stages)

This confirms all offline stages (parse, map, placement) work correctly without ADS:

```powershell
python net2ads.py examples/spdt_switch/spdt_switch_research.net `
  --workspace C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk `
  --lib net2ads_lib `
  --sw-map examples/spdt_switch/spdt_switch_sw_map.yaml `
  --dry-run
```

**Expected output:**
```
[Stage 1] Parsing research netlist...
[Stage 2] Building IR...
[Stage 3] Mapping IR to ADS build plan...
[Stage 4] Computing placement...
================================================================
status: success
stage_completed: 4
outputs:
  - examples/spdt_switch/spdt_switch_ir.yaml
  - examples/spdt_switch/spdt_switch_buildplan.yaml
  - examples/spdt_switch/spdt_switch_placement.yaml
next_action: Run without --dry-run to build ADS cell...
errors: none
================================================================
```

**Time:** <5 seconds (no ADS involved)

### Step 3: Run Full Execution (Stages 1–5, ADS Build)

If dry-run succeeds, proceed with full build:

```powershell
python net2ads.py examples/spdt_switch/spdt_switch_research.net `
  --workspace C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk `
  --lib net2ads_lib `
  --sw-map examples/spdt_switch/spdt_switch_sw_map.yaml
```

**Expected output:**
```
[Stage 1] Parsing research netlist...
[Stage 2] Building IR...
[Stage 3] Mapping IR to ADS build plan...
[Stage 4] Computing placement...
[Stage 5] Building ADS cell...
  [ads] workspace: C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk
  [ads] library  : net2ads_lib
  [ads] opening schematic view...
  [ads] placing 19 instances (7 ports)
  [ads] wiring signal paths (12 wire segments)
  [ads] creating dual symbol
  [ads] saving design...
================================================================
status: success
stage_completed: 5
outputs:
  - examples/spdt_switch/spdt_switch_ads_generated.net
  - (ADS schematic cell: net2ads_lib:SPDT_SWITCH:schematic+symbol)
next_action: Run ads-schematic-checker on generated netlist
errors: none
================================================================
```

**Time:** 30–60 seconds (ADS session + schematic build)

### Step 4: Verify Output Netlist

```powershell
# Check that netlist was exported
dir examples/spdt_switch/spdt_switch_ads_generated.net

# View first few lines
Get-Content examples/spdt_switch/spdt_switch_ads_generated.net -TotalCount 20
```

### Step 5: Run Connectivity Checker

```powershell
# From the main workspace, launch ads-schematic-checker
python ~/openclaw/skills/ads-schematic-checker/scripts/check_netlist.py `
  examples/spdt_switch/spdt_switch_ads_generated.net
```

**Expected output:**
```
================================================================
Connectivity Check Results
================================================================
Port P1:           ✅ Connected
Port P2:           ✅ Connected
Port P3:           ✅ Connected
Port VCTRL_*:      ✅ All connected

Floating nodes:    ✅ None detected
Open circuits:     ✅ None detected
Signal integrity:  ✅ All paths complete

================================================================
STATUS: ALL CHECKS PASSED ✅
================================================================
```

### Step 6 (Optional): Visual Inspection in ADS GUI

```powershell
# Open the workspace in ADS GUI (optional for visual verification)
C:\Program Files\Keysight\ADS2026_Update1\bin\ads.exe `
  -w C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk
```

In ADS GUI:
- Open library `net2ads_lib`
- Open cell `SPDT_SWITCH`, view `schematic`
- Verify:
  - 7 ports visible (P1, P2, P3, VCTRL×4)
  - 4 WIN_PP1029_CPW FET instances with correct pin orientations
  - 4 fetbias_sw_gate subcell instances below gates
  - All wiring connected
  - Symbol displays correctly (dual symbol: left/right pins)

---

## Artifact Locations After Execution

### On Disk (Linux/WSL)
```
~/.openclaw/workspace/jarvis-ads-experiment/
├── examples/spdt_switch/
│   ├── spdt_switch_research.net              (input)
│   ├── spdt_switch_sw_map.yaml               (input)
│   ├── spdt_switch_ir.yaml                   (output)
│   ├── spdt_switch_buildplan.yaml            (output)
│   ├── spdt_switch_placement.yaml            (output)
│   ├── spdt_switch_ads_generated.net         (output — netlist)
│   └── fetbias_sw_gate/
│       ├── fetbias_sw_gate_research.net      (input — generated)
│       ├── fetbias_sw_gate_ir.yaml           (output)
│       ├── fetbias_sw_gate_buildplan.yaml    (output)
│       └── fetbias_sw_gate_placement.yaml    (output)
```

### On Windows (ADS Workspace)
```
C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk\
├── cds.lib
├── lib.defs
└── net2ads_lib/
    ├── cdsinfo.tag
    ├── SPDT_SWITCH/
    │   ├── schematic/
    │   │   └── (schematic view data)
    │   └── symbol/
    │       └── (symbol view data)
    └── fetbias_sw_gate/
        ├── schematic/
        └── symbol/
```

---

## Success Criteria

- [ ] **Dry-run passes** — Stages 1–4 complete without errors
- [ ] **Full build succeeds** — ADS schematic + symbol created
- [ ] **Netlist exports** — `spdt_switch_ads_generated.net` exists and is valid
- [ ] **Connectivity check passes** — `ALL CHECKS PASSED ✅`
- [ ] **Visual inspection OK** — Schematic opens in ADS GUI, ports/FETs/subcells visible
- [ ] **All artifacts staged** — 7 YAML files + 1 netlist present

---

## Troubleshooting

### Error: "ModuleNotFoundError: No module named 'keysight'"

**Cause:** Using wrong Python interpreter

**Fix:**
```powershell
# Use ADS Python explicitly
C:\Program Files\Keysight\ADS2026_Update1\tools\python\python.exe net2ads.py ...
```

### Error: "Workspace already in use / access denied"

**Cause:** Another ADS instance using the workspace

**Fix:**
1. Close all ADS GUI windows
2. Wait 5 seconds
3. Retry

### Error: "SW map YAML not found"

**Cause:** Wrong path to `spdt_switch_sw_map.yaml`

**Fix:** Verify file exists:
```powershell
dir examples/spdt_switch/spdt_switch_sw_map.yaml
```

### Status shows "partial" instead of "success"

**Cause:** One or more UNCONFIRMED API calls were detected

**Fix:**
1. Check error list in status block
2. Examine `MEMORY.md` Section 3 (Unconfirmed API Calls)
3. Document probe result and update status

---

## Next Actions After Successful Build

### Immediate (Phase 3b Probes)

1. **J3-01: Parameter override test**
   - In ADS GUI, open `net2ads_lib:SPDT_SWITCH:schematic`
   - Select instance `BIAS_SW_SERIES_A` (fetbias)
   - Check Properties: Rs should show "1000 Ohm" (overridden from default 1040.2)
   - **Document result** in MEMORY.md

2. **J3-02: V_DC component search**
   - In ADS, search library browser for `ads_rflib:V_DC`
   - If found: note LCV + parameter names
   - If not found: ask for guidance on equivalent component
   - **Document result** in MEMORY.md

3. **J3-04: WIN_PP1029_CPW pin orientation**
   - Visual inspection of FET instances in SPDT schematic
   - Verify series FETs (Q_SW_SERIES_A/B) have drain left, source right, gate below
   - Verify shunt FETs (Q_SW_SHUNT_A/B) have drain upward, source downward
   - **Document result** in MEMORY.md

### Deferred (Phase 3c — Control Voltage Implementation)

- J3-03: Replace VCTRL pins with internal V_DC sources (on-state=0V, off-state=−1.5V)
- Update `ads_api/schematic_ops.py` to instantiate V_DC during SPDT build
- Requires J3-02 confirmation first

### Sign-Off (Phase 3 Complete)

- Update MEMORY.md: `Phase 3 ✅ Complete` (with date)
- Commit to GitHub with tag `v0.3-phase3-complete`
- Archive this execution plan in project notes

---

## Command Quick Reference

**Dry-run (safe, no ADS):**
```powershell
cd C:\Users\jarvis\jarvis-ads-experiment
python net2ads.py examples/spdt_switch/spdt_switch_research.net `
  --workspace C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk `
  --lib net2ads_lib `
  --sw-map examples/spdt_switch/spdt_switch_sw_map.yaml `
  --dry-run
```

**Full build (with ADS):**
```powershell
python net2ads.py examples/spdt_switch/spdt_switch_research.net `
  --workspace C:\Users\jarvis\ads_projects\spdt_phase3_test_wrk `
  --lib net2ads_lib `
  --sw-map examples/spdt_switch/spdt_switch_sw_map.yaml
```

**Connectivity check:**
```powershell
python ~/openclaw/skills/ads-schematic-checker/scripts/check_netlist.py `
  examples/spdt_switch/spdt_switch_ads_generated.net
```

---

## Document Metadata

- **Created:** 2026-04-27 09:20 PDT
- **Purpose:** Stage 4/5 execution plan for Phase 3 SPDT build
- **Status:** Ready for execution
- **Owner:** Jarvis-EDA (net2ads sub-agent)
- **Reference:** PLAYBOOK.md (full workflow), ENVIRONMENT.md (setup details)
