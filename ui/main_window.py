import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QStatusBar, QProgressBar, QMenuBar, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, QSize # <-- ADD QSize HERE
from PyQt6.QtGui import QAction, QIcon

# Import our new worker and the preset manager
import preset_manager
from ui.preset_editor import PresetEditorDialog
from ui.workers import ThumbnailWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Film Tagger")
        self.setGeometry(100, 100, 1200, 700)
        
        # --- Member Variables ---
        # To keep track of running thumbnail generation threads
        self.thumbnail_threads = [] 
        self.thumbnail_workers = []

        # --- Central Widget & Main Layout ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.main_splitter)

        # --- Create UI Panels ---
        self._create_batch_metadata_panel()
        self._create_filmstrip_panel()
        self._create_selection_metadata_panel()
        self.main_splitter.setSizes([250, 700, 250])

        # --- Create Menu Bar & Status Bar ---
        self._create_menu_bar()
        self._create_status_bar()
        
        # --- Final Setup ---
        self._populate_preset_combos() # Load presets into dropdowns

        print("Main window UI is ready.")

    def _populate_preset_combos(self):
        """Loads presets from JSON files and populates the QComboBoxes."""
        print("Loading presets into UI...")
        
        # --- Camera Combo Box ---
        self.camera_combo.clear()
        self.camera_combo.addItem("--- Select Camera ---")
        cameras = preset_manager.load_presets('cameras')
        self.camera_combo.addItems(sorted(cameras.keys()))
        
        # --- Film Stock Combo Box ---
        self.film_stock_combo.clear()
        self.film_stock_combo.addItem("--- Select Film Stock ---")
        film_stocks = preset_manager.load_presets('film_stocks')
        self.film_stock_combo.addItems(sorted(film_stocks.keys()))
        
        # --- Lens Combo Box ---
        self.lens_combo.clear()
        self.lens_combo.addItem("--- Select Lens ---")
        lenses = preset_manager.load_presets('lenses')
        self.lens_combo.addItems(sorted(lenses.keys()))
        
        # Enable the widgets now that they have data
        self.camera_combo.setEnabled(True)
        self.film_stock_combo.setEnabled(True)
        self.roll_notes_edit.setEnabled(True)
        self.lens_combo.setEnabled(True)
        self.aperture_edit.setEnabled(True)
        self.shutter_edit.setEnabled(True)

    def _load_roll(self):
        """Opens a dialog to select a folder and loads images into the filmstrip."""
        # You might want to save/restore the last used directory
        directory = QFileDialog.getExistingDirectory(self, "Select Roll Folder")
        if not directory:
            return

        self.filmstrip_list.clear()
        
        # Find all compatible image files
        supported_extensions = ('.jpg', '.jpeg', '.tif', '.tiff', '.png', '.heic')
        image_files = [os.path.join(directory, f) for f in os.listdir(directory)
                       if f.lower().endswith(supported_extensions)]
        
        if not image_files:
            self.status_bar.showMessage("No compatible image files found in the selected folder.", 5000)
            return
            
        self.status_bar.showMessage(f"Loading {len(image_files)} images...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(image_files))
        self.progress_bar.setValue(0)
        
        # Clean up any previous threads
        self.thumbnail_threads.clear()
        self.thumbnail_workers.clear()

        # Create a worker and thread for each image
        for image_path in image_files:
            worker = ThumbnailWorker(image_path)
            thread = QThread()
            
            self.thumbnail_workers.append(worker)
            self.thumbnail_threads.append(thread)
            
            worker.moveToThread(thread)
            worker.finished.connect(self._add_thumbnail_to_filmstrip)
            
            thread.started.connect(worker.run)
            thread.start()

    def _add_thumbnail_to_filmstrip(self, image_path, icon):
        """Slot to receive the generated thumbnail and add it to the list."""
        if not icon.isNull():
            filename = os.path.basename(image_path)
            item = QListWidgetItem(icon, filename)
            # Store the full path in the item's data for later use
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            self.filmstrip_list.addItem(item)
            
        # Update progress
        current_value = self.progress_bar.value() + 1
        self.progress_bar.setValue(current_value)
        
        # If all images are loaded, hide the progress bar
        if current_value == self.progress_bar.maximum():
            self.status_bar.showMessage("Roll loaded successfully.", 5000)
            self.progress_bar.setVisible(False)

    def open_preset_editor(self):
        """Opens the preset editor and reloads combos when it closes."""
        dialog = PresetEditorDialog(self)
        dialog.exec()
        # After the dialog is closed, refresh the presets in the main window
        self._populate_preset_combos()
        print("Preset editor was closed. Repopulating dropdowns.")

    # --- UI Creation Methods (Mostly Unchanged) ---
    def _create_batch_metadata_panel(self):
        self.batch_metadata_group = QGroupBox("Batch Metadata (Entire Roll)")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Camera Body:"))
        self.camera_combo = QComboBox()
        layout.addWidget(self.camera_combo)
        layout.addWidget(QLabel("Film Stock:"))
        self.film_stock_combo = QComboBox()
        layout.addWidget(self.film_stock_combo)
        layout.addWidget(QLabel("Roll Notes:"))
        self.roll_notes_edit = QTextEdit()
        layout.addWidget(self.roll_notes_edit)
        layout.addStretch()
        self.batch_metadata_group.setLayout(layout)

    def _create_filmstrip_panel(self):
        self.filmstrip_group = QGroupBox("Filmstrip View")
        layout = QVBoxLayout()
        self.filmstrip_list = QListWidget()
        # Configure the list for thumbnails
        self.filmstrip_list.setIconSize(QSize(180, 180))
        self.filmstrip_list.setFlow(QListWidget.Flow.LeftToRight)
        self.filmstrip_list.setWrapping(True)
        self.filmstrip_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.filmstrip_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.filmstrip_list)
        self.filmstrip_group.setLayout(layout)

    def _create_selection_metadata_panel(self):
        self.selection_metadata_group = QGroupBox("Selection Metadata")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Lens:"))
        self.lens_combo = QComboBox()
        layout.addWidget(self.lens_combo)
        layout.addWidget(QLabel("Aperture (F-Number):"))
        self.aperture_edit = QLineEdit()
        self.aperture_edit.setPlaceholderText("e.g., 8 or f/8")
        layout.addWidget(self.aperture_edit)
        layout.addWidget(QLabel("Shutter Speed:"))
        self.shutter_edit = QLineEdit()
        self.shutter_edit.setPlaceholderText("e.g., 1/125 or 125")
        layout.addWidget(self.shutter_edit)
        layout.addStretch()
        self.selection_metadata_group.setLayout(layout)

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        edit_menu = menu_bar.addMenu("&Edit")
        manage_presets_action = QAction("Manage Presets...", self)
        manage_presets_action.triggered.connect(self.open_preset_editor)
        edit_menu.addAction(manage_presets_action)

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.load_button = QPushButton("Load Roll...")
        self.load_button.clicked.connect(self._load_roll) # Connect the button
        self.apply_button = QPushButton("Apply Changes")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.load_button)
        self.status_bar.addPermanentWidget(self.apply_button)
        self.status_bar.addPermanentWidget(self.progress_bar)


