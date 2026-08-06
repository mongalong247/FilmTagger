import os
import shutil
import tempfile
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Qt, QRunnable
from PySide6.QtGui import QImageReader, QIcon, QPixmap

import exiftool_manager

# Extensions QImageReader cannot decode directly -- these get their thumbnail
# via an embedded preview extracted through ExifTool instead.
RAW_EXTENSIONS = (
    '.cr2', '.cr3', '.nef', '.arw', '.dng', '.rw2',
    '.orf', '.raf', '.pef', '.srw', '.rwl', '.3fr', '.raw',
)


def generate_scaled_pixmap(image_path: str, max_size: int):
    """
    Decodes `image_path` and returns a QPixmap scaled to fit within a
    max_size x max_size box (native aspect ratio preserved), or None if it
    couldn't be decoded. Shared by ThumbnailTask (small icons) and
    PreviewTask (the lightbox's larger preview) so both go through the same
    RAW-vs-standard decode logic instead of maintaining it twice.
    """
    ext = os.path.splitext(image_path)[1].lower()
    if ext in RAW_EXTENSIONS:
        return _extract_raw_preview(image_path, max_size)
    return _read_standard_image(image_path, max_size)


def _read_standard_image(image_path: str, max_size: int):
    """Decodes a directly-supported image format (jpg, tiff, png, heic...)."""
    reader = QImageReader(image_path)
    original_size = reader.size()
    if original_size.isValid():
        # Scale to fit within a max_size x max_size box while keeping native
        # aspect ratio -- forcing setScaledSize to a fixed square stretched/
        # cropped every 4:3 or 3:2 frame into a square.
        target = original_size.scaled(max_size, max_size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(target)
    image = reader.read()
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


def _extract_raw_preview(image_path: str, max_size: int):
    """
    RAW formats aren't decodable by QImageReader in a stock Qt install.
    Instead, pull the embedded preview/thumbnail JPEG that RAW files
    already carry, via ExifTool (which this app already depends on).
    """
    preview_bytes = exiftool_manager.extract_preview_bytes(image_path)
    if not preview_bytes:
        return None
    pixmap = QPixmap()
    if not pixmap.loadFromData(preview_bytes):
        return None
    return pixmap.scaled(
        max_size, max_size,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class ThumbnailSignals(QObject):
    """
    QRunnable itself can't emit signals (it isn't a QObject), so the signal
    lives on a small companion QObject instead.
    """
    finished = Signal(str, QIcon, int)  # image_path, icon, generation


class ThumbnailTask(QRunnable):
    """
    A task that runs on Qt's global thread pool to generate a thumbnail for
    a single image. Using QThreadPool instead of a dedicated QThread per
    image avoids spawning dozens of OS threads when loading a full roll.

    `generation` is an opaque counter supplied by the caller (MainWindow)
    that identifies which "load roll" operation this task belongs to. If
    the user loads a new roll before this task finishes, the result is
    still delivered but the caller can tell it's stale and discard it,
    instead of it landing in the wrong (newly loaded) filmstrip.
    """
    def __init__(self, image_path: str, generation: int, thumbnail_size: int = 200):
        super().__init__()
        self.image_path = image_path
        self.generation = generation
        self.thumbnail_size = thumbnail_size
        self.signals = ThumbnailSignals()

    def run(self):
        icon = self._generate_icon()
        self.signals.finished.emit(self.image_path, icon, self.generation)

    def _generate_icon(self) -> QIcon:
        try:
            pixmap = generate_scaled_pixmap(self.image_path, self.thumbnail_size)
            if pixmap is None or pixmap.isNull():
                return QIcon()
            return QIcon(pixmap)
        except Exception as e:
            print(f"Error generating thumbnail for {self.image_path}: {e}")
            return QIcon()


class PreviewSignals(QObject):
    """Companion QObject for PreviewTask -- see ThumbnailSignals above."""
    finished = Signal(str, QPixmap, int)  # image_path, pixmap, generation


class PreviewTask(QRunnable):
    """
    Like ThumbnailTask, but decodes a larger preview for the lightbox panel
    instead of a filmstrip icon, and delivers a QPixmap directly rather than
    a QIcon (the lightbox displays it in a QLabel, not a list item).

    `generation` here is reused as a simple "request token": MainWindow bumps
    it on every selection change so a slow decode for a frame the user has
    since clicked away from doesn't land in the lightbox after the fact.
    """
    def __init__(self, image_path: str, generation: int, preview_size: int = 900):
        super().__init__()
        self.image_path = image_path
        self.generation = generation
        self.preview_size = preview_size
        self.signals = PreviewSignals()

    def run(self):
        try:
            pixmap = generate_scaled_pixmap(self.image_path, self.preview_size)
        except Exception as e:
            print(f"Error generating preview for {self.image_path}: {e}")
            pixmap = None
        self.signals.finished.emit(self.image_path, pixmap or QPixmap(), self.generation)


class ExifWriteWorker(QObject):
    """
    A worker that processes a list of images to write EXIF data in the background.
    Handles temporary backups and reports progress.

    Per-file failures are isolated: a file that can't be backed up or
    tagged is recorded and skipped, and the rest of the batch still runs.
    The old behavior -- raising on the first failure and aborting every
    remaining file -- meant one locked/corrupt file partway through a roll
    silently left the rest of the roll untagged with no record of what had
    actually completed.
    """
    progress = Signal(int, str)  # percentage, status message
    finished = Signal(dict)      # {'cancelled': bool, 'succeeded': int,
                                  #  'failed': [(filename, reason), ...],
                                  #  'backup_path': str}

    def __init__(self, tasks: list, backup_enabled: bool):
        super().__init__()
        self.tasks = tasks
        self.backup_enabled = backup_enabled
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        total_files = len(self.tasks)
        backup_path = ""
        succeeded = 0
        failed = []  # list of (filename, reason)

        if total_files == 0:
            self.finished.emit({'cancelled': False, 'succeeded': 0, 'failed': [], 'backup_path': backup_path})
            return

        if self.backup_enabled:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_path = os.path.join(tempfile.gettempdir(), "FilmTagger", f"Backup_{timestamp}")
                os.makedirs(backup_path, exist_ok=True)
                print(f"Backup folder created at: {backup_path}")
            except Exception as e:
                # Can't create the safety net at all -- that's serious enough
                # to abort the whole batch rather than write without one.
                self.finished.emit({
                    'cancelled': False,
                    'succeeded': 0,
                    'failed': [(os.path.basename(p), f"Backup folder could not be created: {e}") for p, _ in self.tasks],
                    'backup_path': '',
                })
                return

        cancelled = False
        for idx, (image_path, metadata_dict) in enumerate(self.tasks):
            if not self.is_running:
                cancelled = True
                break

            progress_percent = int((idx + 1) / total_files * 100)
            filename = os.path.basename(image_path)
            self.progress.emit(progress_percent, f"Processing {filename}...")

            if self.backup_enabled:
                try:
                    shutil.copy2(image_path, backup_path)
                except Exception as e:
                    # Don't write metadata to a file we couldn't back up first.
                    failed.append((filename, f"Backup failed, file was skipped: {e}"))
                    continue

            try:
                write_ok = exiftool_manager.write_metadata(image_path, metadata_dict)
            except Exception as e:
                # Defensive: write_metadata() isn't expected to raise, but
                # nothing here should be able to take down the rest of the
                # batch, so catch anything unexpected too.
                failed.append((filename, f"Unexpected error: {e}"))
                continue

            if write_ok:
                succeeded += 1
            else:
                failed.append((filename, "ExifTool failed to write metadata (see console log for detail)"))

        self.finished.emit({
            'cancelled': cancelled,
            'succeeded': succeeded,
            'failed': failed,
            'backup_path': backup_path,
        })
