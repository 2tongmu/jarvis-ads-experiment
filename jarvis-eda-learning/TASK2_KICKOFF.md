# TASK2_KICKOFF.md
# Bias Network Expansion — Kickoff Brief

## Current Status
Bias network expansion starting.
Phase 1 (schematic generation) complete and checker-verified for spdt_switch.
Gate nodes are floating — bias networks were intentionally skipped during Phase 1.

## What Exists

4 FETs placed and connected in ADS schematic:

| FET | Type | Size | Gate node | Status |
|---|---|---|---|---|
| Q1a | Series | 160 um (NOF=2 UGW=80) | ng_Q1a | Floating |
| Q3a | Shunt  | 100 um (NOF=2 UGW=50) | ng_Q3a | Floating |
| Q1b | Series | 160 um (NOF=2 UGW=80) | ng_Q1b | Floating |
| Q3b | Shunt  | 100 um (NOF=2 UGW=50) | ng_Q3b | Floating |

PDK: WIN_PP1029_DESIGN_KIT, cell WIN_PP1029_CPW
Frequency range: 2–18 GHz

## Bias Topology (from spdt_switch_prep.net)

Identical for all 4 FETs:

```
ng_<FET>  ──┬── Rg (300 Ω) ──┐
            └── Cpg (12 fF) ──┴── ng2_<FET> ── Lsg (150 pH) ── GND
```

- Rg and Cpg are in parallel between the gate node and the mid-node (ng2_*)
- Lsg connects mid-node to GND
- No DC control voltage node — all networks terminate at GND (static bias stub)

Source: GBIAS_Q1a / GBIAS_Q3a / GBIAS_Q1b / GBIAS_Q3b blocks in spdt_switch_prep.net

## What Needs to Be Built

### 1. `bias-rules/` folder
New directory at repo root. Holds machine-readable bias design rules loaded by builder scripts.

### 2. Design rule YAML
`bias-rules/WIN_PP1029_gbias_rules.yaml`
Should define:
- Bias topology (component types, values, connections)
- Node naming convention (ng_*, ng2_*)
- Placement rules for Rg, Cpg, Lsg relative to FET gate pin
- Any FET-size-dependent overrides (if applicable)

### 3. Builder script
`workspace-scripts/ads_add_bias_networks.py`
Should:
- Load bias rules from YAML
- Accept a list of FETs with gate nodes and gate pin coordinates
- Place Rg, Cpg, Lsg for each FET
- Wire each bias network to its FET gate pin
- Re-run ads-schematic-checker after build
- Follow the standard script header format (see IMPROVEMENT.md)

## Definition of Done

- All 4 gate nodes connected (no floating ng_* nodes)
- ads-schematic-checker passes with zero errors
- Bias component values match prep.net: Rg=300 Ω, Cpg=12 fF, Lsg=150 pH
- ads_add_bias_networks.py added to SKILLS.md
- MEMORY.md updated with run outcome
