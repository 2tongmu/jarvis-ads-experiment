# Review Example Net Flow

## Purpose

This workflow teaches the sub-agent how to review the provided example files before generating a placement plan.

## Files To Review

- `input/spdt_switch.net`
- `input/spdt_switch_prep.net`
- `input/spdt_switch_ads_import.net`

## Workflow

### Step 1
Read `spdt_switch.net` and understand the original circuit intent.

### Step 2
Read `spdt_switch_prep.net` and understand functional grouping and replacement intent.

### Step 3
Read `spdt_switch_ads_import.net` and identify the PDK-specific logical implementation.

### Step 4
Compare the three files and trace how the intended circuit meaning is preserved.

### Step 5
Extract placement-relevant structure from the ADS-oriented file:
- main RF path
- branch paths
- control or bias structures
- shunt or support structures
- simulation objects

### Step 6
Write a concise review summary before generating the placement plan.

## Output From This Workflow

The sub-agent should be able to summarize:
- role of each file
- main RF backbone
- branch structure
- control/support structure
- likely placement risks

## Rule

Do not redesign the circuit during review.

Understand first, then plan placement.