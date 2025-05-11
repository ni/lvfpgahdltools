# githubvisible=true
import csv
import os
import sys
import xml.etree.ElementTree as ET
from mako.template import Template
from xml.dom.minidom import parseString
from dataclasses import dataclass
import configparser

# Constants
BOARDIO_WRAPPER_NAME = "BoardIO"
DOCUMENT_ROOT_PREFIX = "#{{document-root}}/Stock/"
HIERARCHY_TEXT = "AppletonWindow"
DEFAULT_CLOCK_FREQ = "250M"
DEFAULT_ACCURACY_PPM = "100"
DEFAULT_JITTER_PS = "250"

# Data type prototypes mapping
DATA_TYPE_PROTOTYPES = {
    "FXP": DOCUMENT_ROOT_PREFIX + "FXPDigital{direction}",
    "Boolean": DOCUMENT_ROOT_PREFIX + "boolDigital{direction}",
    "U8": DOCUMENT_ROOT_PREFIX + "u8Digital{direction}",
    "U16": DOCUMENT_ROOT_PREFIX + "u16Digital{direction}",
    "U32": DOCUMENT_ROOT_PREFIX + "u32Digital{direction}",
    "U64": DOCUMENT_ROOT_PREFIX + "u64Digital{direction}",
    "I8": DOCUMENT_ROOT_PREFIX + "i8Digital{direction}",
    "I16": DOCUMENT_ROOT_PREFIX + "i16Digital{direction}",
    "I32": DOCUMENT_ROOT_PREFIX + "i32Digital{direction}",
    "I64": DOCUMENT_ROOT_PREFIX + "i64Digital{direction}",
}

@dataclass
class FileConfiguration:
    """Configuration file paths and settings"""
    custom_signals_csv: str
    boardio_output: str
    clock_output: str
    window_vhdl_template: str
    window_vhdl_output: str
    target_xml_template: str
    target_xml_output: str
    include_clip_socket_ports: bool
    include_custom_io: bool


def parse_bool(value, default=False):
    """Parse string to boolean"""
    if value is None:
        return default
    return value.lower() in ('true', 'yes', '1')


def load_config(config_path=None):
    """Load configuration from INI file"""
    if config_path is None:
        config_path = os.path.join(os.getcwd(), "vivadoprojectsettings.ini")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
        
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # Default configuration
    files = FileConfiguration(
        custom_signals_csv=None,
        boardio_output=None,
        clock_output=None,
        window_vhdl_template=None,
        window_vhdl_output=None,
        target_xml_template=None,
        target_xml_output=None,
        include_clip_socket_ports=True,
        include_custom_io=True
    )
    
    # Load settings if section exists
    if 'LVFPGATargetSettings' not in config:
        print(f"Error: LVFPGATargetSettings section missing in {config_path}")
        sys.exit(1)
        
    settings = config['LVFPGATargetSettings']
    
    # Load path settings
    files.custom_signals_csv = settings.get('CustomSignalsCSV')
    files.boardio_output = settings.get('BoardIOXML')
    files.clock_output = settings.get('ClockXML')
    files.window_vhdl_template = settings.get('WindowVhdlTemplate')
    files.window_vhdl_output = settings.get('WindowVhdlOutput')
    files.target_xml_template = settings.get('TargetXMLTemplate')
    files.target_xml_output = settings.get('TargetXMLOutput')
    
    # Load boolean settings
    files.include_clip_socket_ports = parse_bool(settings.get('IncludeCLIPSocketInTarget'), True)
    files.include_custom_io = parse_bool(settings.get('IncludeCustomIOInTarget'), True)
    
    # Verify required paths
    required_fields = [
        'custom_signals_csv', 'boardio_output', 'clock_output',
        'window_vhdl_template', 'window_vhdl_output', 
        'target_xml_template', 'target_xml_output'
    ]
    
    missing = [field for field in required_fields if getattr(files, field) is None]
    if missing:
        missing_settings = [field.replace('_', ' ').title().replace(' ', '') for field in missing]
        print(f"Error: Missing required settings in INI file: {', '.join(missing_settings)}")
        sys.exit(1)
    
    return files


def ensure_dir_exists(filepath):
    """Create directory if it doesn't exist"""
    output_dir = os.path.dirname(filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"Created directory: {output_dir}")


def write_tree_to_xml(root, output_file):
    """Write an XML tree to a formatted XML file"""
    ensure_dir_exists(output_file)
    
    rough_string = ET.tostring(root, encoding="utf-8")
    pretty_xml = parseString(rough_string).toprettyxml(indent="  ")
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
        
    print(f"XML written to {output_file}")


def get_or_create_resource_list(parent, name):
    """Find or create a ResourceList element"""
    for child in parent.findall("ResourceList"):
        if child.attrib.get("name") == name:
            return child
    return ET.SubElement(parent, "ResourceList", {"name": name})


def create_boardio_structure():
    """Create the initial boardio XML structure"""
    boardio_top = ET.Element("boardio")
    boardio_resources = ET.SubElement(boardio_top, "ResourceList", {"name": BOARDIO_WRAPPER_NAME})
    return boardio_top, boardio_resources


def create_clocklist_structure():
    """Create the initial ClockList XML structure"""
    clock_list_top = ET.Element("ClockList")
    hierarchy = ET.SubElement(clock_list_top, "HierarchyForDerivedClockPeriodConstraints")
    hierarchy.text = HIERARCHY_TEXT
    return clock_list_top


def map_datatype_to_vhdl(data_type):
    """Map CSV data type to VHDL data type"""
    if data_type == "Boolean":
        return "std_logic"
    
    elif data_type.startswith(("U", "I")):
        # Handle U8, U16, U32, U64, I8, I16, I32, I64
        bit_width = int(data_type[1:])
        return f"std_logic_vector({bit_width - 1} downto 0)"
    
    elif data_type.startswith("FXP"):
        # Handle FXP type
        try:
            params = data_type.split('(')[1].split(')')[0].split(',')
            word_length = int(params[0])
            return f"std_logic_vector({word_length - 1} downto 0)"
        except:
            return "std_logic_vector(31 downto 0)"  # Default if parsing fails
    
    elif data_type.startswith("Array"):
        # Handle Array type
        try:
            array_size = int(data_type.split('[')[1].split(']')[0])
            element_type = data_type.split('<')[1].split('>')[0]
            
            # Determine element width
            if element_type == "Boolean":
                element_width = 1
            elif element_type.startswith(("U", "I")):
                element_width = int(element_type[1:])
            else:
                element_width = 32
            
            total_width = array_size * element_width
            return f"std_logic_vector({total_width - 1} downto 0)"
        except Exception as e:
            print(f"Error parsing array type: {data_type}, error: {e}")
            return "std_logic_vector(31 downto 0)"
    
    else:
        return "std_logic"  # Default type


def generate_xml_from_csv(csv_path, boardio_output_path, clock_output_path):
    """Generate boardio XML and clock XML files from CSV data"""
    try:
        boardio_top, boardio_resources = create_boardio_structure()
        clock_list_top = create_clocklist_structure()
        
        with open(csv_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                lv_name = row["LVName"]
                hdl_name = row["HDLName"]
                direction = row["Direction"]
                signal_type = row["SignalType"]
                data_type = row["DataType"]
                use_in_scl = row["UseInLabVIEWSingleCycleTimedLoop"]
                required_clock_domain = row["RequiredClockDomain"]
                
                # Convert direction format
                clip_direction = {"output": "ToCLIP", "input": "FromCLIP"}.get(direction, direction)
                
                # Handle clock signals
                is_clock = signal_type.lower() == "clock" and clip_direction == "FromCLIP"
                
                if is_clock:
                    # Process clock signal
                    original_name = lv_name[10:].replace("\\", ".")
                    clock = ET.SubElement(clock_list_top, "Clock", {"name": original_name})
                    
                    # Add clock properties
                    freq = ET.SubElement(clock, "FreqInHertz")
                    ET.SubElement(freq, "DefaultValue").text = DEFAULT_CLOCK_FREQ
                    
                    accuracy = ET.SubElement(clock, "AccuracyInPPM")
                    ET.SubElement(accuracy, "DefaultValue").text = DEFAULT_ACCURACY_PPM
                    
                    jitter = ET.SubElement(clock, "JitterInPicoSeconds")
                    ET.SubElement(jitter, "DefaultValue").text = DEFAULT_JITTER_PS
                    
                    ET.SubElement(clock, "GeneratePeriodConstraints").text = "false"
                else:
                    # Process IO signal
                    original_name = lv_name[10:].replace("\\", ".")
                    parts = original_name.split(".")
                    
                    # Create resource hierarchy
                    current_parent = boardio_resources
                    for part in parts[:-1]:
                        current_parent = get_or_create_resource_list(current_parent, part)
                    
                    # Create IO resource
                    io_resource = ET.SubElement(current_parent, "IOResource", {"name": lv_name})
                    ET.SubElement(io_resource, "VHDLName").text = hdl_name
                    
                    if required_clock_domain:
                        ET.SubElement(io_resource, "RequiredClockDomain").text = required_clock_domain
                    
                    if use_in_scl:
                        ET.SubElement(io_resource, "UseInSingleCycleTimedLoop").text = use_in_scl
                    
                    # Set direction and prototype
                    io_direction = {
                        "ToCLIP": "OutputWithoutReadback",
                        "FromCLIP": "Input"
                    }.get(clip_direction, "Unknown")
                    
                    # Handle data type and prototype
                    data_type_name = data_type.split('(')[0] if '(' in data_type else data_type
                    
                    if data_type_name in DATA_TYPE_PROTOTYPES:
                        prototype = DATA_TYPE_PROTOTYPES[data_type_name].format(direction=io_direction)
                        io_resource.set("prototype", prototype)
                        
                        # Handle FXP attributes
                        if data_type_name == "FXP" and '(' in data_type:
                            try:
                                parts = data_type.split('(')[1].split(')')[0].split(',')
                                io_resource.set("wordLength", parts[0])
                                io_resource.set("integerWordLength", parts[1])
                                io_resource.set("unsigned", "true" if "Unsigned" in data_type else "false")
                            except Exception as e:
                                print(f"Error parsing FXP parameters for {lv_name}: {e}")
                    else:
                        io_resource.set("prototype", f"{DOCUMENT_ROOT_PREFIX}unknownSignal")
        
        # Write the XML files
        write_tree_to_xml(boardio_top, boardio_output_path)
        write_tree_to_xml(clock_list_top, clock_output_path)
        
    except Exception as e:
        print(f"Error generating XML from CSV: {e}")
        sys.exit(1)


def generate_vhdl_from_csv(csv_path, template_path, output_path, include_clip_socket):
    """Generate VHDL from CSV using a Mako template"""
    try:
        # Read signals from CSV
        signals = []
        with open(csv_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row["SignalType"].lower() == "clock":
                    continue
                    
                signals.append({
                    'name': row["HDLName"],
                    'direction': "in" if row["Direction"] == "input" else "out",
                    'type': map_datatype_to_vhdl(row["DataType"]),
                    'lv_name': row["LVName"]
                })
        
        # Render template
        with open(template_path, 'r') as f:
            template = Template(f.read())
            
        output_text = template.render(
            custom_signals=signals,
            include_clip_socket=include_clip_socket
        )
        
        # Write output file
        ensure_dir_exists(output_path)
        with open(output_path, 'w') as f:
            f.write(output_text)
            
        print(f"Generated VHDL file: {output_path}")
            
    except Exception as e:
        print(f"Error generating VHDL from CSV: {e}")
        sys.exit(1)


def generate_target_xml(template_path, output_path, include_clip_socket, include_custom_io, boardio_path, clock_path):
    """Generate Target XML from Mako template"""
    try:
        # Extract filenames
        boardio_filename = os.path.basename(boardio_path)
        clock_filename = os.path.basename(clock_path)
        
        # Render template
        with open(template_path, 'r') as f:
            template = Template(f.read())
            
        output_text = template.render(
            include_clip_socket=include_clip_socket,
            include_custom_io=include_custom_io,
            custom_boardio=boardio_filename,
            custom_clock=clock_filename
        )
        
        # Write output file
        ensure_dir_exists(output_path)
        with open(output_path, 'w') as f:
            f.write(output_text)
            
        print(f"Generated Target XML file: {output_path}")
            
    except Exception as e:
        print(f"Error generating Target XML: {e}")
        sys.exit(1)


def main():
    """Generate target support files"""
    try:
        # Load configuration
        config = load_config()
        
        # Generate all files
        print(f"Generating support files from {config.custom_signals_csv}...")
        
        generate_xml_from_csv(
            config.custom_signals_csv, 
            config.boardio_output, 
            config.clock_output
        )
        
        generate_vhdl_from_csv(
            config.custom_signals_csv, 
            config.window_vhdl_template, 
            config.window_vhdl_output,
            config.include_clip_socket_ports
        )
        
        generate_target_xml(
            config.target_xml_template, 
            config.target_xml_output,
            config.include_clip_socket_ports,
            config.include_custom_io,
            config.boardio_output, 
            config.clock_output
        )
        
        print("Target support file generation complete.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()