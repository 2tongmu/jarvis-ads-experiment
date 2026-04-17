# JARVIS_PDK_TASKS.md
# PDK post-processing tasks for Jarvis
#
# Context
# -------
# build_pdk_yaml.py auto-generates _core.yaml and _reference.yaml for any PDK
# in ads_pdk/ by probing the ADS Python API. It handles all data extraction
# that can be read programmatically (cell enumeration, parameter names,
# pin snap_points, netlist_model names, component classification).
#
# The tasks below require domain reasoning that a data extraction script cannot
# do. These are one-time per PDK. Complete them by editing the generated
# _core.yaml in ads_pdk/pdk_configs/ directly.
#
# How to hand over
# ----------------
# 1. Run build_pdk_yaml.py for the new PDK (see usage in script header)
# 2. Open the generated _core.yaml and _reference.yaml
# 3. Ask Jarvis to complete the tasks below, providing both files as context
# 4. Reference WIN_PP1029_core.yaml as the target format example

---

## Task 1 — Verify semantic pin names

build_pdk_yaml.py probes pin names from the ADS API (it.term.name). For some
PDKs the API returns generic names (p1, p2, p3) instead of semantic names
(gate, drain, source). Jarvis should:

- For each cell in component_map: confirm whether the pin_names list is correct
- If generic (p1/p2/p3): identify the real names from PDK documentation or
  AEL description strings in circuit/ael/*.atf
- Update pin_names in both component_map entries AND pin_offsets section
- Update the pin offset entry labels (e.g. pin1_gate, pin2_drain, pin3_source)

Priority: TRANSISTOR_SWITCH cells first (gate/drain/source naming matters for
placement engine wiring). 2-pin passives (p1/p2) are usually correct as-is.

---

## Task 2 — Add port_mapping for signal-path components

For each component in component_map, add a port_mapping block that declares
which physical pin maps to which circuit port role:

  port_mapping:
    port1: drain    # RF signal in
    port2: source   # RF signal out
    port3: gate     # DC bias / control

Rules:
- For TRANSISTOR_SWITCH (FET): drain and source are the RF ports; gate is control
- For TRANSISTOR_SWITCH (BJT/HBT): collector and emitter are RF ports; base is control
- For TRANSISTOR_AMPLIFIER (2-pin, source pre-grounded): port1=drain, port2=gate
- For RESISTOR/CAPACITOR/INDUCTOR (2-pin): port1=p1, port2=p2

Reference: WIN_PP1029_core.yaml component_map entries for confirmed examples.

---

## Task 3 — Add notes for key components

For each TRANSISTOR_SWITCH and TRANSISTOR_AMPLIFIER entry in component_map,
add a notes field documenting:

- Intended use case (series switch, shunt switch, LNA input, PA driver, etc.)
- Known constraints (max gate width, validated finger count range, etc.)
- What NOT to use this cell for (e.g. source-grounded cells for switching)
- Any PDK-specific quirks (pre-grounded pins, internal feedback elements, etc.)

Format (multiline YAML string):
  notes: >
    Use for series switch FETs (signal flows drain to source).
    Do NOT use PP156X_MS — source is pre-grounded internally.
    Gate bias network must be added separately.

---

## Task 4 — Add typical_params for common use cases

For TRANSISTOR_SWITCH cells, add a typical_params block with recommended
parameter values for each use role:

  typical_params:
    series_switch: {NOF: 2, UGW: "80 um"}
    shunt_switch:  {NOF: 2, UGW: "50 um"}

Values should reflect standard practice for the process node. If unsure,
leave a comment with the parameter range from the PDK datasheet.

---

## Task 5 — Review PASSIVE_PDK entries

build_pdk_yaml.py classifies unrecognised 2-3 pin cells as PASSIVE_PDK.
Jarvis should review each and refine:

- Diodes (Schottky, PIN, varactor) → update rfscikit_type to DIODE
- Baluns / hybrids → PASSIVE_EM_BALUN
- EM-simulated structures → PASSIVE_EM
- Anything that should be in a different category

Current PASSIVE_PDK cells to review (update after running build_pdk_yaml.py):
  (populated automatically from _reference.yaml PASSIVE_PDK section)

---

## Status tracking (fill in after each task)

| PDK | Task 1 pin names | Task 2 port_mapping | Task 3 notes | Task 4 typical_params | Task 5 PASSIVE_PDK review |
|---|---|---|---|---|---|
| WIN_PP1029_DESIGN_KIT | DONE (Jarvis, 2026-04-06) | DONE | DONE | DONE | DONE |
| WIN_PP15_6X_DESIGN_KIT | DONE (net2ads sub-agent, 2026-04-16) | DONE (44/44 entries) | DONE (44/44 entries) | DONE (16 TRANSISTOR_SWITCH + 3 AMPLIFIER entries) | DONE (reclassified 15 passive cells, refined all categories) |
