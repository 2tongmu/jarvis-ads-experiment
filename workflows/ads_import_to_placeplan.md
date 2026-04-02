# ADS Import to Placeplan

## Purpose

This workflow teaches the sub-agent how to convert an ADS-oriented logical implementation into a structured placement plan.

## Input

Primary input:
- `input/spdt_switch_ads_import.net`

Supporting inputs:
- `input/spdt_switch.net`
- `input/spdt_switch_prep.net`
- `schemas/placeplan_schema.md`

## Output

Primary output:
- `input/spdt_switch_placeplan.yaml`

Companion review output:
- `notes/spdt_switch_placeplan_review.md`

## Workflow Steps

### Step 1: Use the ADS-oriented file as logical source
Treat `spdt_switch_ads_import.net` as the logical source of truth for placement planning.

### Step 2: Identify the main RF backbone
Determine the main signal path, branch points, and branch destinations.

### Step 3: Identify non-RF structures
Identify:
- control or bias structures
- shunt or return structures
- simulation-related objects

### Step 4: Create functional groups
Create placement-relevant groups such as:
- input group
- switch core group
- upper branch group
- lower branch group
- gate-bias groups
- shunt/ground-support group
- simulation group

### Step 5: Assign lanes
Assign groups to schematic lanes such as:
- RF main
- control/bias
- shunt/ground
- simulation

### Step 6: Define ordering constraints
Preserve readable signal flow, usually left-to-right for RF.

### Step 7: Define spacing guidance
Use conservative spacing to reduce ambiguous proximity, especially between unrelated groups and near branch points.

### Step 8: Define routing guidance
Favor clear routing channels and separation between RF and control structures.

### Step 9: Define anchor elements
Identify which groups should be placed first by a deterministic ADS builder.

### Step 10: Write outputs
Create:
- `notes/spdt_switch_placeplan_review.md`
- `input/spdt_switch_placeplan.yaml`

## Rule

Do not modify the existing `.net` files.

Generate new outputs only.

## Success Criteria

A good placeplan should:
- preserve logical meaning
- make the RF path clear
- separate control and support structures
- reduce accidental connection risk
- be structured enough for deterministic ADS build scripts to consume