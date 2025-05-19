import os
import re
import traceback

def handle_long_path(path):
    """
    Handle Windows long path limitations by prefixing with \\?\ when needed.
    This allows paths up to ~32K characters.
    
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

def ensure_directory(path):
    """Create directory if it doesn't exist"""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")

def parse_vhdl_entity(vhdl_path):
    """Parse VHDL file to extract entity information - port names only"""
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
    Generate VHDL entity instantiation from VHDL file
    
    Args:
        vhdl_path: Path to input VHDL file
        output_path: Path to output VHDL file
        architecture: Architecture name to use (default: 'rtl')
    """
    entity_name, ports = parse_vhdl_entity(vhdl_path)

    # Create output directory if needed
    ensure_directory(output_path)
    
    # Generate entity instantiation
    with open(output_path, 'w') as f:
        f.write(f"-- Entity instantiation for {entity_name}\n")
        f.write(f"-- Generated from {os.path.basename(vhdl_path)}\n\n")
        
        # Use entity-architecture syntax
        f.write(f"{entity_name}: entity work.{entity_name} ({architecture})\n")
        f.write("port map (\n")
        
        # Create port mappings
        port_mappings = [f"    {port} => {port}" for port in ports]
        
        if port_mappings:
            f.write(",\n".join(port_mappings))
            
        f.write("\n);\n")
    print(f"Generated entity instantiation for {entity_name}")
        
