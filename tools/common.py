# Copyright (c) 2025 National Instruments Corporation
# 
# SPDX-License-Identifier: MIT
#

import os
import re
import traceback

def handle_long_path(path):
    """
    Handle Windows long path limitations by prefixing with \\?\ when needed.
    This allows paths up to ~32K characters instead of the default 260 character limit.
    
    The \\?\ prefix tells Windows API to use extended-length path handling, bypassing
    the normal MAX_PATH limitation. This is essential when working with deeply nested
    project directories or auto-generated files with long names.
    
    Args:
        path (str): The file or directory path to process
        
    Returns:
        str: Modified path with \\?\ prefix if on Windows with long path,
             or the original path otherwise
    """
    if os.name == 'nt' and len(path) > 240:  # Windows and approaching 260-char limit
        # Ensure the path is absolute and normalize it
        abs_path = os.path.abspath(path)
        return f"\\\\?\\{abs_path}"
    return path


def resolve_path(rel_path):
    """
    Convert a relative path to an absolute path based on the current working directory.
    
    This is useful for processing configuration file paths that may be specified
    relative to the location of the configuration file itself.
    
    Args:
        rel_path (str): Relative path to convert
        
    Returns:
        str: Normalized absolute path
    """
    abs_path = os.path.normpath(os.path.join(os.getcwd(), rel_path))
    return abs_path


def fix_file_slashes(path):
    """
    Converts backslashes to forward slashes in file paths.
    
    Vivado and TCL scripts work better with forward slashes in paths,
    regardless of platform. This ensures consistent path formatting.
    
    Args:
        path (str): File path potentially containing backslashes
        
    Returns:
        str: Path with all backslashes converted to forward slashes
    """
    return path.replace('\\', '/')


def parse_vhdl_entity(vhdl_path):
    """
    Parse VHDL file to extract entity information - port names only.
    
    This function analyzes a VHDL file and extracts the entity name and all 
    port names from the entity declaration. It handles complex VHDL syntax including
    multi-line port declarations, comments, and multiple ports with the same data type.
    
    Args:
        vhdl_path (str): Path to the VHDL file to parse
        
    Returns:
        tuple: (entity_name, ports_list)
            - entity_name (str or None): The name of the entity if found, None otherwise
            - ports_list (list): List of port names, empty if none found or on error
    """
    # Handle long paths
    long_path = handle_long_path(vhdl_path)
    
    if not os.path.exists(long_path):
        print(f"Error: VHDL file not found: {vhdl_path}")
        return None, []
    
    try:
        # Read the entire file as a single string
        with open(long_path, 'r') as f:
            content = f.read()
            
        # Step 1: Find the entity declaration
        # Use regex to look for "entity <name> is" pattern, case-insensitive
        entity_pattern = re.compile(r'entity\s+(\w+)\s+is', re.IGNORECASE)
        entity_match = entity_pattern.search(content)
        if not entity_match:
            print(f"Error: Could not find entity declaration in {vhdl_path}")
            return None, []
            
        entity_name = entity_match.group(1)
        
        # Step 2: Find the entire port section
        # First, find the start position of "port ("
        port_start_pattern = re.compile(r'port\s*\(', re.IGNORECASE)
        port_start_match = port_start_pattern.search(content, entity_match.end())
        if not port_start_match:
            print(f"Error: Could not find port declaration in {vhdl_path}")
            return entity_name, []
        
        port_start = port_start_match.end()
        
        # Now find the matching closing parenthesis by counting open/close parentheses
        # This handles nested parentheses in port declarations correctly
        paren_level = 1
        port_end = port_start
        for i in range(port_start, len(content)):
            if content[i] == '(':
                paren_level += 1
            elif content[i] == ')':
                paren_level -= 1
                if paren_level == 0:
                    port_end = i
                    break
        
        if paren_level != 0:
            print(f"Error: Could not find end of port declaration")
            return entity_name, []
        
        # Extract port section
        port_section = content[port_start:port_end]
        
        # Clean up port section - remove comments
        port_section = re.sub(r'--.*?$', '', port_section, flags=re.MULTILINE)
        
        # Split by semicolons to get individual port declarations
        ports = []
        port_declarations = port_section.split(';')
        
        # Process each port declaration
        for decl in port_declarations:
            decl = decl.strip()
            if not decl or ':' not in decl:
                continue
                
            # Extract port names from before the colon
            names_part = decl.split(':', 1)[0].strip()
            
            # Handle multiple comma-separated port names
            for name in names_part.split(','):
                name = name.strip()
                if name:
                    ports.append(name)
        
        return entity_name, ports
        
    except Exception as e:
        print(f"Error parsing VHDL file: {str(e)}")
        traceback.print_exc()
        return None, []


def generate_entity_instantiation(vhdl_path, output_path, architecture='rtl'):
    """
    Generate VHDL entity instantiation from VHDL file.
    
    Creates a VHDL file containing an entity instantiation using the
    entity-architecture syntax (entity work.Entity_Name(architecture_name)).
    All ports are connected to signals with the same name.
    
    Args:
        vhdl_path (str): Path to input VHDL file containing entity declaration
        output_path (str): Path to output VHDL file where instantiation will be written
        architecture (str): Architecture name to use in the instantiation (default: 'rtl')
    
    Note:
        Signal declarations for ports are not included in the output.
        They must be declared separately.
    """
    entity_name, ports = parse_vhdl_entity(vhdl_path)

    # Create output directory if needed
    os.makedirs(os.path.dirname(output_path), exist_ok=True)   
    
    # Generate entity instantiation
    with open(output_path, 'w') as f:
        f.write(f"-- Entity instantiation for {entity_name}\n")
        f.write(f"-- Generated from {os.path.basename(vhdl_path)}\n\n")
        
        # Use entity-architecture syntax
        # Format: entity_label: entity work.entity_name(architecture_name)
        f.write(f"{entity_name}: entity work.{entity_name} ({architecture})\n")
        f.write("port map (\n")
        
        # Create port mappings
        # Format: port_name => signal_name
        port_mappings = [f"    {port} => {port}" for port in ports]
        
        if port_mappings:
            f.write(",\n".join(port_mappings))
            
        f.write("\n);\n")
    print(f"Generated entity instantiation for {entity_name}")


def get_vivado_project_files(lists_of_files):
    """
    Processes the configuration to generate the list of files for the Vivado project.
    
    This is the main function for file gathering that:
    1. Reads file list references from the config file
    2. Processes each list to collect FPGA design files
    3. Identifies and reports duplicate files
    4. Copies dependency files to a centralized location
    5. Returns a sorted, normalized list of all required files
    
    Args:
        config (ConfigParser): Parsed configuration object
        
    Returns:
        list: Complete list of files for the Vivado project
        
    Raises:
        FileNotFoundError: If a specified file list path doesn't exist
        ValueError: If duplicate files are found
    """
    
    # Combine all file lists into a single file_list
    file_list = []
    for file_list_path in lists_of_files:
        if os.path.exists(file_list_path):
            with open(file_list_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        if os.path.isdir(line):
                            print(f"Directory found: {line}")
                            # This is a directory, add all relevant files recursively
                            for root, _, files in os.walk(line):
                                for file in files:
                                    # Filter for relevant file types
                                    if file.endswith(('.vhd', '.v', '.sv', '.xdc', '.edf', '.dcp', '.xci')):
                                        file_path = os.path.join(root, file)
                                        file_list.append(fix_file_slashes(file_path))   
                        else:
                            file_list.append(fix_file_slashes(line))
        else:
            raise FileNotFoundError(f"File list path '{file_list_path}' does not exist.")

    # Sort the final file list
    file_list = sorted(file_list)

    return file_list