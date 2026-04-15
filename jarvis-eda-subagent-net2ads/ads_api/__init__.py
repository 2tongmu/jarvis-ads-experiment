# ads_api package
# ADS automation layer for net2ads (passive R/L/C cells; extensible to Phase 2+).
#
# Public API:
#   ads_session   : get_ads_session(), is_ads_available()
#   workspace_ops : open_workspace(), create_workspace(), ensure_library()
#   cell_ops      : get_or_create_cell(), open_or_create_schematic(), save_design()
#   schematic_ops : place_instance()          ← generic dispatch (use this)
#                   place_port(), place_ground()
#                   place_resistor(), place_capacitor(), place_inductor()
#                   place_subcircuit()        ← for sub-circuit instantiation
#                   connect(), set_design_variables()
#   symbol_ops    : create_basic_symbol(), create_dual_symbol()
#
# Extension points:
#   New component types → add handler to _PASSIVE_PLACER_REGISTRY in schematic_ops.py
