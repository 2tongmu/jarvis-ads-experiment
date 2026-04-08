# ADS Schematic Placement

## Purpose

This skill teaches the agent how to convert a logical ADS-oriented netlist into a schematic placement plan that is readable, conservative, and safe for deterministic ADS schematic generation.

This skill does not redesign the circuit.

This skill does not replace PDK mapping.

This skill does not directly verify RF performance.

Its purpose is to bridge the gap between:

- a logically correct netlist
- a clearer and safer ADS schematic

## When To Use This Skill

Use this skill when:

- a `.net` file already describes the intended circuit connectivity
- an ADS-oriented netlist exists or can be derived
- the schematic builder needs guidance on placement
- current ADS builds suffer from poor placement, crowded symbols, or ambiguous-looking wiring
- the design contains branches, shunt elements, or separate control/bias structures that need visual organization

Do not use this skill to invent a new circuit.

Do not use this skill to change the electrical meaning of the netlist.

## Inputs

Primary inputs:
- `workspace-netlists/*.net`
- especially `*_ads_import.net` when available

Optional supporting inputs:
- corresponding raw `.net`
- corresponding `_prep.net`
- placeplan template files
- PDK-aware implementation notes
- results from previous ADS schematic builds

## Outputs

Primary output:
- `*_placeplan.yaml`

Optional supporting output:
- review note summarizing:
  - main RF backbone
  - branch paths
  - control or bias structures
  - placement risks
  - assumptions and open questions

## Core Principles

### 1. Preserve logical meaning
The placement plan must not change intended connectivity or circuit behavior.

### 2. Separate logic from geometry
The netlist defines what is connected.
The placeplan defines how the schematic should be arranged.

### 3. Readability is a design goal
A good schematic should make the main RF path easy to follow.

### 4. Functional separation matters
RF path, control path, shunt path, and simulation objects should not be mixed arbitrarily.

### 5. Conservative spacing is preferred
Avoid crowded placement, especially near branch points and unrelated pins.

### 6. Deterministic structure beats ad hoc coordinates
The agent should define:
- groups
- lanes
- ordering
- spacing
- anchor elements

A deterministic script should convert that into coordinates.

## Placement Model

The placement model has two layers:

### Layer A: topological understanding
From the netlist, identify:
- ports
- main RF backbone
- branch points
- branch arms
- control or bias elements
- shunt or return elements
- simulation objects

### Layer B: schematic organization
From that understanding, define:
- functional groups
- lanes
- ordering constraints
- spacing rules
- routing preferences
- anchor elements

## Standard Placement Heuristics

### RF backbone
Place the main RF path in a primary lane, usually left to right.

### Branches
When the RF path splits, make the fork visually obvious and separate the branches clearly.

### Control and bias
Keep control or bias structures in a separate lane, usually above the RF lane.

### Shunt and ground-support structures
Keep shunt or return structures in a separate lane, usually below the RF lane.

### Simulation objects
Keep simulation controllers and measurement objects detached from the main circuit body.

## Main Workflow

### Step 1
Read the ADS-oriented netlist and identify components and nets.

### Step 2
Build a connectivity graph.

### Step 3
Identify the main RF backbone from the ports and connectivity.

### Step 4
Identify branch paths and support structures.

### Step 5
Group components into placement-relevant functional groups.

### Step 6
Assign each group to a lane.

### Step 7
Define ordering constraints, spacing guidance, and routing guidance.

### Step 8
Write a structured placeplan.

### Step 9
Hand the placeplan to deterministic scripts for coordinate generation and ADS build.

## What Good Output Looks Like

A good placeplan should:
- preserve the netlist’s intended meaning
- show a clear RF backbone
- separate branch arms clearly
- separate control and support elements from RF path elements
- provide enough spacing to reduce ambiguity
- be stable enough for deterministic ADS build scripts

## What Bad Output Looks Like

Bad placement planning includes:
- random coordinates with no grouping logic
- crowded unrelated components
- mixed RF and bias structures
- unclear branch geometry
- silent reinterpretation of the circuit
- compactness prioritized above clarity

## Known Failure Modes

### Failure 1: unrelated components placed too close
This can create ambiguous-looking or wrong-looking connections.

### Failure 2: branch points not visually clear
This makes the schematic hard to review and wire safely.

### Failure 3: control and RF lanes mixed
This reduces readability and increases routing confusion.

### Failure 4: direct coordinate generation without structure
This produces brittle and hard-to-maintain placement.

## Practical Rules For The Agent

When using this skill:

- start from the existing netlist
- do not redesign the circuit
- identify the main RF path first
- group by function
- use lanes
- prefer conservative spacing
- explain uncertainty instead of hiding it
- make output easy for scripts to consume

## Expected Script Cooperation

This skill assumes downstream scripts will:

- parse the netlist
- generate or refine a placeplan
- assign exact coordinates from the placeplan
- build the ADS schematic using Python
- later validate connectivity

This skill should not try to collapse all of that into a single opaque step.

## Repository Conventions

Use the following repo structure:

- netlists live in `workspace-netlists/`
- experiment scripts live in `workspace-scripts/`
- placement skill lives in `skills/ads-schematic-placement/`

Example files:
- `workspace-netlists/spdt_switch.net`
- `workspace-netlists/spdt_switch_prep.net`
- `workspace-netlists/spdt_switch_ads_import.net`
- `workspace-scripts/ads_placeplan_generate.py`
- `workspace-scripts/ads_placeplan_to_ads.py`

## Summary

Use this skill to transform a logical circuit description into a structured schematic placement plan.

The main goal is better ADS schematic generation quality through:
- clearer RF flow
- better function separation
- safer spacing
- deterministic placement logic