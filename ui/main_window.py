import sys
from PyQt6.QtWidgets import QMainWindow

class MainWindow(QMainWindow):
    """
    The main window for the Film Tagger application.
    This class will contain the main UI layout and connect all the components.
    """
    def __init__(self):
        """Initializes the main window."""
        super().__init__()

        # --- Window Properties ---
        self.setWindowTitle("Film Tagger")
        # Set initial size (x-pos, y-pos, width, height)
        self.setGeometry(100, 100, 1200, 700)

        # --- Central Widget & Layout ---
        # A central widget is required for a QMainWindow.
        # We will add layouts and other widgets to this in the next milestone.
        # For now, we don't need to add anything to it.

        print("Main window initialized.")
