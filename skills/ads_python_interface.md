# ADS Python Interface

## Purpose

This skill records how the sub-agent should think about the ADS Python interface and provides confirmed placement geometry rules for ADS 2026.

## Role of the Sub-Agent

The sub-agent should assume that ADS can be driven through Python-based automation, but the sub-agent itself is not the final execution engine.

Its output should be structured so that a deterministic Python builder can consume it reliably.

## What The Sub-Agent Should Produce

The sub-agent should produce information that is useful for Python-based schematic generation, such as:

- functional groups
- placement lanes
- ordering constraints
- spacing rules
- routing preferences
- anchor elements
- validation expectations

## Confirmed ADS Component Pin Geometry (ADS 2026)

These are verified rules. The builder must follow them exactly — ADS silently ignores wires that miss pin snap_points by even a fraction of a unit.

### R and L (series, angle=0)
- Instance placed at midpoint (cx, cy)
- P1 = (cx - 0.5, cy)  ← left pin
- P2 = (cx + 0.5, cy)  ← right pin
- Wire must land exactly on P1 or P2

### C (shunt, angle=-90)
- Instance placed at tap point (x, y)
- P1 = (x, y)     ← RF pin (on signal line)
- P2 = (x, y-1)   ← GND pin (hangs downward)

### Term (port, angle=-90)
- RF pin at instance origin (x, y)
- GND pin at (x, y-1)
- **Always add a companion GROUND instance at (x, y-1)**

### GROUND (angle=-90)
- Single pin at instance origin (x, y)
- Place at the GND pin location of the component it terminates

### WIN_PP1029_CPW (PDK FET, 3-port) — CONFIRMED pin layout
```
bbox: (0, -0.5) to (0.68125, 0.5)
P1 = Gate   snap (0.0,  0.0)   left pin
P2 = Drain  snap (0.5, +0.5)   top pin
P3 = Source snap (0.5, -0.5)   bottom pin
Netlist port order: gate  drain  source
```

**Series FET (angle=90):** rotate 90° CCW
- Instance origin at (drain_x + 0.5, y - 0.5)
- Drain  = (drain_x,       y)      ← left on signal line
- Source = (drain_x + 1.0, y)      ← right on signal line
- Gate   = (drain_x + 0.5, y - 0.5) ← below signal line

**Shunt FET (angle=0):** no rotation
- Instance origin at (rf_x - 0.5, y - 0.5)
- Drain  = (rf_x,       y)       ← top, on signal line
- Source = (rf_x,       y - 1.0) ← bottom, hangs down
- Gate   = (rf_x - 0.5, y - 0.5) ← left of shunt column

## Critical Wiring Rule

Wire endpoints must EXACTLY match component pin snap_point coordinates.
A 0.01 unit error = open circuit. No rounding, no approximation.

## Common Failure Modes

| Symptom | Root cause |
|---|---|
| Term1 node appears in only 1 component | Wire from Term1 to first series R is missing or at wrong x |
| Rtrm → Lrt_Q3a gap | Explicit wire() call missing between R P2 and L P1 in shunt chain |
| FET drain/source floating | CPW instance origin wrong; drain_x offset error |
| Co1a on wrong node | Placed before Q1b source instead of after |
| All FET pins short to GND | angle= wrong; P1/P2 offsets inverted |

## Interface Principle

The placement plan should be:
- structured
- explicit
- deterministic-script-friendly
- easy to validate before ADS execution

## Practical Summary

Think of the ADS Python layer as a downstream consumer.

The sub-agent should provide clean placement intent, not fragile implementation improvisation.
