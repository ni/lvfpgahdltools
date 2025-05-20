# Copyright (c) 2025 National Instruments Corporation
# 
# SPDX-License-Identifier: MIT
#
"""
Vivado Project Creation Tool

This script automates the creation and updating of Xilinx Vivado projects.
It handles file collection, dependency management, and TCL script generation to
streamline the FPGA development workflow.

The tool supports:
- Creating new Vivado projects with all required source files
- Updating existing projects with modified files
- Managing project dependencies
- Handling duplicate file detection
"""

import os
import shutil
import configparser
import argparse
import subprocess
from collections import defaultdict
from enum import Enum
import genlvtargetsupport


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

def get_vivado_project_files(config):
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
    # Get the lists of Vivado project files from the configuration
    lists_of_files = config.get('VivadoProjectSettings', 'VivadoProjectFilesLists').split()
    
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
        
    # Check for duplicate file names and log them
    find_and_log_duplicates(file_list)

    # Copy dependency files to the gathereddeps folder
    # Returns the file list with the files from githubdeps having new locations in gathereddeps
    file_list = copy_deps_files(file_list)

    # Sort the final file list
    file_list = sorted(file_list)
  
    return file_list

def has_spaces(file_path):
    """
    Checks if the given file path contains spaces.
    
    TCL scripts require special handling for paths containing spaces,
    so this helper function identifies paths needing additional quoting.
    
    Args:
        file_path (str): Path to check for spaces
        
    Returns:
        bool: True if the path contains spaces, False otherwise
    """
    return ' ' in file_path

def get_TCL_add_files_text(file_list, file_dir):
    """
    Generates TCL commands to add files to a Vivado project.
    
    Creates properly formatted 'add_files' TCL commands for each file in the list.
    It handles special cases such as:
    - Converting absolute paths to relative paths
    - Properly quoting paths with spaces
    - Removing Windows long path prefixes
    
    Args:
        file_list (list): List of files to include in the project
        file_dir (str): Base directory for computing relative paths
        
    Returns:
        str: Multi-line TCL commands to add all files
    """
    def strip_long_path_prefix(path):
        # Remove the \\?\ prefix if it exists (used for long paths on Windows)
        if os.name == 'nt' and path.startswith('\\\\?\\'):
            return path[4:]
        return path

    # Strip the \\?\ prefix and compute relative paths
    stripped_file_list = [strip_long_path_prefix(file) for file in file_list]
    replacement_list = [os.path.relpath(file, file_dir) for file in stripped_file_list]
    replacement_list = [f'"{file}"' if has_spaces(file) else file for file in replacement_list]

    # Generate TCL commands
    replacement_text = '\n'.join([f'add_files {{{file}}}' for file in replacement_list])
    return replacement_text

def replace_placeholders_in_file(file_path, new_file_path, add_files, project_name, top_entity):
    """
    Replaces placeholders in a template file with actual values.
    
    This function takes a TCL template file and substitutes key placeholders with
    project-specific values to create a customized Vivado TCL script.
    The main substitutions are:
    - ADD_FILES: List of files to add to the project
    - PROJ_NAME: Name of the Vivado project
    - TOP_ENTITY: Top-level VHDL entity name
    
    Args:
        file_path (str): Path to the template file
        new_file_path (str): Path where the generated file will be saved
        add_files (str): TCL commands to add files to the project
        project_name (str): Name of the Vivado project
        top_entity (str): Name of the top-level entity
    """
    with open(file_path, 'r') as file:
        file_contents = file.read()
    modified_contents = file_contents.replace('ADD_FILES', add_files)
    modified_contents = modified_contents.replace('PROJ_NAME', project_name)
    modified_contents = modified_contents.replace('TOP_ENTITY', top_entity)

    # Create the directory for the new file if it doesn't exist
    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

    with open(new_file_path, 'w') as file:
        file.write(modified_contents)

def find_and_log_duplicates(file_list):
    """
    Finds duplicate file names in the file list and logs their full paths to a file.
    
    Duplicate files can cause compilation issues in Vivado projects, as the tool may
    pick the wrong file version. This function identifies files with the same name but
    different paths, which typically indicates a potential conflict.
    
    The function:
    1. Groups files by base name (without path)
    2. Identifies duplicates (same name, different paths)
    3. Logs details to a file for analysis
    4. Raises an error to prevent proceeding with duplicates
    
    Args:
        file_list (list): List of file paths to check
        
    Raises:
        ValueError: If any duplicate filenames are found
    """
    file_dict = defaultdict(list)
    duplicates_found = False

    # Group files by their base name
    for file in file_list:
        file_name = os.path.basename(file)
        file_dict[file_name].append(file)

    # Check for duplicates
    for file_name, paths in file_dict.items():
        if len(paths) > 1:
            duplicates_found = True
            break

    output_file_path = os.path.join(os.getcwd(), 'duplicate_files.log')  

    # Delete any existing log file
    if os.path.exists(output_file_path):
        os.remove(output_file_path)

    # Log duplicates if found
    if duplicates_found:
        with open(output_file_path, 'w') as output_file:
            for file_name, paths in file_dict.items():
                if len(paths) > 1:
                    output_file.write(f"Duplicate file: {file_name}\n")
                    for path in paths:
                        output_file.write(f"  {path}\n")
                    output_file.write("\n")
        raise ValueError("Duplicate files found. Check the log file for details.")

def copy_deps_files(file_list):
    """
    Copies files with "githubdeps" in their path to the "objects/gathereddeps" folder.
    
    This centralizes external dependencies into the project's local structure, which:
    1. Ensures consistent file locations regardless of development environment
    2. Makes the project more portable across different machines
    3. Avoids dependencies on external repositories during build
    
    The function handles:
    - Creating the target directory if needed
    - Handling Windows long paths for deep directory structures
    - Setting proper file permissions
    - Error reporting for failed copy operations
    
    Args:
        file_list (list): Original list of file paths
        
    Returns:
        list: Updated file list with dependency files moved to local paths
        
    Raises:
        IOError: If any file copy operation fails
    """
    target_folder = os.path.join(os.getcwd(), 'objects/gathereddeps')
    os.makedirs(target_folder, exist_ok=True)

    new_file_list = []
    for file in file_list:
        # Handle long paths on Windows
        if os.name == 'nt':
            file = f"\\\\?\\{os.path.abspath(file)}"
            target_folder_long = f"\\\\?\\{os.path.abspath(target_folder)}"
        else:
            target_folder_long = target_folder

        if 'githubdeps' in file:
            target_path = os.path.join(target_folder_long, os.path.basename(file))
            if os.path.exists(target_path):
                os.chmod(target_path, 0o777)  # Make the file writable
            try:
                shutil.copy2(file, target_path)
                new_file_list.append(target_path)
            except Exception as e:
                raise IOError(f"Error copying file '{file}' to '{target_path}': {e}")
        else:
            new_file_list.append(file)
    return new_file_list

def run_command(command, cwd=None):
    """
    Runs a shell command and captures its output.
    
    This function provides a centralized way to execute external commands
    such as Vivado operations or system utilities. It:
    1. Prints the command before execution for debugging
    2. Captures both stdout and stderr
    3. Reports any errors that occur during execution
    
    Args:
        command (str): Command line to execute
        cwd (str, optional): Working directory for the command
        
    Returns:
        tuple: (return_code, stdout_content)
        
    Note:
        The command is run in shell mode, which allows for redirection and piping
        but can pose security risks if used with untrusted input.
    """
    print(command)
    result = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {command}")
        print(result.stderr)
    else:
        print(result.stdout)
    return result.returncode, result.stdout.strip()

class ProjectMode(Enum):
    """
    Enum defining the possible modes for project operations.
    
    NEW: Create a fresh project from scratch
    UPDATE: Update the files in an existing project
    
    This helps clarify the intent of operations and provide type safety
    compared to using raw strings.
    """
    NEW = "new"
    UPDATE = "update"

def create_project(mode: ProjectMode, config):
    """
    Creates or updates a Vivado project based on the specified mode.
    
    This function:
    1. Resolves paths to template and output TCL scripts
    2. Gathers all project files based on configuration
    3. Generates TCL commands to add these files
    4. Creates customized TCL scripts for project creation or updating
    5. Runs LabVIEW target support generation to create required files
    6. Executes Vivado in batch mode with the appropriate script
    
    The function handles two main operations:
    - Creating a new project from scratch (NEW mode)
    - Updating files in an existing project (UPDATE mode)
    
    Args:
        mode (ProjectMode): Operation mode (NEW or UPDATE)
        config (ConfigParser): Parsed configuration settings
        
    Raises:
        ValueError: If an unsupported mode is specified
    """
    current_dir = os.getcwd()
    new_proj_template_path = os.path.join(current_dir, 'TCL/CreateNewProjectTemplate.tcl')
    new_proj_path = os.path.join(current_dir, 'objects/TCL/CreateNewProject.tcl')    
    update_proj_template_path = os.path.join(current_dir, 'TCL/UpdateProjectFilesTemplate.tcl')
    update_proj_path = os.path.join(current_dir, 'objects/TCL/UpdateProjectFiles.tcl')    
    
    file_list = get_vivado_project_files(config)
    add_files = get_TCL_add_files_text(file_list, os.path.join(current_dir, 'TCL'))

    project_name = config.get('VivadoProjectSettings', 'VivadoProjectName')
    top_entity = config.get('VivadoProjectSettings', 'TopLevelEntity')

    # Replace placeholders in the template Vivado project scripts
    replace_placeholders_in_file(new_proj_template_path, new_proj_path, add_files, project_name, top_entity)
    replace_placeholders_in_file(update_proj_template_path, update_proj_path, add_files, project_name, top_entity)    

    # Run (or rerun) generate LV target support - this is needed to generate TheWindow.vhd that goes
    # into the objects directory and which gets used in the Vivado project
    genlvtargetsupport.gen_lv_target_support();

    vivado_project_path = os.path.join(os.getcwd(), "VivadoProject")
    if not os.path.exists(vivado_project_path):
        os.makedirs(vivado_project_path)   
    os.chdir("VivadoProject")

    # Check if the project file exists
    project_file_path = os.path.join(os.getcwd(), project_name + ".xpr")
    print(f"Project file path: {project_file_path}")

    vivado_path = os.getenv('XILINX')

    if vivado_path:
        # Determine the Vivado executable based on the operating system
        if os.name == 'nt':  # Windows
            vivado_executable = os.path.join(vivado_path, "bin", "vivado.bat")
        else:  # Linux or other OS
            vivado_executable = os.path.join(vivado_path, "bin", "vivado")

        if mode == ProjectMode.NEW:
            # Create a new project
            run_command(f'"{vivado_executable}" -mode batch -source {new_proj_path}', cwd=os.getcwd())
        elif mode == ProjectMode.UPDATE:
            # Update the existing project
            run_command(f'"{vivado_executable}" {project_name}.xpr -mode batch -source {update_proj_path}', cwd=os.getcwd())
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        os.chdir(current_dir)
    else:
        print("Environment variable 'XILINX' is not set.")

def create_project_handler(config, overwrite=False, updatefiles=False):
    """
    Handles command line arguments and performs the desired create Vivado project operation.
    
    This function serves as the main coordination point between command-line arguments
    and the project creation/updating functionality. It:
    1. Validates the combination of command-line arguments
    2. Checks if the project already exists
    3. Dispatches to the appropriate mode (NEW or UPDATE)
    
    The function implements the following logic:
    - With no flags: Create new project (fails if project exists)
    - With --overwrite: Create new project (overwrites existing)
    - With --updatefiles: Update existing project (fails if project doesn't exist)
    - With both flags: Error (invalid combination)
    
    Args:
        config (ConfigParser): Parsed configuration settings
        overwrite (bool): Whether to overwrite an existing project
        updatefiles (bool): Whether to update files in an existing project
        
    Raises:
        FileExistsError: If the project exists and neither overwrite nor update was requested
        FileNotFoundError: If update was requested but the project doesn't exist
        ValueError: If both overwrite and update flags were provided
    """
    project_name = config.get('VivadoProjectSettings', 'VivadoProjectName')

    project_file_path = os.path.join(os.getcwd(), "VivadoProject", project_name + ".xpr")
    print(f"Project file path: {project_file_path}")

    if not overwrite and not updatefiles:
        # User wants to create a new project
        if os.path.exists(project_file_path):
            # Throw error if the project already exists and they didn't ask to overwrite or update
            raise FileExistsError(
                f"The project file '{project_file_path}' already exists. Use the --overwrite or --updatefiles flag to modify the project."
            )
        else:
            create_project(ProjectMode.NEW, config)
    elif updatefiles and not overwrite:
        if not os.path.exists(project_file_path):
            # Throw error if the project does not exist and they want to update it
            raise FileNotFoundError(
                f"The project file '{project_file_path}' does not exist. Run without the --updatefiles flag to create a new project."
            )
        else:
            create_project(ProjectMode.UPDATE, config)
    elif overwrite and not updatefiles:
        # Overwrite the project by creating a new one
        create_project(ProjectMode.NEW, config)
    else:
        # Error case if both overwrite and updatefiles are set
        raise ValueError("Invalid combination of arguements.")

def main():
    """
    Main entry point for the script.
    
    This function:
    1. Sets up the command-line argument parser
    2. Loads the configuration file
    3. Calls the project handler with appropriate parameters
    
    Command-line arguments:
    --overwrite (-o): Force creation of a new project, overwriting existing
    --updatefiles (-u): Update files in an existing project
    
    Configuration is read from 'projectsettings.ini' in the current directory.
    
    Raises:
        FileNotFoundError: If the configuration file is missing
    """
    parser = argparse.ArgumentParser(description="Vivado Project Tools")
    parser.add_argument("--overwrite", "-o", action="store_true", help="Overwrite and create a new project")
    parser.add_argument("--updatefiles", "-u", action="store_true", help="Update files in the existing project")
    args = parser.parse_args()

    config_path = os.path.join(os.getcwd(), 'projectsettings.ini')
    # Check if the configuration file exists
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file '{config_path}' not found. Please ensure it exists in the current working directory.")
    config = configparser.ConfigParser()
    config.read(config_path)
    create_project_handler(config, overwrite=args.overwrite, updatefiles=args.updatefiles)


if __name__ == "__main__":
    main()