# MIT License
# 
# Copyright (c) 2025 National Instruments Corporation
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
# to whom the Software is furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
# FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
#
# githubvisible=true

import os
import shutil
import configparser
import argparse
import subprocess
from collections import defaultdict
from mako.template import Template
import zipfile
from enum import Enum

def list_all_files(folder_path):
    """
    Lists all files in a folder and its subfolders that match specific extensions.
    This is used to gather relevant files (e.g., .vhd, .xdc, .edf) for Vivado projects.
    """
    all_files = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.vhd') or file.endswith('.xdc') or file.endswith('edf'):  # Only include specific file types
                all_files.append(fix_file_slashes(os.path.join(root, file)))
    return all_files

def add_files_to_list(file_list, files):
    """
    Adds additional files to the file list.
    This is used to include specific files that are not part of the folder-based inclusion.
    """
    for file in files:
        file_list.append(file)  
    return file_list

def fix_file_slashes(path):
    """
    Converts backslashes to forward slashes in file paths.
    This ensures compatibility across platforms (e.g., Windows and Linux).
    """
    return path.replace('\\', '/')

def remove_files_from_list(list_a, list_b):
    """
    Removes all files in list_b from list_a.
    This is used to exclude specific files or folders from the final file list.
    """
    set_b = set(list_b)
    return [file for file in list_a if file not in set_b]

def get_vivado_project_files(config):
    """
    Processes the configuration to generate the list of files for the Vivado project.
    This also identifies duplicates and handles dependencies.
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
                        file_list.append(fix_file_slashes(line))
        else:
            raise FileNotFoundError(f"File list path '{file_list_path}' does not exist.")
        
    # Check for duplicate file names and log them
    find_and_log_duplicates(file_list)

    # Copy dependency files to the gathereddeps folder
    # Retuns the file list with the files from githubdeps having new locations in gathereddeps
    file_list = copy_deps_files(file_list)

    # Sort the final file list
    file_list = sorted(file_list)
  
    return file_list

def has_spaces(file_path):
    """
    Checks if the given file path contains spaces.
    This is used to ensure proper handling of file paths in Vivado TCL scripts.
    """
    return ' ' in file_path

def get_TCL_add_files_text(file_list, file_dir):
    """
    Generates TCL commands to add files to a Vivado project.
    This converts file paths to relative paths and ensures proper quoting for paths with spaces.
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
    This is used to generate Vivado TCL scripts for creating or updating projects.
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
    Raises an error if duplicates are found to prevent issues in the Vivado project.
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
    This ensures that dependency files are gathered in a central location for the Vivado project.

    Returns the file list of the locations of the copied files in objects/gathereddeps
    This returned file list is used to generate the TCL add_files text.
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
    This is used to execute Vivado commands or other system commands.
    """
    print(command)
    result = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {command}")
        print(result.stderr)
    else:
        print(result.stdout)
    return result.returncode, result.stdout.strip()

def extract_deps_from_zip(deps_folder, deps_zip_file):
    """
    Extracts the contents of a zip file into the specified folder.
    This is used to manage dependencies for the Vivado project.
    """
    # Handle long paths on Windows
    if os.name == 'nt':
        deps_zip_file = f"\\\\?\\{os.path.abspath(deps_zip_file)}"
        deps_folder = f"\\\\?\\{os.path.abspath(deps_folder)}"

    # Check if the zip file exists
    if not os.path.exists(deps_zip_file):
        print(f"DepsZipFile '{deps_zip_file}' does not exist.")
        return

    # Extract the zip file
    try:
        # Delete everything in the target directory before extracting
        shutil.rmtree(deps_folder, ignore_errors=True)
        shutil.unpack_archive(deps_zip_file, deps_folder, 'zip')
        print(f"Extracted '{deps_zip_file}' into '{deps_folder}'.")
    except Exception as e:
        print(f"Error extracting '{deps_zip_file}': {e}")

#####################################################################
# TEMPORARY FUNCTION TO GET THE WINDOW MAKO TEMPLATE RENDERED
#
# This will be replaced once we have the workflow for migrating CLIP
# and generating the LV FPGA project files.
#######################################################################
def render_mako_template(template_path):
    """Render a Mako template and write the output to objects directory
    
    Args:
        template_path: Path to template file
        
    Returns:
        bool: True if successful, False otherwise
    """
    template_dir = os.path.dirname(template_path)
    template_file = os.path.basename(template_path)
    output_dir = os.path.join(os.getcwd(), "objects/rtl-lvfpga/lvgen")
    output_file = template_file.replace('.mako', '')
    output_path = os.path.join(output_dir, output_file) 

    print(f"Template directory: {template_dir}")
    print(f"Template file: {template_file}")
    print(f"Output directory: {output_dir}")
    print(f"Output file: {output_file}")
    print(f"Output path: {output_path}")
    
    if os.path.exists(template_path):
        os.makedirs(output_dir, exist_ok=True)
        with open(template_path, 'r') as f:
            template = Template(f.read())
        output_text = template.render(
            include_clip_socket=True,
            include_custom_io=False,
            custom_signals=[]
        )
        with open(output_path, 'w') as f:
            f.write(output_text)

class ProjectMode(Enum):
    NEW = "new"
    UPDATE = "update"

def create_project(mode: ProjectMode, config):
    """
    Creates or updates a Vivado project based on the specified mode.
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

    # TEMPORARY: Render the Mako template for TheWindow.vhd
    render_mako_template(os.path.join(current_dir, 'rtl-lvfpga/lvgen/TheWindow.vhd.mako'))

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
    Parses command-line arguments and executes the requested function.
    """
    parser = argparse.ArgumentParser(description="Vivado Project Tools")
    parser.add_argument("function", choices=["create_project", "extract_deps"], help="Function to execute")
    parser.add_argument("--overwrite", "-o", action="store_true", help="Overwrite and create a new project")
    parser.add_argument("--updatefiles", "-u", action="store_true", help="Update files in the existing project")
    args = parser.parse_args()


    if args.function == "create_project":
        config_path = os.path.join(os.getcwd(), 'vivadoprojectsettings.ini')
        # Check if the configuration file exists
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file '{config_path}' not found. Please ensure it exists in the current working directory.")
        config = configparser.ConfigParser()
        config.read(config_path)
        create_project_handler(config, overwrite=args.overwrite, updatefiles=args.updatefiles)
    elif args.function == "extract_deps":
        deps_folder = "githubdeps"
        deps_zip_file = "flexriodeps.zip"
        extract_deps_from_zip(deps_folder, deps_zip_file)

if __name__ == "__main__":
    main()