import os
import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QStatusBar, QProgressBar, QMenuBar, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, QSize
from PyQt6.QtGui import QAction, QIcon

import preset_manager
from ui.preset_editor import PresetEditorDialog
from ui.workers import ThumbnailWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Film Tagger")
        self.setGeometry(100, 100, 1200, 700)
        
        # --- Member Variables ---
        self.thumbnail_threads = [] 
        self.thumbnail_workers = []
        
        # --- NEW: Internal Data Model ---
        # This dictionary will store the metadata for each loaded image.
        # Key: image_path (str), Value: metadata_dictionary (dict)
        self.image_data = {}
        
        # --- NEW: State flag to prevent recursive signal handling ---
        # This prevents signals from firing when we programmatically update the UI
        self._is_updating_ui = False

        # --- Central Widget & Main Layout ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.main_splitter)

        # --- Create UI Panels ---
        self._create_batch_metadata_panel()
        self._create_filmstrip_panel()
        self._create_selection_metadata_panel()
        self.main_splitter.addWidget(self.batch_metadata_group)
        self.main_splitter.addWidget(self.filmstrip_group)
        self.main_splitter.addWidget(self.selection_metadata_group)
        self.main_splitter.setSizes([250, 700, 250])

        # --- Create Menu Bar & Status Bar ---
        self._create_menu_bar()
        self._create_status_bar()
        
        # --- Final Setup ---
        self._populate_preset_combos()
        self._connect_signals() # NEW: Connect all UI signals to handlers

        print("Main window UI is ready.")

    # --- NEW: Signal Connection Hub ---
    def _connect_signals(self):
        """Connects all UI element signals to their corresponding handler methods."""
        # Filmstrip selection
        self.filmstrip_list.itemSelectionChanged.connect(self._on_filmstrip_selection_changed)
        
        # Batch panel inputs
        self.camera_combo.currentIndexChanged.connect(self._on_batch_camera_changed)
        self.film_stock_combo.currentIndexChanged.connect(self._on_batch_film_stock_changed)
        self.roll_notes_edit.textChanged.connect(self._on_batch_notes_changed)
        
        # Selection panel inputs
        self.lens_combo.currentIndexChanged.connect(self._on_selection_lens_changed)
        self.aperture_edit.textChanged.connect(self._on_selection_aperture_changed)
        self.shutter_edit.textChanged.connect(self._on_selection_shutter_changed)

    # --- NEW: Batch Metadata Handlers ---
    def _on_batch_camera_changed(self, index):
        if self._is_updating_ui: return
        camera_name = self.camera_combo.itemText(index)
        # Apply to all loaded images
        for path in self.image_data:
            self.image_data[path]['Camera'] = camera_name
        print(f"Batch updated Camera to: {camera_name}")

    def _on_batch_film_stock_changed(self, index):
        if self._is_updating_ui: return
        film_name = self.film_stock_combo.itemText(index)
        for path in self.image_data:
            self.image_data[path]['FilmStock'] = film_name
        print(f"Batch updated Film Stock to: {film_name}")
        
    def _on_batch_notes_changed(self):
        if self._is_updating_ui: return
        notes = self.roll_notes_edit.toPlainText()
        for path in self.image_data:
            self.image_data[path]['RollNotes'] = notes
        # We don't print notes changes as it fires for every character

    # --- NEW: Selection Metadata Handlers ---
    def _on_selection_lens_changed(self, index):
        if self._is_updating_ui: return
        lens_name = self.lens_combo.itemText(index)
        selected_items = self.filmstrip_list.selectedItems()
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['Lens'] = lens_name
        print(f"Selection updated Lens to: {lens_name}")

    def _on_selection_aperture_changed(self, text):
        if self._is_updating_ui: return
        selected_items = self.filmstrip_list.selectedItems()
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['Aperture'] = text
        
    def _on_selection_shutter_changed(self, text):
        if self._is_updating_ui: return
        selected_items = self.filmstrip_list.selectedItems()
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['ShutterSpeed'] = text

    # --- NEW: Filmstrip Selection Handler ---
    def _on_filmstrip_selection_changed(self):
        """Updates the selection panel when the user clicks on items in the filmstrip."""
        self._is_updating_ui = True # Prevent signals while we update the UI
        
        selected_items = self.filmstrip_list.selectedItems()
        
        if not selected_items:
            # Nothing selected, clear the panel
            self.lens_combo.setCurrentIndex(0)
            self.aperture_edit.clear()
            self.shutter_edit.clear()
        elif len(selected_items) == 1:
            # A single image is selected, display its data
            item = selected_items[0]
            path = item.data(Qt.ItemDataRole.UserRole)
            data = self.image_data.get(path, {})
            
            self.lens_combo.setCurrentText(data.get('Lens', '--- Select Lens ---'))
            self.aperture_edit.setText(data.get('Aperture', ''))
            self.shutter_edit.setText(data.get('ShutterSpeed', ''))
        else:
            # Multiple images selected, display a placeholder for mixed values
            self.lens_combo.setCurrentIndex(0) # Or handle mixed values if you wish
            self.aperture_edit.setPlaceholderText("Multiple Values")
            self.aperture_edit.clear()
            self.shutter_edit.setPlaceholderText("Multiple Values")
            self.shutter_edit.clear()
            
        self._is_updating_ui = False # Re-enable signal handling

    def _load_roll(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Roll Folder")
        if not directory: return

        self.filmstrip_list.clear()
        self.image_data.clear() # Clear the data model for the new roll

        supported_extensions = ('.jpg', '.jpeg', '.tif', '.tiff', '.png', '.heic')
        image_files = [os.path.join(directory, f) for f in os.listdir(directory)
                       if f.lower().endswith(supported_extensions)]
        
        if not image_files:
            self.status_bar.showMessage("No compatible image files found.", 5000)
            return
            
        # Initialize the data model with empty dicts for each image
        for path in image_files:
            self.image_data[path] = {}

        self.status_bar.showMessage(f"Loading {len(image_files)} images...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(image_files))
        self.progress_bar.setValue(0)
        
        self.thumbnail_threads.clear()
        self.thumbnail_workers.clear()

        for image_path in image_files:
            worker = ThumbnailWorker(image_path)
            thread = QThread()
            self.thumbnail_workers.append(worker)
            self.thumbnail_threads.append(thread)
            worker.moveToThread(thread)
            worker.finished.connect(self._add_thumbnail_to_filmstrip)
            thread.started.connect(worker.run)
            thread.start()

    # --- Other methods remain largely unchanged from here ---
    def _add_thumbnail_to_filmstrip(self, image_path, icon):
        if not icon.isNull():
            filename = os.path.basename(image_path)
            item = QListWidgetItem(icon, filename)
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            self.filmstrip_list.addItem(item)
        current_value = self.progress_bar.value() + 1
        self.progress_bar.setValue(current_value)
        if current_value == self.progress_bar.maximum():
            self.status_bar.showMessage("Roll loaded successfully.", 5000)
            self.progress_bar.setVisible(False)
            # Pre-populate batch data into the model
            self._on_batch_camera_changed(self.camera_combo.currentIndex())
            self._on_batch_film_stock_changed(self.film_stock_combo.currentIndex())

    def open_preset_editor(self):
        dialog = PresetEditorDialog(self)
        dialog.exec()
        self._populate_preset_combos()
        print("Preset editor was closed. Repopulating dropdowns.")

    def _populate_preset_combos(self):
        print("Loading presets into UI...")
        self.camera_combo.clear()
        self.camera_combo.addItem("--- Select Camera ---")
        cameras = preset_manager.load_presets('cameras')
        self.camera_combo.addItems(sorted(cameras.keys()))
        self.film_stock_combo.clear()
        self.film_stock_combo.addItem("--- Select Film Stock ---")
        film_stocks = preset_manager.load_presets('film_stocks')
        self.film_stock_combo.addItems(sorted(film_stocks.keys()))
        self.lens_combo.clear()
        self.lens_combo.addItem("--- Select Lens ---")
        lenses = preset_manager.load_presets('lenses')
        self.lens_combo.addItems(sorted(lenses.keys()))
        self.camera_combo.setEnabled(True)
        self.film_stock_combo.setEnabled(True)
        self.roll_notes_edit.setEnabled(True)
        self.lens_combo.setEnabled(True)
        self.aperture_edit.setEnabled(True)
        self.shutter_edit.setEnabled(True)

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
        self.load_button.clicked.connect(self._load_roll)
        self.apply_button = QPushButton("Apply Changes")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.load_button)
        self.status_bar.addPermanentWidget(self.apply_button)
        self.status_bar.addPermanentWidget(self.progress_bar)

