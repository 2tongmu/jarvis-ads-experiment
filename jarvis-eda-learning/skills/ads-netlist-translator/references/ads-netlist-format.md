# ADS Netlist Format Reference

## Table of Contents
1. [File Structure](#file-structure)
2. [Component Syntax](#component-syntax)
3. [Standard Components](#standard-components)
4. [Subcircuits](#subcircuits)
5. [Simulation Controllers](#simulation-controllers)
6. [Full Example — LPF](#full-example--lpf)
7. [Full Example — SPDT Switch](#full-example--spdt-switch)

---

## File Structure

```
; Comments start with semicolon
; File extension: .net  (consumed by hpeesofsim.exe)

; Optional includes
#include "./model_file.net"

; Variables (optional)
var_name = expression

; Component instances
Type:Name  node1  node2  [nodeN]  param=value unit  [param=value unit ...]

; Subcircuit definition (optional)
define SUBCKT_NAME ( port1  port2 )
  ...components...
end SUBCKT_NAME

; Simulation controller (required for sim)
S_Param:SP1  Start=100 MHz  Stop=18 GHz  Step=100 MHz
```

**Ground node:** `0` (integer zero) — the universal ground reference.

**Units:** Written as a suffix separated by a space from the numeric value.
Supported: `Hz`, `kHz`, `MHz`, `GHz`, `Ohm`, `kOhm`, `H`, `nH`, `pH`, `F`, `pF`, `fF`, `nF`, `uF`, `V`, `mV`, `A`, `mA`, `W`, `dB`

---

## Component Syntax

```
Type:InstanceName  node1  node2  [node3]  ParamKey=NumericValue Unit  ...
```

- Type is case-sensitive (e.g. `R`, `L`, `C`, `Term`, `S_Param`)
- InstanceName must be unique within the netlist
- Nodes are net labels (strings) or `0` for ground
- Params: key=value with unit as next whitespace-delimited token, OR inline: `L=7.958e-9` (SI, no unit suffix)

---

## Standard Components

### Resistor
```
R:R1   node_a  node_b   R=50 Ohm
R:R1   node_a  node_b   R=300 Ohm   Noise=yes
```

### Inductor
```
L:L1   node_a  node_b   L=7.958 nH
L:L1   node_a  node_b   L=50 pH    Noise=yes
```

### Capacitor
```
C:C1   node_a  node_b   C=6.366 pF
C:C1   node_a  0        C=65 fF
```

### Port / Termination
```
Term:Term1   rf_in   0   Num=1   Z=50 Ohm
Term:Term2   rf_out  0   Num=2   Z=50 Ohm
```
`Num` sets the port number for S-parameter indexing (1-based).

### Transmission Line (ideal)
```
TL:TL1   n1  n2   Z=50 Ohm   E=90   F=10 GHz
; E = electrical length in degrees at frequency F
```

### Subcircuit Instance
```
SUBCKT_NAME:X1   node1  node2   [param=value ...]
```

---

## Subcircuits

Use `define`/`end` to encapsulate a repeating stage:

```
define FET_SERIES_ON ( in  out )
  R:Ron   in   mid   R=2.50 Ohm
  L:Ls    mid  out   L=50 pH
end FET_SERIES_ON

FET_SERIES_ON:Q1   rf_in   rf_mid
```

Subcircuit ports map positionally to the node list in the instance line.

---

## Simulation Controllers

### S-Parameter
```
S_Param:SP1   Start=100 MHz   Stop=18 GHz   Step=100 MHz
```
Optional: `CalcNoise=yes`, `CalcZ=yes`, `CalcY=yes`

### AC Analysis
```
AC:AC1   Start=1 MHz   Stop=18 GHz   Dec=10
```

### Harmonic Balance
```
HB:HB1   Freq[1]=2 GHz   Order[1]=5   MaxOrder=5
```

---

## Full Example — LPF

3-element Butterworth LPF, fc ≈ 1 GHz, 50 Ohm system:

```
; lpf_demo.net — Ideal 3rd-order Butterworth LPF
; Topology: series L1 - shunt C1 - series L2 (pi-network)

; Ports
Term:Term1   rf_in   0   Num=1   Z=50 Ohm
Term:Term2   rf_out  0   Num=2   Z=50 Ohm

; Circuit
L:L1   rf_in   mid     L=7.958 nH
C:C1   mid     0       C=6.366 pF
L:L2   mid     rf_out  L=7.958 nH

; Simulation: 100 MHz to 5 GHz
S_Param:SP1   Start=100 MHz   Stop=5 GHz   Step=100 MHz
```

---

## Full Example — SPDT Switch (single arm, ON path)

Double series-shunt GaAs pHEMT SPDT — one signal arm (P1→P2), PATH A active.
Component values from `RF_SPDT_Switch_Analysis.ipynb`.

```
; spdt_switch_path1.net
; Double series-shunt absorptive SPDT — P1->P2 active arm
; GaAs pHEMT, 2-18 GHz, WIN Semi WIP process

; ── Ports ────────────────────────────────────────────────────
Term:Term1   P1   0   Num=1   Z=50 Ohm
Term:Term2   P2   0   Num=2   Z=50 Ohm

; ── Input pad (P1 side) ──────────────────────────────────────
R:Rpad_in   P1        pad_in_L    R=0.05 Ohm
L:Lpad_in   pad_in_L  pad_in      L=10 pH
C:Cpad_in   pad_in    0           C=65 fF

; ── Interconnect #1 (pi-model: C/2 - RL - C/2) ──────────────
C:Cint1a    pad_in    0           C=24 fF
R:Rint1     pad_in    int1_L      R=0.009 Ohm
L:Lint1     int1_L    mid1        L=120 pH
C:Cint1b    mid1      0           C=24 fF

; ── Stage 1: Series FET Q1a (ON path) ────────────────────────
; Series FET ON: Ron=2.50 Ohm + Ls=50 pH
R:Ron_Q1a   mid1      q1a_mid     R=2.50 Ohm
L:Ls_Q1a    q1a_mid   stg1_out    L=50 pH
; Via inductance + resistance under Q1a
R:Rvia_Q1a  stg1_out  stg1_via    R=0.08 Ohm
L:Lvia_Q1a  stg1_via  stg1_node   L=50 pH

; Gate-drain feedback: Cgd in series with (Rg || Cp_Rg) + Ls_Rg
C:Cgd_Q1a   stg1_node  cgd1_mid   C=8 fF
R:Rg_Q1a    cgd1_mid   gate1      R=300 Ohm
C:Cpg_Q1a   cgd1_mid   0          C=12 fF
L:Lsg_Q1a   gate1      0          L=150 pH

; Shunt FET Q3a OFF: Coff_sh + Ls_sh in series, then R_term to GND
C:Coff_Q3a  stg1_node  sh1_mid    C=30 fF
L:Lsh_Q3a   sh1_mid    sh1_r      L=50 pH
R:Rterm1    sh1_r      0          R=47 Ohm

; ── Stage 2: Series FET Q1b (ON path) ────────────────────────
R:Ron_Q1b   stg1_node  q1b_mid    R=2.50 Ohm
L:Ls_Q1b    q1b_mid    stg2_out   L=50 pH
R:Rvia_Q1b  stg2_out   stg2_via   R=0.08 Ohm
L:Lvia_Q1b  stg2_via   stg2_node  L=50 pH

C:Cgd_Q1b   stg2_node  cgd2_mid   C=8 fF
R:Rg_Q1b    cgd2_mid   gate2      R=300 Ohm
C:Cpg_Q1b   cgd2_mid   0          C=12 fF
L:Lsg_Q1b   gate2      0          L=150 pH

C:Coff_Q3b  stg2_node  sh2_mid    C=30 fF
L:Lsh_Q3b   sh2_mid    sh2_r      L=50 pH
R:Rterm2    sh2_r      0          R=47 Ohm

; ── Interconnect #2 ──────────────────────────────────────────
C:Cint2a    stg2_node  0          C=24 fF
R:Rint2     stg2_node  int2_L     R=0.009 Ohm
L:Lint2     int2_L     pad_out    L=120 pH
C:Cint2b    pad_out    0          C=24 fF

; ── Output pad (P2 side) ─────────────────────────────────────
C:Cpad_out  pad_out    0          C=65 fF
L:Lpad_out  pad_out    pad_out_R  L=10 pH
R:Rpad_out  pad_out_R  P2         R=0.05 Ohm

; ── Simulation ───────────────────────────────────────────────
S_Param:SP1   Start=2 GHz   Stop=18 GHz   Step=100 MHz
```

**Expected results (PATH A active):**

| Freq (GHz) | IL (dB) | RL_in (dB) | ISO (dB) |
|---|---|---|---|
| 2  | 0.459 | 24.5 | 60.6 |
| 6  | 0.548 | 19.8 | 41.7 |
| 10 | 0.685 | 17.6 | 33.1 |
| 14 | 0.819 | 17.6 | 27.6 |
| 18 | 0.927 | 20.6 | 23.5 |

All IL < 1 dB, ISO > 20 dB across 2–18 GHz. ✅
