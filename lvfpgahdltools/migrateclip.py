# githubvisible=true
import xml.etree.ElementTree as ET
import os
import sys
import csv
from dataclasses import dataclass
import configparser
import re
import traceback


@dataclass
class FileConfiguration:
    """Class to store file paths from the INI file."""
    input_xml: str
    output_csv: str


def load_config(config_path=None):
    """
    Load configuration from INI file.
    
    Args:
        config_path: Path to the INI file. If None, searches in the current directory.
        
    Returns:
        Tuple with input paths and output paths
    """
    if config_path is None:
        config_path = os.path.join(os.getcwd(), "vivadoprojectsettings.ini")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
        
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # Get required settings
    try:
        settings = config['CLIPMigrationSettings']
        input_xml = settings['CLIPXML']
        output_csv = settings['CustomSignalsCSV']
        clip_hdl_top = settings['CLIPHDLTop']
        clip_xdc = settings['CLIPXDC']
        clip_instantiation = settings['CLIPInstantiationExample']
        clip_instance_path = settings['CLIPInstancePath']
        updated_xdc = settings['UpdatedCLIPXDC']
        
    except KeyError as e:
        sys.exit(f"Error: Missing {e} in configuration file.")
        traceback.print_exc()
    
    # Resolve relative paths
    base_dir = os.path.dirname(config_path)
    input_path = os.path.join(base_dir, input_xml)
    output_path = os.path.join(base_dir, output_csv)
    clip_hdl_path = os.path.join(base_dir, clip_hdl_top)
    instantiation_path = os.path.join(base_dir, clip_instantiation)
    clip_xdc_path = os.path.join(base_dir, clip_xdc)
    updated_xdc_path = os.path.join(base_dir, updated_xdc) 
    
    return (input_path, output_path, clip_hdl_path, instantiation_path, 
            clip_xdc_path, clip_instance_path, updated_xdc_path)


def find_case_insensitive(element, xpath):
    """Find an element using case-insensitive tag and attribute matching"""
    if element is None:
        return None
        
    # Handle simple tag name search
    if not xpath.startswith('.//') and not xpath.startswith('@'):
        for child in element:
            if child.tag.lower() == xpath.lower():
                return child
        return None
    
    # Handle xpath with attribute condition like ".//Interface[@Name='LabVIEW']"
    if xpath.startswith('.//') and '@' in xpath:
        base_path, condition = xpath.split('[', 1)
        tag_name = base_path.replace('.//', '')
        attr_name, attr_value = condition.replace(']', '').replace('@', '').split('=')
        attr_value = attr_value.strip("'\"")
        
        # Search recursively
        for elem in element.iter():
            if elem.tag.lower() == tag_name.lower():
                for attr, value in elem.attrib.items():
                    if attr.lower() == attr_name.lower() and value.lower() == attr_value.lower():
                        return elem
        return None
    
    # Handle simple descendant search ".//TagName"
    if xpath.startswith('.//'):
        tag_name = xpath.replace('.//', '')
        for elem in element.iter():
            if elem.tag.lower() == tag_name.lower():
                return elem
        return None
        
    # Default to standard find for other cases
    return element.find(xpath)


def findall_case_insensitive(element, xpath):
    """Find all elements using case-insensitive tag and attribute matching"""
    if element is None:
        return []
        
    # Handle simple descendant search ".//TagName"
    if xpath.startswith('.//'):
        # Handle paths with multiple levels like ".//SignalList/Signal"
        path_parts = xpath.replace('.//', '').split('/')
        
        if len(path_parts) == 1:
            # Simple case like ".//Signal"
            tag_name = path_parts[0]
            return [elem for elem in element.iter() if elem.tag.lower() == tag_name.lower()]
        else:
            # Complex case like ".//SignalList/Signal"
            # First find all elements matching the first part
            parent_tag = path_parts[0]
            child_tag = path_parts[1]
            
            # Find all parents
            results = []
            for parent in element.iter():
                if parent.tag.lower() == parent_tag.lower():
                    # Then find all children under this parent with matching tag
                    for child in parent:
                        if child.tag.lower() == child_tag.lower():
                            results.append(child)
            return results
        
    # Default to standard findall for other cases
    return element.findall(xpath)


def get_attribute_case_insensitive(element, attr_name, default=""):
    """Get attribute value using case-insensitive matching"""
    if element is None:
        return default
        
    for attr, value in element.attrib.items():
        if attr.lower() == attr_name.lower():
            return value
    return default


def get_element_text(element, xpath, default=""):
    """Safely extract text from an element using case-insensitive matching"""
    child = find_case_insensitive(element, xpath) if element is not None else None
    return child.text if child is not None and child.text else default


def extract_data_type(element):
    """Extract data type from element using case-insensitive matching"""
    if element is None:
        return "N/A"
    
    # Check for simple types
    simple_types = ["Boolean", "U8", "U16", "U32", "U64", "I8", "I16", "I32", "I64"]
    for type_name in simple_types:
        if find_case_insensitive(element, type_name) is not None:
            return type_name
    
    # Check for FXP
    fxp = find_case_insensitive(element, "FXP")
    if fxp is not None:
        word_length = get_element_text(fxp, "WordLength", "?")
        int_word_length = get_element_text(fxp, "IntegerWordLength", "?")
        signed = "Unsigned" if find_case_insensitive(fxp, "Unsigned") is not None else "Signed"
        return f"FXP({word_length},{int_word_length},{signed})"
    
    # Check for Array
    array = find_case_insensitive(element, "Array")
    if array is not None:
        size = get_element_text(array, "Size", "?")
        
        # Find array element type
        subtype = "Unknown"
        for type_name in simple_types + ["FXP"]:
            if find_case_insensitive(array, type_name) is not None:
                subtype = type_name
                break
        
        return f"Array<{subtype}>[{size}]"
    
    return "Unknown"


def ensure_directory(path):
    """Create directory if it doesn't exist"""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")


def process_clip_xml(input_path, output_path):
    """Process CLIP XML and generate CSV"""
    try:
        # Validate input file
        if not os.path.exists(input_path):
            sys.exit(f"Error: Input file not found: {input_path}")
            
        # Ensure output directory exists
        ensure_directory(output_path)
        
        # Parse XML
        try:
            tree = ET.parse(input_path)
            root = tree.getroot()
        except ET.ParseError as e:
            sys.exit(f"Error parsing XML file: {e}")
        
        # Find LabVIEW interface
        lv_interface = find_case_insensitive(root, ".//Interface[@Name='LabVIEW']")
        if lv_interface is None:
            sys.exit(f"No LabVIEW interface found in {input_path}")
        
        # Open CSV for writing
        with open(output_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow([
                "LVName", "HDLName", "Direction", "SignalType",
                "DataType", "UseInLabVIEWSingleCycleTimedLoop", "RequiredClockDomain"
            ])
            
            # Find signals
            signals = findall_case_insensitive(lv_interface, ".//SignalList/Signal")             
            if not signals:
                print("Warning: No signals found in the LabVIEW interface")
            
            # Process each signal
            for signal in signals:
                # Get signal name - try both "Name" and "name" attributes
                name = get_attribute_case_insensitive(signal, "Name")
                if not name:
                    print("Warning: Signal without a name found, skipping")
                    continue
                
                # Format LabVIEW name
                lv_name = "IO Socket\\" + name.replace(".", "\\")
                
                # Get signal properties using case-insensitive matching
                hdl_name = get_element_text(signal, "HDLName", "N/A")
                raw_direction = get_element_text(signal, "Direction", "N/A")
                direction = {"ToCLIP": "output", "FromCLIP": "input"}.get(raw_direction, raw_direction)
                signal_type = get_element_text(signal, "SignalType", "N/A")
                data_type = extract_data_type(signal.find("DataType") or find_case_insensitive(signal, "DataType"))
                use_in_scl = get_element_text(signal, "UseInLabVIEWSingleCycleTimedLoop")
                clock_domain = get_element_text(signal, "RequiredClockDomain")
                
                # Write row to CSV
                writer.writerow([
                    lv_name, hdl_name, direction, signal_type,
                    data_type, use_in_scl, clock_domain
                ])
        
        return True
    
    except Exception as e:
        print(f"Error processing XML: {str(e)}")
        traceback.print_exc()
        return False


def parse_vhdl_entity(vhdl_path):
    """
    Parse VHDL file to extract entity information - port names only
    
    Args:
        vhdl_path: Path to VHDL file
        
    Returns:
        Tuple with entity name and list of port names
    """
    if not os.path.exists(vhdl_path):
        print(f"Error: VHDL file not found: {vhdl_path}")
        return None, []
    
    try:
        # Read the entire file as a single string
        with open(vhdl_path, 'r') as f:
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


def generate_entity_instantiation(vhdl_path, output_path):
    """Generate VHDL entity instantiation from VHDL file"""
    entity_name, ports = parse_vhdl_entity(vhdl_path)
        
    # Create output directory if needed
    ensure_directory(output_path)
    
    # Generate entity instantiation
    with open(output_path, 'w') as f:
        f.write(f"-- Entity instantiation for {entity_name}\n")
        f.write(f"-- Generated from {os.path.basename(vhdl_path)}\n\n")
        
        f.write(f"{entity_name}: {entity_name}\n")
        f.write("port map (\n")
        
        # Create port mappings
        port_mappings = [f"    {port} => {port}" for port in ports]
        
        if port_mappings:
            f.write(",\n".join(port_mappings))
            
        f.write("\n);\n")
        
    return True


def process_constraint_file(input_path, output_path, instance_path):
    """
    Process XDC constraint file and replace %ClipInstancePath% with the instance path
    
    Args:
        input_path: Path to input XDC file
        output_path: Path to output XDC file
        instance_path: Instance path to use for replacement
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if not os.path.exists(input_path):
            print(f"Error: XDC file not found: {input_path}")
            return False
        
        # Create output directory if needed
        ensure_directory(output_path)
        
        # Read the input file
        with open(input_path, 'r') as infile:
            content = infile.read()
            
        # Replace all instances of %ClipInstancePath%
        updated_content = content.replace('%ClipInstancePath%', instance_path)

        # Write the updated content to the output file
        with open(output_path, 'w') as outfile:
            outfile.write(updated_content)
            
        return True
        
    except Exception as e:
        print(f"Error processing XDC file: {str(e)}")
        traceback.print_exc()
        return False


def main():
    """Main program entry point"""
    try:
        # Load configuration
        (input_path, output_path, clip_hdl_path, instantiation_path,
         clip_xdc_path, clip_instance_path, updated_xdc_path) = load_config()
        
        # Process XML
        success = process_clip_xml(input_path, output_path)
        
        # Generate entity instantiation
        entity_success = generate_entity_instantiation(clip_hdl_path, instantiation_path)
        success = success and entity_success
        
        # Process constraint file
        xdc_success = process_constraint_file(clip_xdc_path, updated_xdc_path, clip_instance_path)
        success = success and xdc_success
        
        if success:
            print("CLIP migration completed successfully.")
            return 0
        else:
            print("CLIP migration failed.")
            return 1
    
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())