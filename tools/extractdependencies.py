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

import os
import shutil

def extract_deps_from_zip(deps_folder):
    """
    Extracts the contents of zip files into the specified folder.
    
    If deps_zip_file is provided, only that file is extracted.
    Otherwise, all .zip files in the current directory are extracted.
    
    :param deps_folder: Target folder where zip contents will be extracted
    :param deps_zip_file: Optional specific zip file to extract
    """
    # Handle long paths on Windows
    if os.name == 'nt':
        deps_folder_long = f"\\\\?\\{os.path.abspath(deps_folder)}"
    else:
        deps_folder_long = deps_folder

    # Delete the target directory once before extracting any files
    print(f"Cleaning target directory: {deps_folder}")
    shutil.rmtree(deps_folder_long, ignore_errors=True)
    os.makedirs(deps_folder_long, exist_ok=True)
    
    # Find all zip files in the current directory
    zip_files = [f for f in os.listdir() if f.endswith('.zip')]
        
    # Extract each zip file
    for zip_file in zip_files:            
        try:
            print(f"Extracting '{zip_file}' into '{deps_folder}'...")
            shutil.unpack_archive(zip_file, deps_folder_long, 'zip')
            print(f"Successfully extracted '{zip_file}'")
        except Exception as e:
            print(f"Error extracting '{zip_file}': {e}")
            
    # Check if any files were extracted
    extracted_files = os.listdir(deps_folder)
    print(f"Extracted {len(extracted_files)} items to {deps_folder}")


def main():
    """
    Main entry point for the script.
    """
    deps_folder = "githubdeps"
    extract_deps_from_zip(deps_folder)

if __name__ == "__main__":
    main()