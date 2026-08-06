#!/usr/bin/env python3
"""
Post-build step: copies the project's resources/ folder to sit directly
alongside the built executable, OUTSIDE PyInstaller's internal libs folder
(_internal/ on Windows/Linux onedir builds, Contents/Frameworks on macOS
app bundles).

Why this exists
----------------
resources/ holds things that must persist next to the app across runs: the
bundled ExifTool binary on Windows, and the user's saved camera/lens/film-
stock presets. paths.py resolves this location as:

    BASE_DIR = os.path.dirname(sys.executable)   # the folder the exe/app lives in
    RESOURCES_DIR = BASE_DIR / "resources"

If resources/ is instead added to PyInstaller via the spec's `datas=`,
PyInstaller 6+ nests it inside an internal libs folder (_internal/) rather
than next to the exe -- paths.py never looks there, so the bundled ExifTool
silently "goes missing" at runtime. Ported from ImageImporter, which hit
this directly (see packaging/README.md there for the full story); this
step sidesteps it the same way for FilmTagger.

Keeping resources/ entirely outside the PyInstaller Analysis and copying it
here, as an explicit step *after* the build, sidesteps that permanently --
whatever PyInstaller's internal layout does (or changes to, in some future
version), this step always places resources/ next to the actual running
executable.

Usage
-----
Run from the repo root, after building with the spec:

    pyinstaller packaging/FilmTagger.spec --noconfirm --clean
    python packaging/copy_resources.py

On Windows this requires resources/exiftool.exe and resources/exiftool_files/
to already exist in the repo (see packaging/README.md for how the release
workflow unpacks the vendored ExifTool build). On macOS/Linux it just
copies whatever's in resources/ (the presets/ folder) -- no ExifTool binary
is ever bundled there; the app's existing fallback chain (custom path ->
system PATH -> bundled) already handles "nothing bundled" gracefully and
shows a platform-appropriate install hint (see
exiftool_manager.py:_get_install_hint).
"""
import os
import platform
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_RESOURCES = os.path.join(REPO_ROOT, "resources")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
APP_NAME = "FilmTagger"

# resources/presets/*.json in this repo hold Ian's own dev/test gear (real
# camera bodies, lens serial numbers) -- personal data, not a starter
# dataset. Mirrors ImageImporter's exclusion of resources/lens_presets.json
# from release builds: a fresh install should start with an empty preset
# store (preset_manager.py already creates one on first use), not ship
# someone else's specific gear as if it were default content.
_EXCLUDED_RESOURCE_PATHS = {os.path.join("presets", "cameras.json"),
                            os.path.join("presets", "film_stocks.json"),
                            os.path.join("presets", "lenses.json")}


def _copy_resources_tree(dest_resources: str):
    """Copies resources/ to dest_resources, skipping the personal preset files above."""
    for root, _dirs, files in os.walk(SRC_RESOURCES):
        rel_root = os.path.relpath(root, SRC_RESOURCES)
        for name in files:
            rel_path = name if rel_root == "." else os.path.join(rel_root, name)
            if rel_path in _EXCLUDED_RESOURCE_PATHS:
                continue
            src = os.path.join(root, name)
            dst = os.path.join(dest_resources, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def find_app_dir() -> str:
    """Returns the folder that should contain resources/, next to the exe."""
    if platform.system() == "Darwin":
        macos_dir = os.path.join(DIST_DIR, f"{APP_NAME}.app", "Contents", "MacOS")
        if os.path.isdir(macos_dir):
            return macos_dir
        raise SystemExit(
            f"Expected macOS app bundle not found: {macos_dir}\n"
            "Did `pyinstaller packaging/FilmTagger.spec` run first?"
        )

    onedir = os.path.join(DIST_DIR, APP_NAME)
    if os.path.isdir(onedir):
        return onedir
    raise SystemExit(
        f"Expected PyInstaller onedir output not found: {onedir}\n"
        "Did `pyinstaller packaging/FilmTagger.spec` run first?"
    )


def main() -> None:
    target = find_app_dir()
    dest_resources = os.path.join(target, "resources")
    os.makedirs(dest_resources, exist_ok=True)

    if platform.system() == "Windows":
        exe_name = "exiftool.exe"
        if not os.path.isdir(SRC_RESOURCES) or not os.path.isfile(
            os.path.join(SRC_RESOURCES, exe_name)
        ):
            raise SystemExit(
                f"resources/{exe_name} not found in the repo.\n"
                "Windows builds need the bundled ExifTool present before "
                "packaging -- see packaging/README.md ('Sourcing ExifTool "
                "for Windows builds')."
            )
        _copy_resources_tree(dest_resources)
        print(f"Copied Windows resources/ (incl. bundled ExifTool, excl. personal presets) to: {dest_resources}")
    else:
        if os.path.isdir(SRC_RESOURCES):
            _copy_resources_tree(dest_resources)
        print(
            f"Copied resources/ (excl. personal presets, no ExifTool binary) to: {dest_resources}\n"
            "No ExifTool bundled on this platform by design -- users install "
            "it via Homebrew/apt/dnf/pacman, or point the app at a custom "
            "path from Settings > Set ExifTool Path..."
        )


if __name__ == "__main__":
    main()
