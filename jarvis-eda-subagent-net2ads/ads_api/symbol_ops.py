"""
ads_api/symbol_ops.py
=====================
Create symbol views for ADS schematic cells.

Two symbol creation functions:
  create_basic_symbol  — all pins on the left edge (legacy / single-side)
  create_dual_symbol   — pins split left/right based on schematic port angles;
                         draws a body matching ADS manual dual-symbol style;
                         preferred for two-port RF cells

Dual symbol layout (for create_dual_symbol):
  Left-side ports  (schematic angle=180): x=0.0, facing outward left
  Right-side ports (schematic angle=0):   x=symbol_width, facing outward right
  Pin Y spacing: 2.0 units; stack centered at y=0.

  Body shapes (layer 231 — matches ADS manual symbol generator):
    - Outer rectangle: body_margin to symbol_width-body_margin, ±half_h
    - Inner rectangle: inset by 0.025 on all sides
    - Port stubs: short lines from body edge to each pin dot
    - Port name text: layer 237/244, inside body edge near each pin

API status notes:
  list(schematic_design.terms)                    CONFIRMED
  sym_design.add_pin_fig_for_term_type(t, pos)   CONFIRMED (symbol view only)
  LayerId(231) from keysight.ads.de.db_uu        CONFIRMED locally 2026-04-14
  sym_design.add_rectangle(layer_id, ll, ur)     CONFIRMED locally 2026-04-14
  sym_design.add_line(layer_id, points)          CONFIRMED locally 2026-04-14
  sym_design.add_text(layer_id, text, origin...) CONFIRMED locally 2026-04-14
  sym_design.save_design()                       CONFIRMED
  add_dot_for_pin + add_pin on sym_design        CONFIRMED locally 2026-04-14 (use sym-side terms)

Usage:
    from ads_api.symbol_ops import create_dual_symbol

    port_angles = {"P1": 180.0, "P2": 0.0}
    create_dual_symbol(session, lib, lib_name, cell, cell_name, design, port_angles)
"""

from ads_api.ads_session import ADSSession
from ads_api.cell_ops import open_or_create_symbol, save_design, commit_design


# ── Layer constants (confirmed 2026-04-14 on ADS2026_Update1.2) ───────────────
# Imported lazily inside functions to avoid import-time ADS dependency.
def _layer_body():
    from keysight.ads.de.db_uu import LayerId
    return LayerId(231)          # symbol body shapes and port stubs

def _layer_text():
    from keysight.ads.de.db_uu import LayerId
    return LayerId(237, 244)     # symbol port name annotation text


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
        list(schematic_design.terms)                    CONFIRMED
        sym_design.add_pin_fig_for_term_type(t, pos)   CONFIRMED (symbol only)
        sym_design.save_design()                        CONFIRMED
    """
    # ── Read terms from saved schematic ───────────────────────────────────────
    sch_terms = list(schematic_design.terms)

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
    y_start   = (len(sch_terms) - 1) * y_spacing / 2.0

    for idx, term in enumerate(sch_terms):
        y_pos = y_start - (idx * y_spacing)
        sym_design.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))
        print(f"[symbol] pin '{term.name}' at (0.0, {y_pos})")

    # ── Save symbol ───────────────────────────────────────────────────────────
    # Commit transaction to finalize symbol design in OpenAccess (same pattern as schematic)
    commit_design(session, sym_design)
    save_design(sym_design)
    print(f"[symbol] saved: {lib_name}:{cell_name}:symbol")


# ──────────────────────────────────────────────────────────────────────────────
# Dual symbol (preferred for two-port RF cells)
# ──────────────────────────────────────────────────────────────────────────────

def create_dual_symbol(
    session: ADSSession,
    lib,
    lib_name: str,
    cell,
    cell_name: str,
    schematic_design,
    port_angles: dict,
    symbol_width: float = 2.0,
) -> None:
    """
    Generate a dual (two-sided) symbol view matching ADS manual dual-symbol style.

    Reads terms from the saved schematic design and splits them into left-side
    (schematic angle ~180 deg) and right-side (schematic angle ~0 deg) groups.

    Body uses layer 231 (ADS symbol layer), matching the output of the ADS GUI
    manual symbol generator with Dual type selected:
      - Outer rectangle spanning the body region
      - Inner rectangle inset by 0.025 units
      - Short stub lines from body edge to each pin dot
      - Port name text labels just inside the body edge (layer 237/244)

    Args:
        session          : ADSSession
        lib              : library object
        lib_name         : library name string
        cell             : cell object
        cell_name        : cell name string
        schematic_design : saved schematic design — provides the term list
        port_angles      : dict mapping term name to schematic angle (degrees)
                           e.g. {"P1": 180.0, "P2": 0.0}
        symbol_width     : horizontal distance between left and right pin dots
                           (default 2.0 schematic units)

    Pin placement:
        Left  (angle~180): x=0.0,          y stacked top to bottom, centered at 0
        Right (angle~0):   x=symbol_width, y stacked top to bottom, centered at 0
        Y spacing: 2.0 units between consecutive pins on the same side.

    Body layout (all on layer 231):
        body_margin = symbol_width * 0.25  (stub length from pin to body edge)
        bx0 = body_margin
        bx1 = symbol_width - body_margin
        Outer rect: (bx0, -half_h) to (bx1, +half_h)
        Inner rect: inset 0.025 on each side
        Stubs: (bx0, y) to (0.0, y) for left pins
               (bx1, y) to (symbol_width, y) for right pins

    API status:
        LayerId(231) from keysight.ads.de.db_uu        CONFIRMED 2026-04-14
        LayerId(237, 244) for text layer               CONFIRMED 2026-04-14
        sym_design.add_rectangle(layer_id, ll, ur)     CONFIRMED 2026-04-14
        sym_design.add_line(layer_id, points)          CONFIRMED 2026-04-14
        sym_design.add_text(layer_id, ...)             CONFIRMED 2026-04-14
        sym_design.add_dot_for_pin((x, y))             CONFIRMED 2026-04-14
        sym_design.add_pin(sym_term, dot, angle, ...)  CONFIRMED 2026-04-14
        sym_design.find_or_add_net / add_term          CONFIRMED 2026-04-14
        list(schematic_design.terms)                   CONFIRMED
        sym_design.save_design()                       CONFIRMED

    Raises:
        RuntimeError : if schematic has no terms
    """
    sch_terms = list(schematic_design.terms)
    if not sch_terms:
        raise RuntimeError(
            f"Schematic '{cell_name}' has no terms — cannot generate symbol."
        )

    print(f"[symbol] {len(sch_terms)} terms: {[t.name for t in sch_terms]}")

    # ── Split terms by side based on port_angles ───────────────────────────────
    left_terms  = [t for t in sch_terms
                   if abs(port_angles.get(t.name, 0.0) - 180.0) < 1.0]
    right_terms = [t for t in sch_terms
                   if abs(port_angles.get(t.name, 0.0)) < 1.0]
    other_terms = [t for t in sch_terms
                   if t not in left_terms and t not in right_terms]
    left_terms += other_terms   # unclassified go left as fallback

    n_left  = len(left_terms)
    n_right = len(right_terms)
    n_max   = max(n_left, n_right, 1)
    half_h  = n_max * 1.0      # body half-height: 1.0 unit per port row

    print(f"[symbol] left pins : {[t.name for t in left_terms]}")
    print(f"[symbol] right pins: {[t.name for t in right_terms]}")

    # ── Create fresh symbol view ───────────────────────────────────────────────
    sym_design = open_or_create_symbol(session, lib_name, cell, cell_name)

    # ── Layer handles ──────────────────────────────────────────────────────────
    LAYER_BODY = _layer_body()   # LayerId(231)
    LAYER_TEXT = _layer_text()   # LayerId(237, 244)

    # ── Body layout constants ──────────────────────────────────────────────────
    body_margin  = symbol_width * 0.25   # stub length / pin-to-body-edge distance
    inner_inset  = 0.025                 # inner rect inset (matches ADS default)
    text_height  = 0.069                 # port label height (matches ADS default)
    bx0 = body_margin                    # body left  edge x
    bx1 = symbol_width - body_margin     # body right edge x

    # ── Outer rectangle ────────────────────────────────────────────────────────
    try:
        sym_design.add_rectangle(LAYER_BODY, (bx0, -half_h), (bx1, half_h))
        print(f"[symbol] outer rect ({bx0},{-half_h}) to ({bx1},{half_h})")
    except Exception as exc:
        print(f"[symbol] outer rect skipped: {exc}")

    # ── Inner rectangle ────────────────────────────────────────────────────────
    try:
        sym_design.add_rectangle(
            LAYER_BODY,
            (bx0 + inner_inset, -half_h + inner_inset),
            (bx1 - inner_inset,  half_h - inner_inset),
        )
        print(f"[symbol] inner rect drawn")
    except Exception as exc:
        print(f"[symbol] inner rect skipped: {exc}")

    # ── Import TextAlignment for text labels ───────────────────────────────────
    try:
        from keysight.ads.de._pde.db import TextAlignment
        _align_left  = TextAlignment.CENTER_LEFT   # text extends right from origin
        _align_right = TextAlignment.CENTER_RIGHT  # text extends left  from origin
        _has_text = True
    except Exception:
        _has_text = False

    # ── Get or create symbol-side terms (add_pin needs same-block term) ────────
    sym_term_map = {t.name: t for t in list(sym_design.terms)}

    def _get_sym_term(sch_term):
        if sch_term.name in sym_term_map:
            return sym_term_map[sch_term.name]
        net  = sym_design.find_or_add_net(sch_term.name)
        term = sym_design.add_term(net, sch_term.name, sch_term.term_type)
        sym_term_map[sch_term.name] = term
        return term

    def _place_pin(sch_term, x, y, angle):
        sym_term = _get_sym_term(sch_term)
        try:
            dot = sym_design.add_dot_for_pin((x, y))
            sym_design.add_pin(sym_term, dot, angle=angle, add_annot=True)
        except Exception as exc:
            print(f"[symbol]   add_pin failed ({exc}), using add_pin_fig_for_term_type")
            sym_design.add_pin_fig_for_term_type(sch_term.term_type, (x, y))

    # ── Left-side pins: stub + text label + pin dot ───────────────────────────
    y_start = (n_left - 1) * 2.0 / 2.0
    for idx, term in enumerate(left_terms):
        y = y_start - idx * 2.0
        # Port stub: body left edge → pin dot
        try:
            sym_design.add_line(LAYER_BODY, [(bx0, y), (0.0, y)])
        except Exception as exc:
            print(f"[symbol]   left stub failed: {exc}")
        # Port name text: just inside left body edge, extending right
        if _has_text:
            try:
                sym_design.add_text(
                    LAYER_TEXT, term.name,
                    origin=(bx0 + inner_inset, y),
                    font_name="Roboto",
                    height=text_height,
                    align=_align_left,
                    is_drafting=False,
                )
            except Exception as exc:
                print(f"[symbol]   left text failed: {exc}")
        # Pin dot
        _place_pin(term, x=0.0, y=y, angle=180.0)
        print(f"[symbol] left  pin '{term.name}' at (0.0, {y}) angle=180")

    # ── Right-side pins: stub + text label + pin dot ──────────────────────────
    y_start = (n_right - 1) * 2.0 / 2.0
    for idx, term in enumerate(right_terms):
        y = y_start - idx * 2.0
        # Port stub: body right edge → pin dot
        try:
            sym_design.add_line(LAYER_BODY, [(bx1, y), (symbol_width, y)])
        except Exception as exc:
            print(f"[symbol]   right stub failed: {exc}")
        # Port name text: just inside right body edge, extending left
        if _has_text:
            try:
                sym_design.add_text(
                    LAYER_TEXT, term.name,
                    origin=(bx1 - inner_inset, y),
                    font_name="Roboto",
                    height=text_height,
                    align=_align_right,
                    is_drafting=False,
                )
            except Exception as exc:
                print(f"[symbol]   right text failed: {exc}")
        # Pin dot
        _place_pin(term, x=symbol_width, y=y, angle=0.0)
        print(f"[symbol] right pin '{term.name}' at ({symbol_width}, {y}) angle=0")

    # ── Save ──────────────────────────────────────────────────────────────────
    # Commit transaction to finalize symbol design in OpenAccess (same pattern as schematic)
    commit_design(session, sym_design)
    save_design(sym_design)
    print(f"[symbol] dual symbol saved: {lib_name}:{cell_name}:symbol")
