"""
ads_api/itemdef_generator.py
============================
Generate itemdef.ael files to expose design variables as user parameters.

In ADS, subcircuit cells can have design variables defined at the schematic level,
but these are only exposed as user parameters (editable properties when instantiated
in a parent schematic) if the cell has an itemdef.ael file that declares them via
create_item() and create_parm() functions.

This module generates these AEL files programmatically.

Usage:
    from ads_api.itemdef_generator import create_itemdef_ael
    
    variables = [('Rs', '1000.0 Ohm', 'series resistance'), 
                 ('Cp', '2272.73 fF', 'parallel capacitance')]
    ael_content = create_itemdef_ael('fetbias_sw_gate', variables)
    
    # Write to cell directory
    Path(cell_dir / 'itemdef.ael').write_text(ael_content)
"""

def create_itemdef_ael(cell_name: str, variables: list) -> str:
    """
    Generate an itemdef.ael file for a subcircuit cell.
    
    Makes design variables visible as user parameters (Component Parameters)
    when the cell is instantiated in a parent schematic.
    
    Args:
        cell_name   : name of the cell (e.g. 'fetbias_sw_gate')
        variables   : list of (var_name, var_value, description) tuples
                      e.g. [('Rs', '1000.0 Ohm', 'series resistance'),
                            ('Cp', '2272.73 fF', 'parallel capacitance')]
    
    Returns:
        String containing the complete itemdef.ael file content
    
    Format (Cadence AEL - Analog Environment Language):
        create_item(
            cell_name, symbol_name, type, flags, icon, ...
            "Component Parameters",  <-- Category shown in ADS GUI
            ...,
            create_parm(...),        <-- Each parameter
            create_parm(...)
        );
    """
    
    # Extract parameter names and convert values to AEL format
    parm_list = []
    for var_name, var_value, description in variables:
        # Parse the value to extract number and unit
        # Examples: "1000.0 Ohm" -> (1000.0, "Ohm")
        #           "2272.73 fF" -> (2272.73, "fF")
        parts = var_value.strip().split()
        if len(parts) >= 2:
            num = parts[0]
            unit = ' '.join(parts[1:])
        else:
            num = var_value
            unit = ""
        
        # Convert to scientific notation for AEL default value
        # "1000.0 Ohm" -> "1e3"
        # "2272.73 fF" -> "2.27273e-12" (in base units)
        # For now, use simple format: just the number in scientific notation
        try:
            num_float = float(num)
            sci_notation = f"{num_float:.5e}".rstrip('0').rstrip('.')
        except:
            sci_notation = num
        
        # Create parameter definition
        # Format: create_parm("VarName", "description", flags, "StdFormSet", -1, prm("StdForm", "default"))
        parm = f'create_parm("{var_name}","{description}",68608,"StdFormSet",-1,prm("StdForm","{sci_notation}"))'
        parm_list.append(parm)
    
    # Build the create_item call
    # Flags: 16 = standard component, -1 = no special handling
    # Type: "X" = subcircuit/component
    parm_args = ','.join(parm_list)
    
    ael_content = (
        f'create_item("{cell_name}","{cell_name}","X",16,-1,NULL,"Component Parameters",NULL,'
        f'"%43?global %;%d:%t %# %44?0%:%31?%C%:_net%c%;%;%e %b%r%8?%29?%:%30?%p %:%k%?[%1i]%;=%p %;%;%;%e%e",'
        f'"{cell_name}",'
        f'"%t%b%r%38?%:\n%30?%s%:%k%?[%1i]%;=%s%;%;%e%e%;","",3,NULL,0,\n'
        f'{parm_args});'
    )
    
    return ael_content


def write_itemdef_to_cell(cell_dir_path, cell_name: str, variables: list) -> None:
    """
    Write itemdef.ael file to a cell directory.
    
    Args:
        cell_dir_path : pathlib.Path to the cell directory
                        (e.g. C:\Users\...\net2ads_lib\fetbias_sw_gate\)
        cell_name     : name of the cell
        variables     : list of (var_name, var_value, description) tuples
    """
    from pathlib import Path
    
    cell_dir = Path(cell_dir_path)
    itemdef_path = cell_dir / 'itemdef.ael'
    
    ael_content = create_itemdef_ael(cell_name, variables)
    itemdef_path.write_text(ael_content, encoding='utf-8')
    
    print(f"[itemdef] wrote {itemdef_path}")
    print(f"[itemdef] content:\n{ael_content}\n")


if __name__ == "__main__":
    # Test generation
    variables = [
        ('Cp', '2272.73 fF', 'parallel capacitance (F)'),
        ('Rs', '1000.0 Ohm', 'series resistance (ohm)')
    ]
    
    ael = create_itemdef_ael('fetbias_sw_gate', variables)
    print(ael)
