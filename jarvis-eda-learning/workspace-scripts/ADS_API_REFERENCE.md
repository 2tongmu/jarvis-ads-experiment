# ADS Python API Reference

Derived from reading ADS 2026 Update 1.2 source at:
`C:/Program Files/Keysight/ADS2026_Update1.2/tools/python/packages/keysight/ads/de/`

**Confirmed by Jarvis execution 2026-04-08** — corrections from
`ads_bias_subcell_create.py` applied and verified against the running API.
Same API applies to ADS 2026 Update 1 (Jarvis). Core module `_pde` is compiled
(`.pyd`); signatures come from `.pyi` stubs and Python wrapper files.

> **Critical note:** The `de_*` function names seen in `.dem` macro recordings are
> AEL (ADS Extension Language) calls, not Python. The Python API is fully
> object-oriented. Do not use `de_init_item`, `de_place_item`, etc. in Python scripts.

---

## Imports

```python
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
from keysight.ads.de._pde.db import TermType, DesignMode   # ✅ confirmed path
from keysight.ads.de.db import MirrorType, Orientation, LibraryMode
```

> **Note:** `TermType` and `DesignMode` live in the private `_pde.db` submodule,
> not the public `db` module. Import from `_pde.db` as shown above.

---

## 1. Workspace

```python
de.create_workspace(path: str) -> None       # create new workspace
de.open_workspace(path: str) -> Workspace    # open existing workspace
de.close_workspace() -> None
de.workspace_is_open() -> bool
de.workspace_directory() -> str
```

---

## 2. Library

```python
de.create_new_library(lib_name: str, lib_path: str) -> Library
de.open_library(lib_name: str, lib_path: str, mode: LibraryMode) -> Library
de.get_open_library(lib_name: str) -> Library
de.library_exists_at_path(path: str) -> bool
de.library_is_open(lib_name: str) -> bool
de.close_library(lib_name: str) -> None
```

---

## 3. Design / View creation  ✅ confirmed

`CellviewRefLike` accepts `"lib:cell:view"` string, `("lib","cell","view")` tuple, or `LCVName`.

**Confirmed pattern (Jarvis 2026-04-08):**
```python
# Get existing library (already in workspace)
lib = de.get_open_library(lib_name) -> Library

# Get or create cell
if lib.cell_exists(cell_name):
    cell = lib.cell(cell_name)
else:
    cell = de.Cell.create(lib, cell_name)

# Create view (delete first if recreating)
if cell.view_exists('schematic'):
    cell.delete_view('schematic')
sch_view = de.View.create(cell, 'schematic', 'schematic') -> View

# Get design in WRITE mode — CRITICAL: default is READ_ONLY, cannot save
design = sch_view.get_design(DesignMode.WRITE) -> Design
```

For symbols and layouts:
```python
symbol_design = db.create_symbol((lib_name, cell_name, 'symbol')) -> Design
sym_view      = cell.view('symbol')
sym_write     = sym_view.get_design(DesignMode.WRITE) -> Design
```

Save:
```python
design.save_design() -> None          # ✅ confirmed — must be called explicitly
```

---

## 4. Placing instances (components)  ✅ confirmed

```python
# Place via the design object — confirmed API
inst = design.add_instance(
    master = de.LCVName(lib, cell, view),  # ✅ use de.LCVName, not string
    origin = (x, y),                       # tuple of floats (user units)
    name   = "R1",                         # instance name
    angle  = 0.0,                          # rotation degrees
) -> Instance
```

Parameters — use dict-style access with `.value` setter:
```python
inst.parameters["R"].value = "Rs"    # ✅ confirmed — sets to variable expression
inst.parameters["C"].value = "Cp"
```

> **NOT** `inst.pcell_parameters[key] = value` — that API exists but
> `parameters[key].value` is the confirmed working form.

---

## 5. Nets  ✅ confirmed

```python
net = design.find_or_add_net("net_name") -> Net   # ✅ confirmed
```

> **NOT** `ScalarNet(design=schematic, name=...)` — use `design.find_or_add_net()`.
> This is idempotent: returns existing net if name already exists.

---

## 6. Terminals (cell ports / generic pins)  ✅ confirmed

Terminals define the cell's external interface. Use `design.add_term()` — **not**
`ads_simulation:Term` (simulation component only) and **not** `ScalarTerm()` constructor.

```python
net  = design.find_or_add_net("port_name")
term = design.add_term(net, "port_name", TermType.INPUT_OUTPUT) -> Term   # ✅ confirmed

# TermType values (from keysight.ads.de._pde.db):
#   INPUT  OUTPUT  INPUT_OUTPUT  SWITCH  JUMPER  UNUSED  TRISTATE

# Iterate all terms on a design (used for symbol generation):
for term in design.terms:
    print(term.name, term.term_type)
```

---

## 7. Pins (graphical port marker)  ✅ confirmed

For schematic sub-cell pins, `add_pin_fig_for_term_type()` is the confirmed method.
Use this on the **symbol** design to place a pin figure for each term.

```python
# On the symbol design (not schematic):
sym_design_write.add_pin_fig_for_term_type(term.term_type, (x, y))  # ✅ confirmed

# Standard pin layout for blackbox: iterate schematic terms, place vertically
sch_terms = list(design.terms)
y_spacing = 2.0
y_start   = (len(sch_terms) - 1) * y_spacing / 2.0
for idx, term in enumerate(sch_terms):
    y_pos = y_start - (idx * y_spacing)
    sym_design_write.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))
```

> The `Pin(term, [rect], ...)` constructor API exists in the stubs but
> `add_pin_fig_for_term_type()` is the confirmed working path.

---

## 8. Wiring  ✅ confirmed

```python
# Add a wire as a list of (x, y) waypoints — ADS auto-connects to pins/terms
design.add_wire([(x1, y1), (x2, y2), ...])   # ✅ confirmed

# Multi-segment wire (one call = one polyline):
design.add_wire([(0.0, 0.0), (2.875, 0.0), (4.25, 0.0), (6.5, 0.0)])
```

> **NOT** `Line(design, layer, Outline([...]))` — use `design.add_wire()`.
> Wire connectivity is position-based: wire endpoint must reach the component
> pin or term snap-point. There is no explicit `wire.net = net` assignment needed.

---

## 9. Design variables  ✅ confirmed

```python
# Write design variables — list of (name, value_str) tuples
design.cell.write_design_variables([
    ("Rs", "1000 Ohm"),
    ("Cp", "1 pF"),
])   # ✅ confirmed

# Read design variables
design.cell.read_design_variables() -> list[tuple[str, str]]
```

> **NOT** `write_design_variables(design.cell, [...])` (module-level function) —
> use the method `design.cell.write_design_variables([...])` directly.

---

## 10. Symbol generation (blackbox)

```python
from keysight.ads.de.experimental.generate_symbol import de_generate_blackbox_symbol, OrderType

source_design = db_uu.open_design("lib:cell:schematic", DesignMode.READ_ONLY)
symbol_design = db_uu.create_symbol("lib:cell:symbol")

de_generate_blackbox_symbol(
    symbol_design       = symbol_design,
    source_design       = source_design,
    lead_len            = 0.25,               # pin lead length (user units)
    lead_spacing        = 0.25,               # pin-to-pin spacing
    is_dual_symbol_type = False,              # False=quad (4-side), True=dual (2-side)
    replace             = False,              # True to replace existing symbol
    order               = OrderType.ORDER_LOCATION,
    add_ref             = False,
    pin_shape           = "dot",              # "dot" | "square" | "round"
    pin_one_warn_off    = False,
    use_one_pin_per_em_port = False,
    use_pin_net_text_label  = False,
    use_single_line_body    = False,
) -> None
```

`OrderType` values: `ORDER_LOCATION`, `ORDER_NUMBER1`, `ORDER_NUMBER2`,
`ORDER_NUMBER3`, `ORDER_NUMBER4`

---

## 11. Key enumerations

```python
from keysight.ads.de.db import (
    DesignMode,   # READ_ONLY  APPEND  OVERWRITE
    MirrorType,   # NONE  MIRROR_X  MIRROR_Y
    Orientation,  # R0  R90  R180  R270  MY  MYR90  MX  MXR90
    TermType,     # INPUT  OUTPUT  INPUT_OUTPUT  SWITCH  JUMPER  UNUSED  TRISTATE
    SignalType,   # SIGNAL  POWER  GROUND  CLOCK  TIE_OFF  TIE_HI  TIE_LO  ANALOG
    LibraryMode,  # READ_ONLY  READ_WRITE
)
```

---

## 12. Component LCV names (ads_rflib)

| Component | LCV string                   |
|-----------|------------------------------|
| Resistor  | `"ads_rflib:R:symbol"`       |
| Capacitor | `"ads_rflib:C:symbol"`       |
| Inductor  | `"ads_rflib:L:symbol"`       |
| Ground    | `"ads_rflib:GROUND:symbol"`  |
| Port/Term | `"ads_simulation:Term:symbol"` *(simulation only — not for cell ports)* |

---

## 13. AEL vs Python — what NOT to use in scripts

The `.dem` macro recorder outputs AEL function calls. These are **not** Python and
will fail or produce wrong results in Python scripts:

| AEL (`.dem` — do not use)              | Python equivalent                         |
|-----------------------------------------|-------------------------------------------|
| `de_create_new_schematic_view(l,c,v)`  | `db_uu.create_schematic("l:c:v")`         |
| `de_get_design_context_from_name(lcv)` | `db_uu.open_design(lcv)` (or just use the Design object) |
| `de_init_item("lib:cell:view")`        | `Instance(design, master="lib:cell:view", ...)` |
| `de_rotate_inc()` / `de_rotate_image()`| `angle=90.0` / `mirror=MirrorType.MIRROR_X` on `Instance` |
| `de_place_item(item, x, y)`            | `inst.origin = (x, y)` or set in `Instance()` constructor |
| `db_create_pin(ctx, x, y, rot, ...)`   | `ScalarTerm` + `Pin` + `Rect` (see §6–7) |
| `de_connect()` / `de_add_wire(x,y)`    | `Line(design, layer, Outline([...]))`     |
| `de_edit_item` / `de_set_item_parameters` | `inst.pcell_parameters[name] = value`  |
| `de_update_item_ex` / `create_parm`    | `write_design_variables(cell, [...])`     |
| `de_save_oa_design(lcv)`               | `design.save_design()`                    |
| `de_create_new_symbol_view()`          | `db_uu.create_symbol("lib:cell:symbol")`  |
| `de_generate_blackbox_symbol(...)`     | `de_generate_blackbox_symbol(...)` *(same name, different import — see §10)* |
