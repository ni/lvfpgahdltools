# Copyright (c) 2025 National Instruments Corporation
# 
# SPDX-License-Identifier: MIT
#
import os                              # For file and directory operations
import sys                             # For command-line arguments and error handling
from dataclasses import dataclass      # For type-safe configuration storage
import configparser                    # For reading INI configuration files
import common                          # For shared utilities across tools

@dataclass
class FileConfiguration:
    """
    Configuration file paths and settings for target support generation
    
    This class centralizes all file paths and boolean settings used throughout
    the generation process, ensuring consistent configuration access and validation.
    """
    lv_target_plugin_folder: str  # Destination folder for plugin generation
    lv_target_install_folder: str  # Destination folder for plugin installation
    lv_target_name: str          # Name of the LabVIEW FPGA target (e.g., "PXIe-7903")


def load_config(config_path=None):
    """Load configuration from INI file"""
    if config_path is None:
        config_path = os.path.join(os.getcwd(), "projectsettings.ini")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
        
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # Default configuration
    files = FileConfiguration(
        lv_target_install_folder=None,
        lv_target_plugin_folder=None,
        lv_target_name=None
    )
    
    # Load settings if section exists
    if 'LVFPGATargetSettings' not in config:
        print(f"Error: LVFPGATargetSettings section missing in {config_path}")
        sys.exit(1)
        
    settings = config['LVFPGATargetSettings']
    
    # Load settings
    files.lv_target_install_folder = common.resolve_path(settings.get('LVTargetInstallFolder'))
    files.lv_target_plugin_folder = common.resolve_path(settings.get('LVTargetPluginFolder'))
    files.lv_target_name = settings.get('LVTargetName')
   
    return files

def is_admin():
    """
    Check if the script is running with administrator privileges
    
    Returns:
        bool: True if running as admin, False otherwise
    """
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    """
    Re-launch the current script with administrator privileges
    
    This function creates a new process with elevated privileges using
    the Windows shell's "runas" verb.
    """
    import ctypes
    import sys
    
    # Get the full path to the Python interpreter and script
    script = sys.argv[0]
    args = ' '.join(sys.argv[1:])
    
    print("Requesting administrator privileges...")
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        f'"{script}" {args}',
        None,
        1  # SW_SHOWNORMAL
    )

def install_lv_target_support():
    """
    Install LabVIEW Target Support files to the target installation folder
    
    This function:
    1. Loads configuration from the INI file
    2. Checks for administrator privileges (required for Program Files)
    3. Deletes the existing installation if present
    4. Copies all files from the plugin folder to the installation folder
    
    Administrator privileges are automatically requested if needed.
    """
    # Load configuration
    config = load_config()
    
    # Verify configuration
    if not config.lv_target_plugin_folder or not config.lv_target_install_folder:
        print("Error: Plugin folder or install folder not specified in configuration.")
        sys.exit(1)
    
    # Check if source exists
    if not os.path.exists(config.lv_target_plugin_folder):
        print(f"Error: Source plugin folder not found: {config.lv_target_plugin_folder}")
        sys.exit(1)
    
    # Check if we need admin rights (typically for Program Files)
    needs_admin = "program files" in config.lv_target_install_folder.lower()
    
    # If we need admin and don't have it, relaunch with elevated privileges
    if needs_admin and not is_admin():
        run_as_admin()
        return  # Exit current instance as the elevated instance will continue
    
    print(f"Installing LabVIEW Target '{config.lv_target_name}' files...")
    print(f"From: {config.lv_target_plugin_folder}")
    print(f"To: {config.lv_target_install_folder}")
    
    try:
        # Delete existing installation if it exists
        if os.path.exists(config.lv_target_install_folder):
            print(f"Removing existing installation from {config.lv_target_install_folder}...")
            
            # First try to delete individual files and folders
            for item in os.listdir(config.lv_target_install_folder):
                item_path = os.path.join(config.lv_target_install_folder, item)
                try:
                    if os.path.isfile(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        import shutil
                        shutil.rmtree(item_path)
                except Exception as e:
                    print(f"Warning: Could not remove {item_path}: {e}")
            
        # Create install directory if it doesn't exist
        os.makedirs(config.lv_target_install_folder, exist_ok=True)
        
        # Copy files from plugin folder to install folder
        import shutil
        
        def copy_recursively(src, dst):
            """Helper to copy files and directories recursively"""
            if os.path.isdir(src):
                # Create destination directory if it doesn't exist
                if not os.path.exists(dst):
                    os.makedirs(dst)
                
                # Copy each item in the directory
                for item in os.listdir(src):
                    s = os.path.join(src, item)
                    d = os.path.join(dst, item)
                    if os.path.isdir(s):
                        copy_recursively(s, d)
                    else:
                        shutil.copy2(s, d)
            else:
                # Direct file copy
                shutil.copy2(src, dst)
                
        # Copy everything from plugin folder to install folder
        copy_recursively(config.lv_target_plugin_folder, config.lv_target_install_folder)
        
        print(f"Successfully installed LabVIEW Target '{config.lv_target_name}' to {config.lv_target_install_folder}")
        
    except PermissionError:
        print("Error: Permission denied. Administrator privileges are required.")
        print("Try running this script as Administrator.")
        sys.exit(1)
    except Exception as e:
        print(f"Error during installation: {e}")
        sys.exit(1)

def main():
    """Main function to run the script"""
    install_lv_target_support()


if __name__ == "__main__":
    main()