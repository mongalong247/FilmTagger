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
