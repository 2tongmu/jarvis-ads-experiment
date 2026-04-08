# ADS Schematic Build Limitations

## Purpose

This skill captures known limitations and risks in the current ADS schematic generation flow so the sub-agent can plan more conservatively.

## Known Limitation 1: Silent Wiring Failures

A logically correct ADS-oriented file can still produce a broken schematic even though Python reports no errors.

ADS places components silently even if wire endpoints don't land on pin snap_points. The schematic looks complete in the GUI but `generate_netlist()` reveals floating nodes.

**Rule:** Always verify connectivity by running the connectivity checker on the generated netlist. Never trust a silent success.

## Known Limitation 2: Poor Placement = Ambiguous Connections

Components that are too close to unrelated symbols or pins may create ambiguous or wrong-looking connections in the ADS GUI, even if the netlist is correct.

## Known Limitation 3: PDK Models Only Resolve in ADS GUI

PDK models (PP1029_CPW_PDK, PP1029_MS_PDK) do not resolve when running standalone hpeesofsim.exe. They only work when simulated from the ADS GUI after building the schematic programmatically.

Do not try to simulate directly from CircuitSimulator with PDK FETs.

## Known Limitation 4: Workspace and Cell Locking

- Deleting cells via API can cause lock errors if ADS GUI had the cell open previously
- Use `shutil.rmtree(cell_dir)` on disk instead of API deletion
- Check `workspace.libraries` before calling `add_library` to avoid duplicate registration errors

## Known Limitation 5: WSL Path Crashes

hpeesofsim.exe crashes if given a `\\wsl.localhost\...` path. Always copy netlists and scripts to a Windows-native path first (e.g., `C:\Users\jarvis\AppData\Local\Temp\`).

## Implication For The Sub-Agent

The sub-agent should treat placement as a safety and readability problem, not just a formatting problem.

## Conservative Planning Rules

Prefer:
- larger spacing between unrelated groups
- clearer lane separation
- more obvious branch structure
- more room near branch points
- cleaner separation between RF and control structures

Avoid:
- tight packing
- arbitrary local placement
- mixing unrelated functions in one crowded region
- assuming the downstream builder will automatically fix bad geometry

## Connectivity Self-Check (Mandatory)

After any schematic build, run:
```
python ~/openclaw/skills/ads-schematic-checker/scripts/check_netlist.py <generated.net>
```

Do not report success until ALL CHECKS PASSED ✅.

## Practical Summary

When uncertain, choose the placement rule that makes the schematic easier to inspect and less likely to hide a connection mistake.
