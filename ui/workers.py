import os
from PyQt6.QtCore import QObject, pyqtSignal, QSize, Qt
from PyQt6.QtGui import QImageReader, QIcon, QPixmap

class ThumbnailWorker(QObject):
    """
    A worker that runs on a separate thread to generate a thumbnail for an image.
    This prevents the UI from freezing when loading a roll of film.
    """
    # Signal: finished(str, QIcon) -> Emits the image path and the generated icon
    finished = pyqtSignal(str, QIcon)

    def __init__(self, image_path: str, thumbnail_size: int = 200):
        super().__init__()
        self.image_path = image_path
        self.thumbnail_size = thumbnail_size
        self.is_running = True

    def run(self):
        """The main work method that will be executed on the new thread."""
        if not self.is_running:
            return

        try:
            # Use QImageReader for robust image loading
            reader = QImageReader(self.image_path)
            
            # Set a target size for the thumbnail
            target_size = QSize(self.thumbnail_size, self.thumbnail_size)
            reader.setScaledSize(target_size)
            
            # Read the image
            image = reader.read()
            if image.isNull():
                print(f"Failed to read image: {self.image_path}")
                # Emit a signal with an empty icon to signify failure if needed
                self.finished.emit(self.image_path, QIcon())
                return
            
            # Create a QPixmap and then a QIcon from the image
            pixmap = QPixmap.fromImage(image)
            icon = QIcon(pixmap)
            
            # Emit the signal with the result
            self.finished.emit(self.image_path, icon)

        except Exception as e:
            print(f"Error generating thumbnail for {self.image_path}: {e}")
            self.finished.emit(self.image_path, QIcon())

    def stop(self):
        """Stops the worker."""
        self.is_running = False

# ... (keep the existing ThumbnailWorker class and imports at the top) ...
import shutil
import tempfile
from datetime import datetime

# Import exiftool_manager from the parent directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import exiftool_manager

class ExifWriteWorker(QObject):
    """
    A worker that processes a list of images to write EXIF data in the background.
    Handles temporary backups and reports progress.
    """
    progress = pyqtSignal(int, str)  # Reports percentage and status message
    finished = pyqtSignal(bool, str) # Reports success/failure and the backup path

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
        
        try:
            # 1. Create backup folder if enabled
            if self.backup_enabled:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                # Use a system temp directory for the backup
                backup_path = os.path.join(tempfile.gettempdir(), "FilmTagger", f"Backup_{timestamp}")
                os.makedirs(backup_path, exist_ok=True)
                print(f"Backup folder created at: {backup_path}")

            # 2. Process each file
            for idx, (image_path, metadata_dict) in enumerate(self.tasks):
                if not self.is_running:
                    raise InterruptedError("Process cancelled by user.")

                progress_percent = int((idx + 1) / total_files * 100)
                filename = os.path.basename(image_path)
                self.progress.emit(progress_percent, f"Processing {filename}...")

                # 2a. Copy original to backup folder
                if self.backup_enabled:
                    shutil.copy2(image_path, backup_path)

                # 2b. Write metadata to the original file
                if not exiftool_manager.write_metadata(image_path, metadata_dict):
                    # If write fails, the original is safe in the backup folder
                    raise IOError(f"Failed to write metadata for {filename}.")
            
            # 3. If we get here, all files succeeded
            self.finished.emit(True, backup_path)

        except Exception as e:
            # On any failure, emit a failure signal
            error_message = f"Error: {e}. Originals are safe in backup folder: {backup_path}" if self.backup_enabled else f"Error: {e}"
            self.finished.emit(False, error_message)

class InterruptedError(Exception):
    pass

