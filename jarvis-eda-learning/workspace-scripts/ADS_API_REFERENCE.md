# ADS Python API Reference

**Status key:**
- ✅ CONFIRMED — verified by Jarvis execution on ADS 2026 Update 1 (2026-04-08)
- ⚠️ UNCONFIRMED — from source stubs / static analysis only; may be wrong

Applies to: ADS 2026 Update 1 (Jarvis), ADS 2026 Update 1.2 (local dev).
Core `_pde` module is compiled (`.pyd`); signatures from `.pyi` stubs.

> **Critical:** `.dem` macro recordings use AEL function calls — not Python.
> Do not use `de_init_item`, `de_place_item`, etc. in scripts. See §13.

---

## Imports

```python
import keysight.ads.de as de
from keysight.ads.de import db_uu as db
from keysight.ads.de._pde.db import TermType, DesignMode   # ✅ CONFIRMED
from keysight.ads.de.db import MirrorType, Orientation, LibraryMode  # ⚠️ UNCONFIRMED
```

> `TermType` and `DesignMode` are in `_pde.db` (private submodule), **not** the
> public `keysight.ads.de.db`. Importing from the wrong module silently fails.

---

## 1. Workspace

```python
de.open_workspace(path: str) -> Workspace    # ✅ CONFIRMED
de.create_workspace(path: str) -> None       # ⚠️ UNCONFIRMED
de.close_workspace() -> None                 # ⚠️ UNCONFIRMED
de.workspace_is_open() -> bool               # ⚠️ UNCONFIRMED
de.workspace_directory() -> str              # ⚠️ UNCONFIRMED
```

Suppress benign vtb.defs warnings with:
```python
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    ws = de.open_workspace(WORKSPACE)   # ✅ CONFIRMED
```

---

## 2. Library

```python
de.get_open_library(lib_name: str) -> Library        # ✅ CONFIRMED
lib.cell_exists(cell_name: str) -> bool              # ✅ CONFIRMED
lib.cell(cell_name: str) -> Cell                     # ✅ CONFIRMED
de.Cell.create(lib, cell_name: str) -> Cell          # ✅ CONFIRMED

de.create_new_library(lib_name, lib_path) -> Library # ⚠️ UNCONFIRMED
de.open_library(lib_name, lib_path, mode) -> Library # ⚠️ UNCONFIRMED
de.library_exists_at_path(path: str) -> bool         # ⚠️ UNCONFIRMED
de.library_is_open(lib_name: str) -> bool            # ⚠️ UNCONFIRMED
de.close_library(lib_name: str) -> None              # ⚠️ UNCONFIRMED
```

---

## 3. Design / View creation  ✅ CONFIRMED

Full confirmed pattern for creating a schematic:

```python
lib = de.get_open_library(lib_name)

# Get or create cell
if lib.cell_exists(cell_name):
    cell = lib.cell(cell_name)
else:
    cell = de.Cell.create(lib, cell_name)

# Recreate view from scratch (delete if exists)
if cell.view_exists('schematic'):
    cell.delete_view('schematic')          # ✅ CONFIRMED
sch_view = de.View.create(cell, 'schematic', 'schematic')  # ✅ CONFIRMED

# CRITICAL: must open in WRITE mode — default READ_ONLY cannot save
design = sch_view.get_design(DesignMode.WRITE)  # ✅ CONFIRMED
```

For symbols:
```python
symbol_design = db.create_symbol((lib_name, cell_name, 'symbol'))  # ✅ CONFIRMED
sym_view      = cell.view('symbol')                                  # ✅ CONFIRMED
sym_write     = sym_view.get_design(DesignMode.WRITE)               # ✅ CONFIRMED
```

Saving:
```python
design.save_design()   # ✅ CONFIRMED — must be called; changes are not auto-saved
```

---

## 4. Placing instances  ✅ CONFIRMED

```python
inst = design.add_instance(
    de.LCVName(lib, cell, view),   # ✅ CONFIRMED — use LCVName, not bare string
    (x, y),                        # origin as tuple of floats (user units)
    name  = "R1",
    angle = 0.0,                   # rotation in degrees (0=default, 90=rotated, etc.)
)
```

Setting parameters — dict access with `.value`:
```python
inst.parameters["R"].value = "Rs"   # ✅ CONFIRMED — assigns design variable expression
inst.parameters["C"].value = "Cp"   # ✅ CONFIRMED
```

> **NOT** `inst.pcell_parameters[key] = value` — `parameters[key].value` is confirmed.

---

## 5. Nets  ✅ CONFIRMED

```python
net = design.find_or_add_net("net_name")   # ✅ CONFIRMED
# Idempotent: returns existing net if the name already exists.
```

> **NOT** `ScalarNet(design=schematic, name=...)`.

---

## 6. Terminals (cell ports)  ✅ CONFIRMED

Terminals are the cell's external interface — the sub-cell pin definition.

```python
net  = design.find_or_add_net("port_name")
term = design.add_term(net, "port_name", TermType.INPUT_OUTPUT)  # ✅ CONFIRMED
```

TermType values (from `keysight.ads.de._pde.db`):
`INPUT` `OUTPUT` `INPUT_OUTPUT` `SWITCH` `JUMPER` `UNUSED` `TRISTATE`

Iterating all terms on a design:
```python
for term in design.terms:   # ✅ CONFIRMED
    print(term.name, term.term_type)
```

> **NOT** `ScalarTerm(net, name, term_type)` constructor.
> **NOT** `ads_simulation:Term` — that is a simulation port component, not a cell pin.

---

## 7. Symbol pin figures  ✅ CONFIRMED

Place one pin figure per schematic term on the **symbol** design:

```python
# Create symbol design first (see §3)
sch_terms = list(design.terms)   # ✅ CONFIRMED — reads terms from schematic design

y_spacing = 2.0
y_start   = (len(sch_terms) - 1) * y_spacing / 2.0
for idx, term in enumerate(sch_terms):
    y_pos = y_start - (idx * y_spacing)
    sym_write.add_pin_fig_for_term_type(term.term_type, (0.0, y_pos))  # ✅ CONFIRMED

sym_write.save_design()   # ✅ CONFIRMED
```

> `Pin(term, [rect], ...)` constructor exists in stubs but is ⚠️ UNCONFIRMED.
> `de_generate_blackbox_symbol()` from `experimental` is ⚠️ UNCONFIRMED — Jarvis
> used `add_pin_fig_for_term_type()` instead.

---

## 8. Wiring  ✅ CONFIRMED

```python
design.add_wire([(x1, y1), (x2, y2), ...])   # ✅ CONFIRMED
```

One call = one polyline. ADS auto-connects endpoints to component pins and terms
based on position — no explicit net assignment needed.

```python
# Example: main horizontal path + shunt branch
design.add_wire([(0.0, 0.0), (2.875, 0.0), (4.25, 0.0), (6.5, 0.0)])  # ✅ CONFIRMED
design.add_wire([(2.875, 0.0), (2.875, -1.0)])                          # ✅ CONFIRMED
```

> **NOT** `Line(design, layer, Outline([...]))`.

---

## 9. Design variables  ✅ CONFIRMED

```python
design.cell.write_design_variables([   # ✅ CONFIRMED
    ("Rs", "1000 Ohm"),
    ("Cp", "1 pF"),
])

design.cell.read_design_variables()    # ⚠️ UNCONFIRMED (exists in stubs)
```

> **NOT** the module-level `write_design_variables(design.cell, [...])`.

---

## 10. Enumerations

```python
from keysight.ads.de._pde.db import TermType, DesignMode  # ✅ CONFIRMED

# DesignMode  ✅ CONFIRMED
DesignMode.WRITE      # open design for modification
DesignMode.READ_ONLY  # default — cannot save_design()

# TermType  ✅ CONFIRMED
TermType.INPUT_OUTPUT
TermType.INPUT
TermType.OUTPUT

# The following exist in stubs but import paths are ⚠️ UNCONFIRMED:
from keysight.ads.de.db import MirrorType, Orientation, SignalType, LibraryMode
```

---

## 11. Component LCV names (ads_rflib)

| Component | LCVName args                          | Status        |
|-----------|---------------------------------------|---------------|
| Resistor  | `de.LCVName('ads_rflib','R','symbol')`      | ✅ CONFIRMED |
| Capacitor | `de.LCVName('ads_rflib','C','symbol')`      | ✅ CONFIRMED |
| Ground    | `de.LCVName('ads_rflib','GROUND','symbol')` | ✅ CONFIRMED |
| Inductor  | `de.LCVName('ads_rflib','L','symbol')`      | ⚠️ UNCONFIRMED |
| Sim Port  | `de.LCVName('ads_simulation','Term','symbol')` | ⚠️ do NOT use for cell ports |

---

## 12. AEL vs Python

`.dem` macro recordings use AEL. Python equivalents (all ✅ CONFIRMED unless noted):

| AEL (`.dem` — do not use)                    | Confirmed Python equivalent                              |
|----------------------------------------------|----------------------------------------------------------|
| `de_create_new_schematic_view(l, c, v)`      | `de.View.create(cell, 'schematic', 'schematic')`         |
| `de_get_design_context_from_name(lcv)`       | `sch_view.get_design(DesignMode.WRITE)`                  |
| `de_init_item("lib:cell:view")`              | `de.LCVName(lib, cell, view)` as arg to `add_instance`  |
| `de_rotate_inc()` / `de_rotate_image("DOWN")`| `angle=90.0` / `angle=180.0` on `add_instance`          |
| `de_place_item(item, x, y)`                  | `design.add_instance(lcv_name, (x, y), name=, angle=)`  |
| `db_create_pin(ctx, x, y, rot, ...)`         | `design.add_term(net, name, TermType)` (see §6)          |
| `de_connect()` / `de_add_wire(x, y)`         | `design.add_wire([(x1,y1), (x2,y2), ...])`              |
| `de_edit_item` / `de_set_item_parameters`    | `inst.parameters[key].value = expr`                     |
| `de_update_item_ex` / `create_parm`          | `design.cell.write_design_variables([...])`              |
| `de_save_oa_design(lcv)`                     | `design.save_design()`                                   |
| `de_create_new_symbol_view()`                | `db.create_symbol((lib, cell, 'symbol'))`               |
| `de_generate_blackbox_symbol(...)`           | `sym_write.add_pin_fig_for_term_type(...)` per term (§7) |
