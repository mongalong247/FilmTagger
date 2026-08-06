import os
import platform
import shutil
import subprocess
import json
import base64
import threading
import queue
import time
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
# download or update check. Ported alongside ImageImporter's packaging
# pipeline (see packaging/README.md): the Windows build unzips
# vendor/exiftool-<VERSION>_64.zip into resources/ at build time. To ship a
# newer version, update the vendored zip, EXIFTOOL_VERSION in
# .github/workflows/release.yml, and this constant together.
PINNED_BUNDLED_VERSION = "13.59"

SETTINGS_ORG = "PhotoTagger"
SETTINGS_APP = "FilmTagger"
CUSTOM_PATH_KEY = "exiftoolCustomPath"

# --- Platform-specific configuration for subprocess to hide console window ---
SUBPROCESS_ARGS = {}
if platform.system() == "Windows":
    SUBPROCESS_ARGS['creationflags'] = subprocess.CREATE_NO_WINDOW

SUBPROCESS_TIMEOUT = 15  # seconds, for one-off calls to the exiftool binary
STAY_OPEN_TIMEOUT = 30   # seconds, for a single command sent to a persistent session/pool

# How many persistent, already-running ExifTool processes to keep around
# for reads (RAW preview extraction) and metadata writes. On a bundled
# Windows build, every "cold" invocation of exiftool.exe re-loads the Perl
# interpreter plus every .pm module under resources/exiftool_files/ from
# scratch -- by far the biggest single cost per call, dwarfing the actual
# work done. A small pool of persistent ("-stay_open") processes pays that
# startup cost once (per process) at the start of a run instead of once per
# file (or, previously, up to three times per file for RAW preview
# extraction -- see extract_preview_bytes), and lets a handful of files'
# extraction calls genuinely run concurrently instead of queueing behind a
# single process. Kept modest: each process costs some memory and its own
# one-time startup, and beyond a handful there's no more benefit once local
# disk/CPU is saturated anyway. Ported from ImageImporter's performance pass.
POOL_SIZE = max(1, min(4, (os.cpu_count() or 2)))

# --- State ---
_resolved_exiftool_path = None  # cached once a working path is found this session
_exiftool_checked = False       # guards against repeating the resolution flow

_pool = None
_pool_lock = threading.Lock()

# Preview/thumbnail tags to try, in descending order of expected size/
# quality -- see extract_preview_bytes() below for why each exists.
_PREVIEW_TAGS_PRIORITY = ("JpgFromRaw2", "JpgFromRaw", "PreviewImage", "OtherImage", "ThumbnailImage")


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
    global _exiftool_checked
    invalidate_resolved_path()
    _exiftool_checked = False
    # A path change means any already-running persistent processes are
    # pointed at the wrong (or no-longer-desired) executable -- shut them
    # down so the next call starts fresh ones against the new path.
    close_session()


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


def invalidate_resolved_path():
    """
    Forces the next resolve_exiftool_path() call to re-run the fallback
    chain from scratch instead of trusting the cached result. Used when a
    persistent ExifTool session fails to even launch (e.g. the resolved
    binary was deleted, or a removable drive holding it went away mid-run),
    so a bad cached path doesn't stay stuck for the rest of the app's
    lifetime.
    """
    global _resolved_exiftool_path
    _resolved_exiftool_path = None


def resolve_exiftool_path():
    """
    Resolves a working ExifTool executable using a fallback chain:
      1. User-configured custom path (Settings)
      2. A system-wide install found on PATH
      3. The bundled, pinned copy in resources/

    The result is cached for the rest of the app's run once found, and is
    NOT re-validated (i.e. no extra "-ver" subprocess spawn) on every call.
    This matters: previously, every single ExifTool operation in this app
    (a RAW preview extraction, a metadata write) silently paid for TWO
    process launches instead of one -- a "-ver" liveness check here, then
    the real command -- which for a full roll doubled the total number of
    exiftool.exe launches for no benefit, since the resolved path
    essentially never changes mid-run. Call invalidate_resolved_path() to
    force re-resolution (set_custom_path() already does this
    automatically). Ported from ImageImporter's performance pass.

    Returns the resolved path (str), or None if nothing usable was found.
    """
    global _resolved_exiftool_path

    if _resolved_exiftool_path:
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


# --- PERSISTENT ("-stay_open") EXIFTOOL PROCESS SUPPORT ---
# Ported from ImageImporter's performance rework (2026-08-05) -- see
# claude/imageimporter-performance-notes.md in the project. Every class
# below is unchanged from that pass; FilmTagger's own write_metadata() /
# extract_preview_bytes() wrap it while keeping FilmTagger-specific
# behavior (the "-all:" group-prefix convention, -overwrite_original_in_place).

class _ExifToolSession:
    """
    Wraps one persistent ExifTool process started with '-stay_open True',
    so many commands can be sent to it, one after another, without paying
    process-launch (and, for a bundled Windows build, Perl interpreter +
    module reload) cost each time.

    Thread-safe: commands are serialized through an internal lock, so
    calling execute() from multiple threads is safe, but only one command
    is ever in flight on THIS particular process at a time -- see
    _ExifToolPool below for running several of these concurrently.
    """

    def __init__(self, exiftool_path: str):
        self._exiftool_path = exiftool_path
        self._proc = None
        self._out_queue = None
        self._lock = threading.Lock()

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self):
        try:
            self._proc = subprocess.Popen(
                [self._exiftool_path, "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **SUBPROCESS_ARGS
            )
        except Exception:
            # The resolved path itself is no good (deleted, unplugged
            # drive, etc.) -- don't keep handing out the same bad path.
            invalidate_resolved_path()
            self._proc = None
            raise

        self._out_queue = queue.Queue()
        threading.Thread(
            target=self._reader_loop, args=(self._proc.stdout, self._out_queue), daemon=True
        ).start()
        threading.Thread(
            target=self._drain_stderr, args=(self._proc.stderr,), daemon=True
        ).start()

    @staticmethod
    def _reader_loop(stream, out_queue):
        try:
            for line in iter(stream.readline, b""):
                out_queue.put(line)
        except Exception:
            pass
        finally:
            out_queue.put(None)  # signals EOF / process gone

    @staticmethod
    def _drain_stderr(stream):
        # Just keeps the stderr pipe from filling up and blocking ExifTool
        # -- per-command/per-file success is already determined from the
        # stdout text (see write_metadata / extract_preview_bytes), so
        # stderr content here isn't otherwise consumed.
        try:
            for _line in iter(stream.readline, b""):
                pass
        except Exception:
            pass

    def _kill(self):
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None

    def close(self):
        """Cleanly shuts down the persistent process, if one is running."""
        with self._lock:
            if not self._is_alive():
                self._proc = None
                return
            try:
                # Per ExifTool's documented -stay_open protocol, the
                # shutdown command still needs an -execute terminator like
                # any other command -- just writing "-stay_open\nFalse\n"
                # without it leaves ExifTool waiting for more input forever.
                self._proc.stdin.write(b"-stay_open\nFalse\n-execute\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=SUBPROCESS_TIMEOUT)
            except Exception:
                self._kill()
            self._proc = None

    def _collect_until_ready(self, timeout):
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for ExifTool's response")
            try:
                line = self._out_queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("Timed out waiting for ExifTool's response")
            if line is None:
                raise RuntimeError("ExifTool's -stay_open process ended unexpectedly")
            if line.rstrip(b"\r\n") == b"{ready}":
                return b"".join(lines)
            lines.append(line)

    def execute(self, args, timeout=STAY_OPEN_TIMEOUT):
        """
        Sends one command (a list of ExifTool arguments, e.g.
        ["-j", "-DateTimeOriginal", "file.jpg"]) to the persistent process
        and returns its raw stdout bytes for that command (with the
        trailing '{ready}' marker stripped). Retries once (killing and
        restarting the process) on any failure. Returns None if the
        command still couldn't be completed -- callers should treat that
        as "not available for this call" and fall back accordingly, the
        same as if ExifTool weren't installed at all.
        """
        with self._lock:
            last_error = None
            for _attempt in (1, 2):
                try:
                    if not self._is_alive():
                        self._start()
                    payload = "".join(f"{a}\n" for a in args) + "-execute\n"
                    self._proc.stdin.write(payload.encode("utf-8", errors="replace"))
                    self._proc.stdin.flush()
                    return self._collect_until_ready(timeout)
                except Exception as e:
                    last_error = e
                    self._kill()
            print(f"[ExifTool Session Error] {last_error}")
            return None


class _ExifToolPool:
    """
    A small round-robin pool of _ExifToolSession processes. A single
    persistent process removes launch overhead but still handles one
    command at a time; spreading calls across a few processes lets
    independent files' reads (RAW preview extraction) actually run
    concurrently instead of queueing behind one process.
    """

    def __init__(self, size: int):
        self._size = max(1, size)
        self._path = None
        self._sessions = []
        self._lock = threading.Lock()
        self._next = 0

    def _ensure_sessions(self, path: str):
        with self._lock:
            if self._path != path or len(self._sessions) != self._size:
                for s in self._sessions:
                    s.close()
                self._path = path
                self._sessions = [_ExifToolSession(path) for _ in range(self._size)]

    def execute(self, args, timeout=STAY_OPEN_TIMEOUT):
        path = resolve_exiftool_path()
        if not path:
            return None
        self._ensure_sessions(path)
        with self._lock:
            session = self._sessions[self._next]
            self._next = (self._next + 1) % self._size
        return session.execute(args, timeout=timeout)

    def close(self):
        with self._lock:
            for s in self._sessions:
                s.close()
            self._sessions = []
            self._path = None


def _get_pool():
    """Returns the shared ExifTool process pool, lazily created, or None
    if no working ExifTool could be resolved at all."""
    global _pool
    if not resolve_exiftool_path():
        return None
    with _pool_lock:
        if _pool is None:
            _pool = _ExifToolPool(size=POOL_SIZE)
        return _pool


def close_session():
    """
    Cleanly shuts down any persistent ExifTool process(es) this app has
    running. Safe to call even if none are running. Call this on app exit
    so no orphaned exiftool process is left behind, and after changing the
    resolved ExifTool path so stale processes aren't reused.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


# --- PUBLIC: METADATA OPERATIONS ---

def write_metadata(file_path: str, metadata: dict) -> bool:
    """
    Writes EXIF/XMP metadata to a single file, via the persistent ExifTool
    pool when available (falling back to a direct one-off process launch
    if the pool can't complete the call). Returns False (without raising)
    if no ExifTool is available, the file doesn't exist, or the write
    otherwise fails.

    Overwrites originals in place (-overwrite_original_in_place), which is
    safer than -overwrite_original for proprietary RAW file formats since
    it edits the existing file rather than writing a new one and renaming
    over it. (This is a deliberate difference from ImageImporter's
    write_metadata, which uses plain -overwrite_original -- ImageImporter
    doesn't write to RAW originals the way FilmTagger does.)

    Tag keys in `metadata` may be either:
      - a plain tag name (e.g. "FNumber") -- written with an "-all:" group
        prefix, so ExifTool won't create the tag in an unintended/unknown
        group; or
      - a fully-qualified "Group:Tag" string (e.g. "XMP-dc:Subject") --
        written verbatim, since the group is already explicit. This is
        used for tags with no single standard EXIF home, like film stock.
    """
    if not os.path.exists(file_path):
        print(f"[Error] File not found for metadata writing: {file_path}")
        return False

    tag_args = []
    for tag, value in metadata.items():
        if not value:
            continue
        if ":" in tag:
            tag_args.append(f"-{tag}={value}")
        else:
            tag_args.append(f"-all:{tag}={value}")

    if not tag_args:
        return True

    pool = _get_pool()
    if pool is not None:
        output = pool.execute(["-overwrite_original_in_place"] + tag_args + [file_path])
        if output is not None:
            text = output.decode("utf-8", errors="replace")
            if (
                "1 image files updated" in text
                or "1 image files created" in text
                or "1 image files unchanged" in text
            ):
                return True
            if text.strip():
                print(f"[ExifTool Error] {text.strip()}")
            return False
        # Pool/process failed even after its internal retry -- fall back
        # to a direct one-off invocation for just this file.

    return _write_metadata_subprocess_fallback(file_path, metadata)


def extract_preview_bytes(file_path: str):
    """
    Extracts an embedded preview/thumbnail image (raw JPEG bytes) from a
    file using ExifTool. Used for generating thumbnails/lightbox previews
    of RAW files, which QImageReader cannot decode directly.

    Different manufacturers embed their largest preview under different
    tag names, so several are considered in descending order of expected
    size/quality:

      JpgFromRaw2 / JpgFromRaw  -- near full-resolution; common on
                                   Panasonic and some Olympus RAW files,
                                   which often don't populate PreviewImage
      PreviewImage              -- medium-to-large; common on Canon/
                                   Nikon/Sony
      OtherImage                -- uncommon, occasional fallback
      ThumbnailImage            -- small (often ~160x120) -- last resort

    All candidate tags are requested in a single ExifTool command (using
    -json -b, which base64-encodes binary tag values inline in the JSON
    response) rather than trying them one at a time in up to five separate
    processes -- ported from ImageImporter's performance pass, where this
    was the single biggest source of redundant ExifTool invocations in a
    RAW-heavy pass (previously up to 3 processes per RAW file here).

    Returns the JPEG bytes, or None if no ExifTool is available or no
    embedded preview could be extracted.
    """
    if not os.path.exists(file_path):
        return None

    pool = _get_pool()
    if pool is not None:
        args = ["-j", "-b"] + [f"-{tag}" for tag in _PREVIEW_TAGS_PRIORITY] + [file_path]
        output = pool.execute(args)
        if output is not None:
            try:
                parsed = json.loads(output.decode("utf-8", errors="replace"))
                entry = parsed[0] if parsed else {}
            except Exception as e:
                print(f"[Exif Error] Could not parse combined preview response for {os.path.basename(file_path)}: {e}")
                entry = None

            if entry is not None:
                for tag in _PREVIEW_TAGS_PRIORITY:
                    raw = entry.get(tag)
                    if raw and isinstance(raw, str) and raw.startswith("base64:"):
                        try:
                            return base64.b64decode(raw[len("base64:"):])
                        except Exception as e:
                            print(f"[Exif Error] Could not decode base64 {tag} from {os.path.basename(file_path)}: {e}")
                return None
        # Pool/process failed even after its internal retry -- fall back.

    return _extract_preview_subprocess_fallback(file_path)


def get_shot_date(file_path: str):
    """
    Extracts the 'shot date' from a file's EXIF metadata using ExifTool.
    Returns None (without raising) if no ExifTool is available, the file
    doesn't exist, or the date can't be parsed. Not currently called
    anywhere in FilmTagger's UI, kept (and upgraded to use the persistent
    pool) for parity with ImageImporter in case a future feature wants
    chronological sorting or date-based subfolder naming.
    """
    if not os.path.exists(file_path):
        return None

    pool = _get_pool()
    if pool is not None:
        output = pool.execute(["-j", "-DateTimeOriginal", "-CreateDate", file_path])
        if output is not None:
            try:
                metadata = json.loads(output.decode("utf-8", errors="replace"))[0]
                date_str = metadata.get("DateTimeOriginal") or metadata.get("CreateDate")
                if date_str:
                    return datetime.strptime(date_str[:19], "%Y:%m:%d %H:%M:%S")
                return None
            except Exception as e:
                print(f"[Exif Error] Could not read shot date from {os.path.basename(file_path)}: {e}")
                return None
        # Pool/process failed even after its internal retry -- fall back.

    return _get_shot_date_subprocess_fallback(file_path)


# --- SUBPROCESS FALLBACKS (one-off process per call; no -stay_open) ---
#
# Used when the persistent process pool can't be started or stops
# responding (e.g. an unusual ExifTool build that doesn't support
# -stay_open). Slower, but never a regression in correctness.

def _write_metadata_subprocess_fallback(file_path: str, metadata: dict) -> bool:
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


def _extract_preview_subprocess_fallback(file_path: str):
    exiftool_path = resolve_exiftool_path()
    if not exiftool_path or not os.path.exists(file_path):
        return None

    for tag in (f"-{t}" for t in _PREVIEW_TAGS_PRIORITY):
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


def _get_shot_date_subprocess_fallback(file_path: str):
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
