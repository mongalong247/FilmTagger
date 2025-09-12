import os
import sys
import shutil
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QComboBox, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QStatusBar, QProgressBar, QMenuBar, QFileDialog,
    QCheckBox
)
from PyQt6.QtCore import Qt, QThread, QSize
from PyQt6.QtGui import QAction, QIcon

import preset_manager
from ui.preset_editor import PresetEditorDialog
from ui.workers import ThumbnailWorker, ExifWriteWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Film Tagger")
        self.setGeometry(100, 100, 1200, 700)
        
        self.thumbnail_threads = [] 
        self.thumbnail_workers = []
        self.write_thread = None
        self.write_worker = None
        self.image_data = {}
        self._is_updating_ui = False

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.main_splitter)

        self._create_batch_metadata_panel()
        self._create_filmstrip_panel()
        self._create_selection_metadata_panel()
        self.main_splitter.addWidget(self.batch_metadata_group)
        self.main_splitter.addWidget(self.filmstrip_group)
        self.main_splitter.addWidget(self.selection_metadata_group)
        self.main_splitter.setSizes([250, 700, 250])

        self._create_menu_bar()
        self._create_status_bar()
        
        self._populate_preset_combos()
        self._connect_signals()

    def _connect_signals(self):
        self.filmstrip_list.itemSelectionChanged.connect(self._on_filmstrip_selection_changed)
        self.camera_combo.currentIndexChanged.connect(self._on_batch_camera_changed)
        self.film_stock_combo.currentIndexChanged.connect(self._on_batch_film_stock_changed)
        self.roll_notes_edit.textChanged.connect(self._on_batch_notes_changed)
        self.lens_combo.currentIndexChanged.connect(self._on_selection_lens_changed)
        self.aperture_edit.textChanged.connect(self._on_selection_aperture_changed)
        self.shutter_edit.textChanged.connect(self._on_selection_shutter_changed)
        # NEW: Connect the apply button
        self.apply_button.clicked.connect(self._apply_changes)

    # --- NEW: Processing Logic ---
    def _apply_changes(self):
        """Prepares and starts the EXIF writing process."""
        if not self.image_data:
            QMessageBox.warning(self, "No Images Loaded", "Please load a roll of film before applying changes.")
            return

        reply = QMessageBox.question(self, "Confirm Changes", 
                                     f"You are about to write metadata to {len(self.image_data)} files. Are you sure you want to proceed?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return
            
        # Prepare the task list by gathering all data
        tasks = self._prepare_task_list()
        if not tasks:
            QMessageBox.critical(self, "Error", "Could not prepare data for writing. Please check your presets.")
            return

        # Disable UI and start worker
        self._set_ui_enabled(False)
        self.status_bar.showMessage("Applying changes...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        backup_enabled = self.backup_checkbox.isChecked()
        self.write_worker = ExifWriteWorker(tasks, backup_enabled)
        self.write_thread = QThread()
        self.write_worker.moveToThread(self.write_thread)
        
        self.write_worker.progress.connect(lambda val, msg: self.progress_bar.setValue(val) and self.status_bar.showMessage(msg))
        self.write_worker.finished.connect(self._on_apply_finished)
        
        self.write_thread.started.connect(self.write_worker.run)
        self.write_thread.start()

    def _prepare_task_list(self) -> list:
        """
        Gathers all metadata from the UI and data model and prepares a list of tasks
        for the ExifWriteWorker.
        """
        tasks = []
        # Load all presets once to be efficient
        all_presets = {
            'cameras': preset_manager.load_presets('cameras'),
            'lenses': preset_manager.load_presets('lenses'),
            'film_stocks': preset_manager.load_presets('film_stocks')
        }

        for path, data in self.image_data.items():
            final_exif = {}

            # 1. Get full preset data
            camera_name = data.get('Camera')
            if camera_name and camera_name in all_presets['cameras']:
                final_exif.update(all_presets['cameras'][camera_name])

            film_name = data.get('FilmStock')
            if film_name and film_name in all_presets['film_stocks']:
                final_exif.update(all_presets['film_stocks'][film_name])

            lens_name = data.get('Lens')
            if lens_name and lens_name in all_presets['lenses']:
                final_exif.update(all_presets['lenses'][lens_name])
            
            # 2. Map UI fields to EXIF tags and overwrite
            if data.get('Aperture'):
                final_exif['FNumber'] = data['Aperture']
            if data.get('ShutterSpeed'):
                final_exif['ShutterSpeedValue'] = data['ShutterSpeed']
            if data.get('RollNotes'):
                final_exif['ImageDescription'] = data['RollNotes']
            
            # 3. Clean up empty values
            final_exif_cleaned = {k: v for k, v in final_exif.items() if v}
            tasks.append((path, final_exif_cleaned))
        
        return tasks

    def _on_apply_finished(self, success: bool, message: str):
        """Handles the completion of the EXIF writing process."""
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage("Ready.")
        
        if success:
            backup_path = message
            QMessageBox.information(self, "Success", "Metadata applied to all files successfully.")
            
            # Ask to delete backup if it was created
            if self.backup_checkbox.isChecked() and os.path.exists(backup_path):
                reply = QMessageBox.question(self, "Delete Backup",
                                             f"Do you want to delete the temporary backup folder?\n\n{backup_path}",
                                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                             QMessageBox.StandardButton.Yes)
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        shutil.rmtree(backup_path)
                        self.status_bar.showMessage("Temporary backup deleted.", 5000)
                    except Exception as e:
                        QMessageBox.warning(self, "Error", f"Could not delete backup folder: {e}")

        else: # On failure
            QMessageBox.critical(self, "Process Failed", message)

        self._set_ui_enabled(True)
        self.write_thread.quit()
        self.write_thread.wait()

    def _set_ui_enabled(self, enabled: bool):
        """Enables or disables the entire UI during processing."""
        self.main_splitter.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)
        self.load_button.setEnabled(enabled)
        self.apply_button.setEnabled(enabled)
        self.backup_checkbox.setEnabled(enabled)

    # --- Other methods from here on are mostly unchanged ---
    def _on_batch_camera_changed(self, index):
        if self._is_updating_ui: return
        camera_name = self.camera_combo.itemText(index)
        for path in self.image_data: self.image_data[path]['Camera'] = camera_name

    def _on_batch_film_stock_changed(self, index):
        if self._is_updating_ui: return
        film_name = self.film_stock_combo.itemText(index)
        for path in self.image_data: self.image_data[path]['FilmStock'] = film_name
        
    def _on_batch_notes_changed(self):
        if self._is_updating_ui: return
        notes = self.roll_notes_edit.toPlainText()
        for path in self.image_data: self.image_data[path]['RollNotes'] = notes

    def _on_selection_lens_changed(self, index):
        if self._is_updating_ui: return
        lens_name = self.lens_combo.itemText(index)
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data: self.image_data[path]['Lens'] = lens_name

    def _on_selection_aperture_changed(self, text):
        if self._is_updating_ui: return
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data: self.image_data[path]['Aperture'] = text
        
    def _on_selection_shutter_changed(self, text):
        if self._is_updating_ui: return
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data: self.image_data[path]['ShutterSpeed'] = text

    def _on_filmstrip_selection_changed(self):
        self._is_updating_ui = True
        selected_items = self.filmstrip_list.selectedItems()
        if not selected_items:
            self.lens_combo.setCurrentIndex(0)
            self.aperture_edit.clear()
            self.shutter_edit.clear()
        elif len(selected_items) == 1:
            item = selected_items[0]
            path = item.data(Qt.ItemDataRole.UserRole)
            data = self.image_data.get(path, {})
            self.lens_combo.setCurrentText(data.get('Lens', '--- Select Lens ---'))
            self.aperture_edit.setText(data.get('Aperture', ''))
            self.shutter_edit.setText(data.get('ShutterSpeed', ''))
        else:
            self.lens_combo.setCurrentIndex(0)
            self.aperture_edit.setPlaceholderText("Multiple Values")
            self.aperture_edit.clear()
            self.shutter_edit.setPlaceholderText("Multiple Values")
            self.shutter_edit.clear()
        self._is_updating_ui = False

    def _load_roll(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Roll Folder")
        if not directory: return
        self.filmstrip_list.clear()
        self.image_data.clear()
        supported_extensions = ('.jpg', '.jpeg', '.tif', '.tiff', '.png', '.heic')
        image_files = [os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith(supported_extensions)]
        if not image_files:
            self.status_bar.showMessage("No compatible image files found.", 5000)
            return
        for path in image_files: self.image_data[path] = {}
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
            self._on_batch_camera_changed(self.camera_combo.currentIndex())
            self._on_batch_film_stock_changed(self.film_stock_combo.currentIndex())

    def open_preset_editor(self):
        dialog = PresetEditorDialog(self)
        dialog.exec()
        self._populate_preset_combos()

    def _populate_preset_combos(self):
        # This function remains unchanged
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
        # This function remains unchanged
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
        # This function remains unchanged
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
        # This function remains unchanged
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
        # This function remains unchanged
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        edit_menu = menu_bar.addMenu("&Edit")
        manage_presets_action = QAction("Manage Presets...", self)
        manage_presets_action.triggered.connect(self.open_preset_editor)
        edit_menu.addAction(manage_presets_action)

    def _create_status_bar(self):
        # This function remains unchanged
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.load_button = QPushButton("Load Roll...")
        self.load_button.clicked.connect(self._load_roll)
        self.backup_checkbox = QCheckBox("Create temporary backup")
        self.backup_checkbox.setChecked(True)
        self.backup_checkbox.setToolTip("If checked, original files will be backed up before metadata is written.")
        self.apply_button = QPushButton("Apply Changes")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.load_button)
        self.status_bar.addPermanentWidget(self.backup_checkbox)
        self.status_bar.addPermanentWidget(self.apply_button)
        self.status_bar.addPermanentWidget(self.progress_bar)

