# ads_api package
# Minimal ADS automation layer for net2ads Phase 1 (passive R/L/C cells).
#
# Public API:
#   ads_session   : get_ads_session(), is_ads_available()
#   workspace_ops : open_workspace(), create_workspace(), ensure_library()
#   cell_ops      : get_or_create_cell(), open_or_create_schematic(), save_design()
#   schematic_ops : place_port(), place_ground(), place_resistor(),
#                   place_capacitor(), place_inductor(), connect(), set_design_variables()
#   symbol_ops    : create_basic_symbol()
