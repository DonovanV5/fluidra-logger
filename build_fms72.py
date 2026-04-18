import os
import shutil
import subprocess
import sys
from pathlib import Path

def build_executable():
    print("Starting build process for Fluidra Manufacturing Solution v7.2...")
    
    # Define paths
    base_dir = Path(__file__).parent.absolute()
    script = 'Fluidra_Manufacturing_Solutionv7.2.py'
    name = 'FMS_v7.2'
    
    # Create necessary directories
    dist_dir = base_dir / 'dist'
    build_dir = base_dir / 'build'
    
    # Clean previous builds
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)
        
    dist_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)
    
    # Collect data files
    data_files = []
    
    # Add zpl_presets directory
    zpl_presets_path = base_dir / 'zpl_presets'
    if zpl_presets_path.exists():
        for root, _, files in os.walk(zpl_presets_path):
            for file in files:
                src_path = Path(root) / file
                rel_path = src_path.relative_to(base_dir)
                dest_dir = str(rel_path.parent)
                data_files.append((str(src_path), dest_dir))
    
    # Add config directory
    config_path = base_dir / 'config'
    if config_path.exists():
        for root, _, files in os.walk(config_path):
            for file in files:
                src_path = Path(root) / file
                rel_path = src_path.relative_to(base_dir)
                dest_dir = str(rel_path.parent)
                data_files.append((str(src_path), dest_dir))
    
    # Add individual files
    additional_files = [
        'barcode_log.xlsx',
        'pumpline-logger.json',
        'config.json',
        'logo.png',
        'screenshot.png'
    ]
    
    for file in additional_files:
        file_path = base_dir / file
        if file_path.exists():
            data_files.append((str(file_path), '.'))
    
    # Format data files for PyInstaller
    data_args = []
    for src, dst in data_files:
        data_args.append('--add-data')
        data_args.append(f"{os.path.normpath(src)};{os.path.normpath(dst)}")
    
    # Build the command
    cmd = [
        'pyinstaller',
        '--name', name,
        '--onefile',
        '--windowed',
        '--distpath', str(dist_dir),
        '--workpath', str(build_dir / 'work'),
        '--specpath', str(build_dir),
        '--clean',
        '--noconfirm'
    ]
    
    # Add data files
    cmd.extend(data_args)
    
    # Add hidden imports
    hidden_imports = [
        'pandas', 'numpy', 'openpyxl', 'requests', 'zeep', 'PIL', 'PIL._tkinter_finder',
        'tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.ttk', 'tkinter.scrolledtext',
        'gspread', 'oauth2client', 'httplib2', 'googleapiclient', 'google.oauth2', 'google.auth',
        'google.auth.transport.requests', 'google_auth_oauthlib', 'google.oauth2.service_account',
        'pyzbar', 'pyzbar.pyzbar', 'pyzbar.wrapper', 'pyzbar.locations', 'pyzbar.images',
        'pyzbar.scripts', 'pyzbar.tests', 'pyzbar.zbar_library', 'pyzbar.wrapper', 'pyzbar.locations',
        'pyzbar.images', 'pyzbar.scripts', 'pyzbar.tests', 'pyzbar.zbar_library', 'pyzbar.wrapper',
        'pyzbar.locations', 'pyzbar.images', 'pyzbar.scripts', 'pyzbar.tests', 'pyzbar.zbar_library'
    ]
    
    for imp in hidden_imports:
        cmd.extend(['--hidden-import', imp])
    
    # Add the script
    cmd.append(str(base_dir / script))
    
    print("Running command:", ' '.join(cmd))
    
    # Run the command
    try:
        subprocess.run(cmd, check=True)
        print("\nBuild completed successfully!")
        print(f"The executable is located in: {dist_dir}")
        
        # Copy additional files to dist directory
        print("\nCopying additional files to dist directory...")
        for src, dst in data_files:
            src_path = Path(src)
            dst_path = dist_dir / dst / src_path.name
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_file():
                shutil.copy2(src_path, dst_path)
                print(f"Copied: {src_path} -> {dst_path}")
        
        print("\nBuild and file copy completed successfully!")
        print(f"The executable and all required files are in: {dist_dir}")
        print("\nTo distribute the application:")
        print(f"1. Copy the entire '{dist_dir.name}' folder to the target computer")
        print(f"2. Run '{name}.exe' from within that folder")
        
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed with error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller not found. Installing required packages...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Check for other required packages
    required_packages = [
        'pandas', 'numpy', 'openpyxl', 'requests', 'zeep', 'Pillow',
        'customtkinter', 'gspread', 'google-api-python-client', 'oauth2client',
        'pyzbar', 'pywin32', 'python-dotenv'
    ]
    
    print("Checking for required packages...")
    for package in required_packages:
        try:
            __import__(package.split('==')[0])
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    
    # Start the build process
    build_executable()
