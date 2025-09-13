import os
import platform
import shutil
import zipfile
import urllib.request
import urllib.error
import subprocess
import json
from datetime import datetime

# --- PATHS & CONFIGURATION ---

RESOURCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
EXIFTOOL_EXE_NAME = "exiftool.exe" if platform.system() == "Windows" else "exiftool"
EXIFTOOL_PATH = os.path.join(RESOURCES_DIR, EXIFTOOL_EXE_NAME)

# --- Platform-specific configuration for subprocess to hide console window ---
SUBPROCESS_ARGS = {}
if platform.system() == "Windows":
    SUBPROCESS_ARGS['creationflags'] = subprocess.CREATE_NO_WINDOW

_exiftool_checked = False

# --- PUBLIC FUNCTIONS ---

def check_or_install_exiftool():
    """
    Checks if ExifTool is installed and up-to-date. A guard flag ensures
    this logic only ever runs once per application launch.
    """
    global _exiftool_checked
    if _exiftool_checked:
        return True

    os.makedirs(RESOURCES_DIR, exist_ok=True)
    
    print("Checking for ExifTool...")
    latest_version = _get_latest_version()
    if not latest_version:
        print("Could not check for the latest ExifTool version. Will use the existing version if available.")
        _exiftool_checked = True
        return os.path.exists(EXIFTOOL_PATH)

    installed_version = _get_installed_version()
    
    print(f"Latest version available: {latest_version}")
    print(f"Installed version: {installed_version or 'Not found'}")
    
    result = False
    if installed_version and installed_version >= latest_version:
        print(f"ExifTool v{installed_version} is up to date.")
        result = True
    else:
        print(f"Updating ExifTool from v{installed_version or 'N/A'} to v{latest_version}...")
        result = _download_and_extract_exiftool(latest_version)

    _exiftool_checked = True
    return result

def write_metadata(file_path: str, metadata: dict) -> bool:
    """
    Writes EXIF metadata to a single file using the ExifTool executable.
    """
    if not os.path.exists(file_path):
        print(f"[Error] File not found for metadata writing: {file_path}")
        return False

    # --- THIS IS THE CRITICAL FIX ---
    # Changed from "-overwrite_original" to "-overwrite_original_in_place"
    # This is much safer for proprietary RAW file formats.
    args = [EXIFTOOL_PATH, "-overwrite_original_in_place"]
    
    for tag, value in metadata.items():
        if value:
            # Add "-all=" to prevent ExifTool from creating new tags in unknown groups
            args.append(f"-all:{tag}={value}")
    
    if len(args) <= 2:
        return True

    args.append(file_path)

    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, **SUBPROCESS_ARGS)
        if result.returncode != 0:
            # ExifTool often returns warnings (code 1) even on success, so we check stderr.
            # We will consider it a failure only if there is something in stderr.
            if result.stderr:
                print(f"[ExifTool Error] For file {os.path.basename(file_path)}: {result.stderr.strip()}")
                return False
        # If no stderr, we can assume it was successful or had minor warnings.
        return True
    except Exception as e:
        print(f"[Exception] Failed to write metadata: {e}")
        return False

def get_shot_date(file_path: str) -> datetime | None:
    # This function is unchanged
    if not os.path.exists(file_path):
        return None
    try:
        cmd = [EXIFTOOL_PATH, "-j", "-DateTimeOriginal", "-CreateDate", file_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, **SUBPROCESS_ARGS)
        metadata = json.loads(result.stdout)[0]
        date_str = metadata.get("DateTimeOriginal") or metadata.get("CreateDate")
        if date_str:
            return datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
    except Exception as e:
        print(f"[Exif Error] Could not read shot date from {os.path.basename(file_path)}: {e}")
    return None

# --- INTERNAL HELPER FUNCTIONS ---
# All internal functions (_get_installed_version, _get_latest_version, etc.) are unchanged
def _get_installed_version():
    if not os.path.exists(EXIFTOOL_PATH):
        return None
    try:
        output = subprocess.check_output([EXIFTOOL_PATH, "-ver"], text=True, **SUBPROCESS_ARGS).strip()
        return output
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def _get_latest_version():
    url = "https://exiftool.org/ver.txt"
    try:
        with urllib.request.urlopen(url) as response:
            return response.read().decode("utf-8").strip()
    except Exception as e:
        print(f"Error fetching latest ExifTool version: {e}")
        return None

def _download_and_extract_exiftool(version):
    zip_path = os.path.join(RESOURCES_DIR, "exiftool.zip")
    extract_path = os.path.join(RESOURCES_DIR, f"exiftool-temp-{version}")
    zip_url = f"https://exiftool.org/exiftool-{version}_64.zip"
    try:
        print(f"Downloading ExifTool v{version} from {zip_url}...")
        urllib.request.urlretrieve(zip_url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)
        binary_moved = False
        for root, _, files in os.walk(extract_path):
            for file in files:
                if file.lower().startswith("exiftool") and file.lower().endswith(".exe"):
                    shutil.move(os.path.join(root, file), EXIFTOOL_PATH)
                    binary_moved = True
                    break
            if binary_moved: break
        if not binary_moved:
            raise FileNotFoundError("Could not find exiftool.exe in the extracted files.")
        support_dir_moved = False
        for root, dirs, _ in os.walk(extract_path):
            for dir_name in dirs:
                if dir_name.lower() == "exiftool_files":
                    src = os.path.join(root, dir_name)
                    dst = os.path.join(RESOURCES_DIR, dir_name)
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.move(src, dst)
                    support_dir_moved = True
                    break
            if support_dir_moved: break
        print(f"ExifTool v{version} installed successfully.")
        return True
    except Exception as e:
        print(f"Error during ExifTool installation: {e}")
        return False
    finally:
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)
        if os.path.exists(zip_path):
            os.remove(zip_path)
