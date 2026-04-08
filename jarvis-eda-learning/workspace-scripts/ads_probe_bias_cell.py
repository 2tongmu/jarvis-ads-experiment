"""
ads_probe_bias_cell.py
Probe cell_fetbias_switch_gate to extract ADS API ground truth.
Run on Jarvis: "C:/Program Files/Keysight/ADS2026_Update1/tools/python/python.exe" workspace-scripts/ads_probe_bias_cell.py
"""

import sys
from pathlib import Path

ADS_DIR = Path("C:/Program Files/Keysight/ADS2026_Update1")
sys.path.insert(0, str(ADS_DIR / "tools" / "python" / "packages"))

import keysight.ads.de as de
from keysight.ads.de import db_uu as db

WORKSPACE = "C:/Users/jarvis/ads_projects/spdt_switch_pdk_wrk"
LIBRARY   = "spdt_switch_pdk_wrk"
CELL      = "cell_fetbias_switch_gate"
VIEW      = "schematic"

def probe():
    print("=== Opening workspace ===")
    ws = de.open_workspace(WORKSPACE)
    print(f"  workspace: {ws}")

    print("\n=== Opening schematic ===")
    lcv = de.LCVName(LIBRARY, CELL, VIEW)
    print(f"  LCVName: {lcv}")
    sch = db.open_schematic(lcv)
    print(f"  schematic object: {sch}")
    print(f"  type: {type(sch)}")

    print("\n=== Design variables ===")
    try:
        dvars = sch.cell.design_variables()
        print(f"  raw return: {dvars}")
        print(f"  type: {type(dvars)}")
        for v in dvars:
            print(f"    {v}")
    except Exception as e:
        print(f"  design_variables() failed: {e}")

    try:
        dvars2 = sch.cell.read_design_variables()
        print(f"  read_design_variables: {dvars2}")
    except Exception as e:
        print(f"  read_design_variables() failed: {e}")

    print("\n=== All instances ===")
    instances = sch.instances()
    print(f"  count: {len(instances)}")
    for i, inst in enumerate(instances):
        print(f"\n  [{i}] instance: {inst}")
        print(f"      type:      {type(inst)}")
        try:
            print(f"      name:      {inst.name}")
        except Exception as e:
            print(f"      name:      ERROR {e}")
        try:
            print(f"      cell_name: {inst.cell_name}")
        except Exception as e:
            print(f"      cell_name: ERROR {e}")
        try:
            print(f"      lib_name:  {inst.lib_name}")
        except Exception as e:
            print(f"      lib_name:  ERROR {e}")
        try:
            params = inst.parameters()
            print(f"      parameters: {params}")
            for p in params:
                print(f"        param: {p}  type={type(p)}")
                try:
                    print(f"          .name={p.name}  .value={p.value}  .units={p.units}")
                except Exception as e:
                    print(f"          detail error: {e}")
        except Exception as e:
            print(f"      parameters(): ERROR {e}")
        try:
            pos = inst.position()
            print(f"      position:  {pos}")
        except Exception as e:
            print(f"      position:  ERROR {e}")
        try:
            print(f"      rotation:  {inst.rotation()}")
        except Exception as e:
            print(f"      rotation:  ERROR {e}")

    print("\n=== All nets ===")
    try:
        nets = sch.nets()
        print(f"  count: {len(nets)}")
        for n in nets:
            print(f"    net: {n}  name={getattr(n, 'name', '?')}")
    except Exception as e:
        print(f"  nets() failed: {e}")

    print("\n=== All pins ===")
    try:
        pins = sch.pins()
        print(f"  count: {len(pins)}")
        for p in pins:
            print(f"    pin: {p}")
            try:
                print(f"      name={p.name}  position={p.position()}  rotation={p.rotation()}")
            except Exception as e:
                print(f"      detail error: {e}")
    except Exception as e:
        print(f"  pins() failed: {e}")

    print("\n=== Coordinate scaling check ===")
    try:
        instances = sch.instances()
        if instances:
            pos = instances[0].position()
            print(f"  first instance position raw: {pos}")
            print(f"  (compare to ADS GUI coordinates to determine MILS_PER_UNIT)")
    except Exception as e:
        print(f"  ERROR: {e}")

    print("\n=== Done ===")

if __name__ == "__main__":
    probe()
