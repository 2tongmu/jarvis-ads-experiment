# net_prepare.py
# Step 1 of the ADS schematic pipeline:
#   input:  (circuit).net       -- raw ideal lumped-element netlist
#   output: (circuit)_prep.net  -- annotated netlist with structured @BLOCK and @PDK_SWAP tags
#
# What this step does:
#   1. Preserves all components and connectivity exactly (no values changed)
#   2. Groups related ideal components into named logical blocks using @BLOCK/@END_BLOCK
#   3. Annotates each block with its fundamental element type
#   4. Adds structured @PDK_SWAP tags where a PDK component should replace ideal elements
#   5. Marks keep-as-is components explicitly
#
# Fundamental element types recognised:
#   RESISTOR | CAPACITOR | INDUCTOR | TLINE | DIODE | TRANSISTOR |
#   VSOURCE  | ISOURCE   | XFORMER  | PORT  | SIM_CTRL | PASSIVE_NETWORK
#
# @BLOCK tag format:
#   ; @BLOCK  name=<id>  type=<fundamental>  desc="<human description>"
#   ; @END_BLOCK name=<id>
#
# @PDK_SWAP tag format (inside a @BLOCK):
#   ; @PDK_SWAP  model=<pdk_cell>  params="<key=val ...>"  port1=<node>  port2=<node>  [port3=<node>]
#   ;            replaces=<comp1,comp2,...>  keep=<comp1,comp2,...>
#
# The parser in ads_import_netlist.py reads these tags to:
#   - Know which components to instantiate from the PDK
#   - Know which ideal components to delete vs keep
#   - Know how to wire the PDK instance into the existing nodes
#
# Usage:
#   python3 net_prepare.py spdt_switch.net
#   --> produces spdt_switch_prep.net

import sys, re
from pathlib import Path

def prepare(input_path: Path) -> str:
    src = input_path.read_text(encoding="utf-8")
    out = []

    out.append(f"; {'='*68}")
    out.append(f"; {input_path.stem}_prep.net")
    out.append(f"; Prepared from: {input_path.name}")
    out.append(f"; Pipeline stage: 1 of 3  (raw .net -> prepared .net -> ADS schematic)")
    out.append(f";")
    out.append(f"; @BLOCK / @PDK_SWAP tag guide for ads_import_netlist.py:")
    out.append(f";   @BLOCK      -- groups ideal components into one logical device")
    out.append(f";   @PDK_SWAP   -- instructs the parser to replace this block with a PDK cell")
    out.append(f";   @KEEP       -- instructs the parser to keep these ideal components as-is")
    out.append(f";   @END_BLOCK  -- closes the block")
    out.append(f"; {'='*68}")
    out.append(f";")

    # Copy Options and sim controller unchanged (marked as SIM_CTRL)
    out.append("; @BLOCK  name=sim_options  type=SIM_CTRL  desc=\"Simulator options\"")
    out.append("Options ResourceUsage=yes UseNutmegFormat=no")
    out.append("; @END_BLOCK name=sim_options")
    out.append(";")
    out.append("; @BLOCK  name=SP1  type=SIM_CTRL  desc=\"S-parameter sweep 2-18 GHz 50 MHz step\"")
    out.append('S_Param:SP1 CalcS=yes CalcY=no CalcZ=no StatusLevel=2 CalcNoise=no \\')
    out.append('SweepVar="freq" SweepPlan="SP1_stim" OutputPlan="SP1_Output"')
    out.append("SweepPlan: SP1_stim Start=2 GHz Stop=18 GHz Step=50 MHz")
    out.append("OutputPlan:SP1_Output \\")
    out.append("      Type=\"Output\" \\")
    out.append("      UseEquationNestLevel=yes \\")
    out.append("      EquationNestLevel=2 \\")
    out.append("      UseSavedEquationNestLevel=yes \\")
    out.append("      SavedEquationNestLevel=2")
    out.append("; @END_BLOCK name=SP1")
    out.append(";")

    # Ports
    out.append("; @BLOCK  name=Term1  type=PORT  desc=\"RF input port P1, 50 Ohm\"")
    out.append("Port:Term1  P1  0  Num=1  Z=50 Ohm")
    out.append("; @END_BLOCK name=Term1")
    out.append(";")
    out.append("; @BLOCK  name=Term2  type=PORT  desc=\"RF output port P2, 50 Ohm\"")
    out.append("Port:Term2  P2  0  Num=2  Z=50 Ohm")
    out.append("; @END_BLOCK name=Term2")
    out.append(";")

    # Input RF pad
    out.append("; @BLOCK  name=PAD_in  type=PASSIVE_NETWORK  desc=\"Input RF bond/probe pad\"")
    out.append(";   @KEEP  components=Rpad_in,Lpad_in,Cpad_in")
    out.append(";   Physical meaning: pad series resistance + inductance, pad capacitance to GND")
    out.append(";   No PDK swap -- pad parasitics are layout-extracted, not a PDK cell")
    out.append("R:Rpad_in   P1   n1   R=0.05 Ohm")
    out.append("L:Lpad_in   n1   n2   L=10 pH")
    out.append("C:Cpad_in   n2   0    C=65 fF")
    out.append("; @END_BLOCK name=PAD_in")
    out.append(";")

    # Input interconnect
    out.append("; @BLOCK  name=INT_in  type=TLINE  desc=\"Input 0.3mm Au interconnect, pi-model\"")
    out.append(";   @KEEP  components=Ci1a,Ri1,Li1,Ci1b")
    out.append(";   Physical meaning: 50-Ohm microstrip, L=120pH C=48fF R=0.009Ohm (0.3mm @ GaAs)")
    out.append(";   Optional PDK swap: PP1029_mlin  Layer=Metal1  W=<width>  L=300 um")
    out.append(";   (keep as pi-model for initial ideal simulation)")
    out.append("C:Ci1a  n2   0    C=24 fF")
    out.append("R:Ri1   n2   n3   R=0.009 Ohm")
    out.append("L:Li1   n3   n4   L=120 pH")
    out.append("C:Ci1b  n4   0    C=24 fF")
    out.append("; @END_BLOCK name=INT_in")
    out.append(";")

    # Stage 1: Series FET Q1a
    out.append("; @BLOCK  name=Q1a  type=TRANSISTOR  desc=\"Stage 1 series pHEMT Q1a, ON state, 160um\"")
    out.append(";   @PDK_SWAP  model=WIN_PP1029_MS  params=\"NOF=2 UGW=80\"")
    out.append(";              port1=n4  port2=n8")
    out.append(";              replaces=Ron_Q1a,Ls_Q1a,Rvia_Q1a,Lvia_Q1a")
    out.append(";              keep=none")
    out.append(";   Note: NOF=2 fingers x UGW=80um = 160um total gate periphery")
    out.append(";   Note: port1=Drain(n4), port2=Source(n8). Gate bias via Cgd_Q1a/Rg_Q1a network.")
    out.append("R:Ron_Q1a   n4   n5   R=2.50 Ohm")
    out.append("L:Ls_Q1a    n5   n6   L=50 pH")
    out.append("R:Rvia_Q1a  n6   n7   R=0.08 Ohm")
    out.append("L:Lvia_Q1a  n7   n8   L=50 pH")
    out.append("; @END_BLOCK name=Q1a")
    out.append(";")

    # Cgd feedback Q1a
    out.append("; @BLOCK  name=GBIAS_Q1a  type=PASSIVE_NETWORK  desc=\"Gate bias + Cgd feedback network Q1a\"")
    out.append(";   @KEEP  components=Cgd_Q1a,Rg_Q1a,Cpg_Q1a,Lsg_Q1a")
    out.append(";   Physical meaning: Cgd(8fF) gate-drain feedback; Rg(300Ohm)||Cpg(12fF) bias isolation;")
    out.append(";                     Lsg(150pH) self-inductance of bias resistor")
    out.append(";   No PDK swap -- these are discrete passives on the bias network")
    out.append("C:Cgd_Q1a   n8   ng1  C=8 fF")
    out.append("R:Rg_Q1a    ng1  ng2  R=300 Ohm")
    out.append("C:Cpg_Q1a   ng1  ng2  C=12 fF")
    out.append("L:Lsg_Q1a   ng2  0    L=150 pH")
    out.append("; @END_BLOCK name=GBIAS_Q1a")
    out.append(";")

    # Shunt FET Q3a
    out.append("; @BLOCK  name=Q3a  type=TRANSISTOR  desc=\"Stage 1 shunt pHEMT Q3a, OFF state (absorptive), 100um\"")
    out.append(";   @PDK_SWAP  model=WIN_PP1029_MS  params=\"NOF=2 UGW=50\"")
    out.append(";              port1=n8  port2=ns2")
    out.append(";              replaces=Coff_Q3a,Lsh_Q3a")
    out.append(";              keep=Rtrm1,Lrt_Q3a")
    out.append(";   Note: NOF=2 fingers x UGW=50um = 100um total gate periphery")
    out.append(";   Note: port1=Drain(n8 RF node), port2=Source(ns2, connects to Rtrm1)")
    out.append(";   Note: Rtrm1 + Lrt_Q3a remain in series after the FET source to GND")
    out.append("C:Coff_Q3a  n8   ns1  C=30 fF")
    out.append("L:Lsh_Q3a   ns1  ns2  L=50 pH")
    out.append("R:Rtrm1     ns2  ns3  R=47 Ohm")
    out.append("L:Lrt_Q3a   ns3  0    L=25 pH")
    out.append("; @END_BLOCK name=Q3a")
    out.append(";")

    # Stage 2: Series FET Q1b
    out.append("; @BLOCK  name=Q1b  type=TRANSISTOR  desc=\"Stage 2 series pHEMT Q1b, ON state, 160um\"")
    out.append(";   @PDK_SWAP  model=WIN_PP1029_MS  params=\"NOF=2 UGW=80\"")
    out.append(";              port1=n8  port2=n12")
    out.append(";              replaces=Ron_Q1b,Ls_Q1b,Rvia_Q1b,Lvia_Q1b")
    out.append(";              keep=none")
    out.append(";   Note: same device as Q1a, second stage for improved isolation")
    out.append("R:Ron_Q1b   n8   n9   R=2.50 Ohm")
    out.append("L:Ls_Q1b    n9   n10  L=50 pH")
    out.append("R:Rvia_Q1b  n10  n11  R=0.08 Ohm")
    out.append("L:Lvia_Q1b  n11  n12  L=50 pH")
    out.append("; @END_BLOCK name=Q1b")
    out.append(";")

    # Cgd feedback Q1b
    out.append("; @BLOCK  name=GBIAS_Q1b  type=PASSIVE_NETWORK  desc=\"Gate bias + Cgd feedback network Q1b\"")
    out.append(";   @KEEP  components=Cgd_Q1b,Rg_Q1b,Cpg_Q1b,Lsg_Q1b")
    out.append("C:Cgd_Q1b   n12  ng3  C=8 fF")
    out.append("R:Rg_Q1b    ng3  ng4  R=300 Ohm")
    out.append("C:Cpg_Q1b   ng3  ng4  C=12 fF")
    out.append("L:Lsg_Q1b   ng4  0    L=150 pH")
    out.append("; @END_BLOCK name=GBIAS_Q1b")
    out.append(";")

    # Shunt FET Q3b
    out.append("; @BLOCK  name=Q3b  type=TRANSISTOR  desc=\"Stage 2 shunt pHEMT Q3b, OFF state (absorptive), 100um\"")
    out.append(";   @PDK_SWAP  model=WIN_PP1029_MS  params=\"NOF=2 UGW=50\"")
    out.append(";              port1=n12  port2=ns5")
    out.append(";              replaces=Coff_Q3b,Lsh_Q3b")
    out.append(";              keep=Rtrm2,Lrt_Q3b")
    out.append("C:Coff_Q3b  n12  ns4  C=30 fF")
    out.append("L:Lsh_Q3b   ns4  ns5  L=50 pH")
    out.append("R:Rtrm2     ns5  ns6  R=47 Ohm")
    out.append("L:Lrt_Q3b   ns6  0    L=25 pH")
    out.append("; @END_BLOCK name=Q3b")
    out.append(";")

    # Output interconnect
    out.append("; @BLOCK  name=INT_out  type=TLINE  desc=\"Output 0.3mm Au interconnect, pi-model\"")
    out.append(";   @KEEP  components=Co1a,Ro1,Lo1,Co1b")
    out.append("C:Co1a  n12  0    C=24 fF")
    out.append("R:Ro1   n12  n13  R=0.009 Ohm")
    out.append("L:Lo1   n13  n14  L=120 pH")
    out.append("C:Co1b  n14  0    C=24 fF")
    out.append("; @END_BLOCK name=INT_out")
    out.append(";")

    # Output RF pad
    out.append("; @BLOCK  name=PAD_out  type=PASSIVE_NETWORK  desc=\"Output RF bond/probe pad\"")
    out.append(";   @KEEP  components=Cpad_out,Lpad_out,Rpad_out")
    out.append("C:Cpad_out  n14  0    C=65 fF")
    out.append("L:Lpad_out  n14  n15  L=10 pH")
    out.append("R:Rpad_out  n15  P2   R=0.05 Ohm")
    out.append("; @END_BLOCK name=PAD_out")

    return "\n".join(out) + "\n"


if __name__ == "__main__":
    inp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spdt_switch.net")
    if not inp.exists():
        print(f"ERROR: {inp} not found"); sys.exit(1)
    out_path = inp.parent / (inp.stem + "_prep.net")
    result = prepare(inp)
    out_path.write_text(result, encoding="utf-8")
    print(f"Written: {out_path}")
    print(result)
