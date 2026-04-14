"""
ads_api/symbol_ops.py
=====================
Create symbol views for ADS schematic cells.

The symbol is a blackbox representation of the cell — a rectangle with port
pins placed on its left/right edges. It is what appears when the cell is
instantiated inside a parent schematic.

Port placement strategy (confirmed from ads_bias_subcell_create.py):
  - All pin figures placed at x=0.0 (left edge of symbol)
  - Pins spaced 2.0 units apart vertically
  - Stack centered around y=0.0

For two-port cells:
  Port 1 (input):  (0.0, +1.0)
  Port 2 (output): (0.0, -1.0)

For three-port cells (Phase 3):
  Port 1: (0.0, +2.0)
  Port 2: (0.0,  0.0)
  Port 3: (0.0, -2.0)

API status notes (sourced from ADS_API_REFERENCE.md §7):
  cell_ops.open_or_create_symbol()          — see cell_ops.py (all calls confirmed)
  list(schematic_design.terms)              ✅ CONFIRMED
  sym_design.add_pin_fig_for_term_type()    ✅ CONFIRMED (symbol view only)
  sym_design.save_design()                  ✅ CONFIRMED

Important:
  add_pin_fig_for_term_type() is confirmed ONLY for the symbol design.
  Do not call it on the schematic design — it will not produce visible pins there.
  Schematic-side pin graphics (add_dot_for_pin + add_pin) are ⚠️ UNCONFIRMED (§12).

Usage:
    from ads_api.symbol_ops import create_basic_symbol

    # After schematic is built and saved:
    create_basic_symbol(session, lib, lib_name, cell, cell_name, schematic_design)
"""

from ads_api.ads_session import ADSSession
from ads_api.cell_ops import open_or_create_symbol, save_design


def create_basic_symbol(
    session: ADSSession,
    lib,
    lib_name: str,
    cell,
    cell_name: str,
    schematic_design,
) -> None:
    """
    Generate a blackbox symbol view from the schematic's terminal list.

    Reads terms from the schematic design, places one pin figure per term
    on the symbol, and saves. Must be called AFTER schematic_design.save_design()
    so the term list is complete and stable.

    Port ordering: preserves the order returned by list(design.terms).
    This matches the term creation order in schematic_ops.place_port(),
    which processes ports in ascending port number order.

    Layout:
      - All pin figures at x = 0.0
      - Spaced 2.0 units apart vertically
      - Stack centered at y = 0.0

    Args:
        session           : ADSSession
        lib               : library object (used implicitly through cell)
        lib_name          : library name string (required for db.create_symbol tuple)
        cell              : cell object
        cell_name         : cell name string
        schematic_design  : the saved schematic design — provides the term list

    Raises:
        RuntimeError : if schematic has no terms (symbol would be empty)

    API status:
        list(schematic_design.terms)                    ✅ CONFIRMED
        sym_design.add_pin_fig_for_term_type(t, pos)   ✅ CONFIRMED (symbol only)
        sym_design.save_design()                        ✅ CONFIRMED
    """
    # ── Read terms from saved schematic ───────────────────────────────────────
    sch_terms = list(schematic_design.terms)   # ✅ CONFIRMED

    if not sch_terms:
        raise RuntimeError(
            f"Schematic '{cell_name}' has no terms — cannot generate symbol.\n"
            "Ensure place_port() was called for each port before save_design()."
        )

    print(f"[symbol] {len(sch_terms)} terms: {[t.name for t in sch_terms]}")

    # ── Create fresh symbol view ───────────────────────────────────────────────
    sym_design = open_or_create_symbol(session, lib_name, cell, cell_name)

    # ── Place one pin figure per term ─────────────────────────────────────────
    # Stack vertically at x=0, centered around y=0, 2.0 units spacing.
    y_spacing = 2.0
    y_start   = (len(sch_terms) - 1) * y_spacing / 2.0   # centre the stack

    for idx, term in enumerate(sch_terms):
        y_pos = y_start - (idx * y_spacing)
        sym_design.add_pin_fig_for_term_type(   # ✅ CONFIRMED (symbol view only)
            term.term_type,
            (0.0, y_pos),
        )
        print(f"[symbol] pin '{term.name}' at (0.0, {y_pos})")

    # ── Save symbol ───────────────────────────────────────────────────────────
    save_design(sym_design)   # ✅ CONFIRMED
    print(f"[symbol] saved: {lib_name}:{cell_name}:symbol")
