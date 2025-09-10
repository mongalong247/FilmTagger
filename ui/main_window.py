import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QLineEdit, QListWidget,
    QSplitter, QGroupBox, QStatusBar, QProgressBar
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

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
        self.setGeometry(100, 100, 1200, 700)

        # --- Central Widget & Main Layout ---
        # The main layout will be a horizontal splitter to create the panels.
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.main_splitter)

        # --- Create the UI Panels ---
        self._create_batch_metadata_panel()
        self._create_filmstrip_panel()
        self._create_selection_metadata_panel()

        # Add the panels to the splitter
        self.main_splitter.addWidget(self.batch_metadata_group)
        self.main_splitter.addWidget(self.filmstrip_group)
        self.main_splitter.addWidget(self.selection_metadata_group)

        # Set initial sizes for the panels (optional, but good for UX)
        self.main_splitter.setSizes([250, 700, 250])

        # --- Create Action Buttons and Status Bar ---
        self._create_status_bar()

        print("Main window UI layout created.")

    def _create_batch_metadata_panel(self):
        """Creates the left-hand panel for metadata applied to the whole roll."""
        self.batch_metadata_group = QGroupBox("Batch Metadata (Entire Roll)")
        layout = QVBoxLayout()

        # Camera Body
        layout.addWidget(QLabel("Camera Body:"))
        self.camera_combo = QComboBox()
        self.camera_combo.setDisabled(True)
        self.camera_combo.setToolTip("Select the camera body used for this entire roll.")
        layout.addWidget(self.camera_combo)

        # Film Stock
        layout.addWidget(QLabel("Film Stock:"))
        self.film_stock_combo = QComboBox()
        self.film_stock_combo.setDisabled(True)
        self.film_stock_combo.setToolTip("Select the film stock used.")
        layout.addWidget(self.film_stock_combo)

        # Roll Notes
        layout.addWidget(QLabel("Roll Notes:"))
        self.roll_notes_edit = QTextEdit()
        self.roll_notes_edit.setDisabled(True)
        self.roll_notes_edit.setToolTip("Enter any general notes for this roll of film.")
        layout.addWidget(self.roll_notes_edit)

        layout.addStretch() # Pushes widgets to the top
        self.batch_metadata_group.setLayout(layout)

    def _create_filmstrip_panel(self):
        """Creates the central panel to display image thumbnails."""
        self.filmstrip_group = QGroupBox("Filmstrip View")
        layout = QVBoxLayout()

        self.filmstrip_list = QListWidget()
        # TODO: Configure view for thumbnails later
        layout.addWidget(self.filmstrip_list)

        self.filmstrip_group.setLayout(layout)

    def _create_selection_metadata_panel(self):
        """Creates the right-hand panel for metadata applied to selected frames."""
        self.selection_metadata_group = QGroupBox("Selection Metadata")
        layout = QVBoxLayout()

        # Lens
        layout.addWidget(QLabel("Lens:"))
        self.lens_combo = QComboBox()
        self.lens_combo.setDisabled(True)
        self.lens_combo.setToolTip("Select the lens used for the selected frame(s).")
        layout.addWidget(self.lens_combo)

        # Aperture
        layout.addWidget(QLabel("Aperture (F-Number):"))
        self.aperture_edit = QLineEdit()
        self.aperture_edit.setDisabled(True)
        self.aperture_edit.setPlaceholderText("e.g., 8 or f/8")
        layout.addWidget(self.aperture_edit)

        # Shutter Speed
        layout.addWidget(QLabel("Shutter Speed:"))
        self.shutter_edit = QLineEdit()
        self.shutter_edit.setDisabled(True)
        self.shutter_edit.setPlaceholderText("e.g., 1/125 or 125")
        layout.addWidget(self.shutter_edit)

        layout.addStretch() # Pushes widgets to the top
        self.selection_metadata_group.setLayout(layout)

    def _create_status_bar(self):
        """Creates the status bar at the bottom with action buttons."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Action Buttons
        self.load_button = QPushButton("Load Roll...")
        self.apply_button = QPushButton("Apply Changes")

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False) # Hide it initially

        # Add widgets to the status bar
        self.status_bar.addPermanentWidget(self.load_button)
        self.status_bar.addPermanentWidget(self.apply_button)
        self.status_bar.addPermanentWidget(self.progress_bar)

