import os
import platform
import shutil
import subprocess
import json
from datetime import datetime

from PySide6.QtCore import QSettings

import paths

# --- PATHS & CONFIGURATION ---

RESOURCES_DIR = paths.RESOURCES_DIR
EXIFTOOL_EXE_NAME = "exiftool.exe" if platform.system() == "Windows" else "exiftool"
BUNDLED_EXIFTOOL_PATH = os.path.join(RESOURCES_DIR, EXIFTOOL_EXE_NAME)

# Kept for backwards compatibility with any code that still references the
# old constant name directly (e.g. error messages).
EXIFTOOL_PATH = BUNDLED_EXIFTOOL_PATH

# The version of ExifTool bundled in resources/ for this release. This is
# informational only (shown in status messages) -- there is no runtime
# download or update check. To ship a newer version: download the official
# release zip from https://exiftool.org (mirrored via SourceForge), extract
# it, and replace resources/exiftool.exe + resources/exiftool_files/ in the
# project, then bump this constant to match.
PINNED_BUNDLED_VERSION = "13.59"

SETTINGS_ORG = "PhotoTagger"
SETTINGS_APP = "FilmTagger"
CUSTOM_PATH_KEY = "exiftoolCustomPath"

# --- Platform-specific configuration for subprocess to hide console window ---
SUBPROCESS_ARGS = {}
if platform.system() == "Windows":
    SUBPROCESS_ARGS['creationflags'] = subprocess.CREATE_NO_WINDOW

SUBPROCESS_TIMEOUT = 15  # seconds, for calls to the exiftool binary itself

# --- State ---
_resolved_exiftool_path = None  # cached once a working path is found this session
_exiftool_checked = False       # guards against repeating the resolution flow


# --- SETTINGS: CUSTOM PATH ---

def get_custom_path() -> str:
    """Returns the user-configured custom ExifTool path, or '' if unset."""
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    return settings.value(CUSTOM_PATH_KEY, "", type=str)


def set_custom_path(path: str):
    """
    Saves a user-configured custom ExifTool path and forces re-resolution
    on the next call to resolve_exiftool_path() / ensure_exiftool_available().
    Pass an empty string to clear the override.
    """
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    settings.setValue(CUSTOM_PATH_KEY, path)
    global _resolved_exiftool_path, _exiftool_checked
    _resolved_exiftool_path = None
    _exiftool_checked = False


def _get_install_hint() -> str:
    """Returns a platform-appropriate install instruction for ExifTool."""
    system = platform.system()
    if system == "Darwin":
        return "install it with Homebrew (brew install exiftool)"
    if system == "Linux":
        return (
            "install it with your distro's package manager "
            "(e.g. 'sudo apt install libimage-exiftool-perl' on Debian/Ubuntu, "
            "'sudo dnf install perl-Image-ExifTool' on Fedora, or "
            "'sudo pacman -S perl-image-exiftool' on Arch)"
        )
    return "install it from https://exiftool.org"


# --- PUBLIC: RESOLUTION ---

def _is_valid_exiftool(path: str) -> bool:
    """Checks that `path` points to a file that actually runs as ExifTool."""
    if not path or not os.path.isfile(path):
        return False
    try:
        subprocess.check_output(
            [path, "-ver"], text=True, timeout=SUBPROCESS_TIMEOUT, **SUBPROCESS_ARGS
        )
        return True
    except Exception:
        return False


def resolve_exiftool_path():
    """
    Resolves a working ExifTool executable using a fallback chain:
      1. User-configured custom path (Settings)
      2. A system-wide install found on PATH
      3. The bundled, pinned copy in resources/

    Returns the resolved path (str), or None if nothing usable was found.
    """
    global _resolved_exiftool_path

    if _resolved_exiftool_path and _is_valid_exiftool(_resolved_exiftool_path):
        return _resolved_exiftool_path

    custom = get_custom_path()
    if custom and _is_valid_exiftool(custom):
        _resolved_exiftool_path = custom
        return custom

    system_path = shutil.which("exiftool")
    if system_path and _is_valid_exiftool(system_path):
        _resolved_exiftool_path = system_path
        return system_path

    if _is_valid_exiftool(BUNDLED_EXIFTOOL_PATH):
        _resolved_exiftool_path = BUNDLED_EXIFTOOL_PATH
        return BUNDLED_EXIFTOOL_PATH

    _resolved_exiftool_path = None
    return None


def get_active_exiftool_path():
    """Returns the currently cached, resolved exiftool path (may be None)."""
    return _resolved_exiftool_path


def ensure_exiftool_available():
    """
    Checks whether a working ExifTool is available via the fallback chain
    (custom path / system PATH / bundled copy). There is no runtime
    download -- the bundled copy is pinned and shipped with the app (see
    PINNED_BUNDLED_VERSION above), which also removes the network
    dependency and the fragile "download and extract a .zip" logic that
    used to run on first launch.

    This function NEVER raises and never implies the app should quit -- it
    just reports what it found so the caller can degrade gracefully (e.g.
    disable metadata features) instead of treating a missing ExifTool as
    fatal.

    Returns (success: bool, message: str).
    """
    global _exiftool_checked

    path = resolve_exiftool_path()
    _exiftool_checked = True

    if path:
        return True, f"Using ExifTool at: {path}"

    return False, (
        "ExifTool was not found. The bundled copy may be missing from this "
        f"build's resources/ folder, you can {_get_install_hint()}, or you "
        "can set a custom path in Settings > Set ExifTool Path..."
    )


# --- PUBLIC: METADATA OPERATIONS ---

def write_metadata(file_path: str, metadata: dict) -> bool:
    """
    Writes EXIF/XMP metadata to a single file using the resolved ExifTool
    executable. Returns False (without raising) if no ExifTool is
    available or the file doesn't exist.

    Overwrites originals in place (-overwrite_original_in_place), which is
    safer than -overwrite_original for proprietary RAW file formats since
    it edits the existing file rather than writing a new one and renaming
    over it.

    Tag keys in `metadata` may be either:
      - a plain tag name (e.g. "FNumber") -- written with an "-all:" group
        prefix, so ExifTool won't create the tag in an unintended/unknown
        group; or
      - a fully-qualified "Group:Tag" string (e.g. "XMP-dc:Subject") --
        written verbatim, since the group is already explicit. This is
        used for tags with no single standard EXIF home, like film stock.
    """
    exiftool_path = resolve_exiftool_path()
    if not exiftool_path:
        print("[Error] ExifTool is not available; cannot write metadata.")
        return False

    if not os.path.exists(file_path):
        print(f"[Error] File not found for metadata writing: {file_path}")
        return False

    args = [exiftool_path, "-overwrite_original_in_place"]
    for tag, value in metadata.items():
        if not value:
            continue
        if ":" in tag:
            args.append(f"-{tag}={value}")
        else:
            args.append(f"-all:{tag}={value}")

    if len(args) <= 2:
        return True

    args.append(file_path)

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False,
            timeout=SUBPROCESS_TIMEOUT, **SUBPROCESS_ARGS
        )
        if result.returncode != 0:
            # ExifTool often returns warnings (code 1) even on success, so we
            # check stderr. Only treat it as a failure if stderr has content.
            if result.stderr:
                print(f"[ExifTool Error] For file {os.path.basename(file_path)}: {result.stderr.strip()}")
                return False
        return True
    except Exception as e:
        print(f"[Exception] Failed to write metadata: {e}")
        return False


def get_shot_date(file_path: str):
    """
    Extracts the 'shot date' from a file's EXIF metadata using ExifTool.
    Returns None (without raising) if no ExifTool is available, the file
    doesn't exist, or the date can't be parsed.
    """
    exiftool_path = resolve_exiftool_path()
    if not exiftool_path or not os.path.exists(file_path):
        return None
    try:
        cmd = [exiftool_path, "-j", "-DateTimeOriginal", "-CreateDate", file_path]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=True, timeout=SUBPROCESS_TIMEOUT, **SUBPROCESS_ARGS
        )
        metadata = json.loads(result.stdout)[0]
        date_str = metadata.get("DateTimeOriginal") or metadata.get("CreateDate")
        if date_str:
            # Some cameras include a timezone offset or subseconds; only the
            # first 19 characters ("YYYY:MM:DD HH:MM:SS") are guaranteed to
            # match this format, so trim before parsing.
            return datetime.strptime(date_str[:19], "%Y:%m:%d %H:%M:%S")
    except Exception as e:
        print(f"[Exif Error] Could not read shot date from {os.path.basename(file_path)}: {e}")
    return None


def extract_preview_bytes(file_path: str):
    """
    Extracts an embedded preview/thumbnail image (raw JPEG bytes) from a
    file using ExifTool, trying progressively smaller embedded images.
    Used for generating thumbnails of RAW files, which QImageReader cannot
    decode directly.

    Returns the JPEG bytes, or None if no ExifTool is available or no
    embedded preview could be extracted.
    """
    exiftool_path = resolve_exiftool_path()
    if not exiftool_path or not os.path.exists(file_path):
        return None

    for tag in ("-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"):
        try:
            result = subprocess.run(
                [exiftool_path, "-b", tag, file_path],
                capture_output=True, check=False,
                timeout=SUBPROCESS_TIMEOUT, **SUBPROCESS_ARGS
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except Exception:
            continue
    return None


# --- INTERNAL HELPER FUNCTIONS ---

def _get_installed_version():
    """Checks the version of the currently-resolved ExifTool, if any."""
    path = resolve_exiftool_path()
    if not path:
        return None
    try:
        output = subprocess.check_output(
            [path, "-ver"], text=True, timeout=SUBPROCESS_TIMEOUT, **SUBPROCESS_ARGS
        ).strip()
        return output
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
