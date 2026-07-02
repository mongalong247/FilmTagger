import os
import re
import shutil

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QComboBox, QTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QGroupBox, QStatusBar, QProgressBar, QFileDialog, QCheckBox,
    QDialog, QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QThread, QThreadPool, QSize, QSettings, QUrl
from PySide6.QtGui import QAction, QIcon, QPainter, QColor, QPixmap, QDesktopServices

import preset_manager
import exiftool_manager
from preset_editor import PresetEditorDialog
from workers import ThumbnailTask, ExifWriteWorker

APP_VERSION = "0.1.0"
NORMAL_STYLE = "color: gray; font-style: italic;"
OK_STYLE = "color: #2e7d32;"
WARNING_STYLE = "color: #b26a00; font-weight: bold;"

# Kept in sync by hand with ImageImporter's IMAGE_EXTENSIONS list (app.py).
# If that list grows, mirror the change here.
IMAGE_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.heic', '.heif', '.tif', '.tiff',
    '.cr2', '.cr3', '.nef', '.arw', '.dng', '.rw2',
    '.orf', '.raf', '.pef', '.srw', '.rwl', '.3fr', '.raw',
)

SETTINGS_ORG = "PhotoTagger"
SETTINGS_APP = "FilmTagger"


def _natural_sort_key(path: str):
    """
    Sort key that orders paths the way a person would (frame2 before
    frame10), not plain alphabetically (which would put frame10 before
    frame2). Splits on runs of digits and treats each digit run as an
    integer. Uses the full (normalized) path rather than just the
    filename, so a recursive load groups files by folder first, then
    orders naturally within each folder.
    """
    normalized = path.replace("\\", "/")
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r'(\d+)', normalized)]


class ApplyPreviewDialog(QDialog):
    """
    Shows exactly what's about to be written before any file is touched.
    Rows for frames missing Lens/Aperture/Shutter (the per-frame fields set
    in stage two of the workflow) are highlighted, so a skipped frame is
    obvious before you commit rather than after.
    """
    def __init__(self, image_data: dict, ordered_paths: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Before Applying")
        self.resize(950, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"About to write metadata to {len(ordered_paths)} file(s). "
            "Rows highlighted in orange are missing a lens, aperture, or shutter speed value."
        ))

        columns = ["Filename", "Camera", "Film Stock", "ISO", "Lens", "Aperture", "Shutter", "Notes"]
        table = QTableWidget(len(ordered_paths), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)

        for row, path in enumerate(ordered_paths):
            data = image_data.get(path, {})
            incomplete = not (data.get('Lens') and data.get('Aperture') and data.get('ShutterSpeed'))
            values = [
                os.path.basename(path), data.get('Camera', ''), data.get('FilmStock', ''),
                data.get('ISO', ''), data.get('Lens', ''), data.get('Aperture', ''),
                data.get('ShutterSpeed', ''), data.get('RollNotes', ''),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if incomplete:
                    item.setBackground(QColor("#fff3e0"))
                    item.setForeground(QColor("#b26a00"))
                table.setItem(row, col, item)

        layout.addWidget(table)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Apply Changes")
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class BackupCleanupDialog(QDialog):
    """
    Asks what to do with a completed backup, with a way to actually look at
    it first rather than deleting or keeping it blind. "Open Backup Folder"
    does not close the dialog, so you can check the files and come back.
    """
    def __init__(self, backup_path: str, parent=None):
        super().__init__(parent)
        self.backup_path = backup_path
        self.setWindowTitle("Temporary Backup")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "A backup of the original files was made before writing metadata:\n\n"
            f"{backup_path}\n\n"
            "You can open the folder to check the originals are intact before "
            "deciding whether to delete this backup."
        ))
        button_layout = QHBoxLayout()
        open_button = QPushButton("Open Backup Folder")
        open_button.clicked.connect(self._open_folder)
        button_layout.addWidget(open_button)
        button_layout.addStretch()
        keep_button = QPushButton("Keep Backup")
        keep_button.setDefault(True)
        keep_button.clicked.connect(self.reject)
        delete_button = QPushButton("Delete Backup")
        delete_button.clicked.connect(self.accept)
        button_layout.addWidget(keep_button)
        button_layout.addWidget(delete_button)
        layout.addLayout(button_layout)

    def _open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.backup_path))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Film Tagger")
        self.setGeometry(100, 100, 1200, 700)

        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        self.threadpool = QThreadPool.globalInstance()
        self._load_generation = 0  # bumped on every _load_roll call; used to
                                    # discard thumbnail results from a roll
                                    # that's since been superseded
        self.write_thread = None
        self.write_worker = None
        self.image_data = {}
        self._filmstrip_items = {}  # image_path -> QListWidgetItem, so async
                                     # thumbnail results update in place and
                                     # never disturb frame order
        self._is_updating_ui = False
        self.exiftool_available = False

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.main_splitter)

        self._create_batch_metadata_panel()
        self._create_filmstrip_panel()
        self._create_selection_metadata_panel()
        self.main_splitter.addWidget(self.batch_metadata_group)
        self.main_splitter.addWidget(self.filmstrip_group)
        self.main_splitter.addWidget(self.selection_metadata_group)
        self.main_splitter.setSizes([260, 680, 260])

        self._create_menu_bar()
        self._create_status_bar()

        self._populate_preset_combos()
        self._connect_signals()
        self._load_last_source_folder()
        self._refresh_exiftool_status()

    # --- Signal wiring ---

    def _connect_signals(self):
        self.filmstrip_list.itemSelectionChanged.connect(self._on_filmstrip_selection_changed)
        self.camera_combo.currentIndexChanged.connect(self._on_batch_camera_changed)
        self.film_stock_combo.currentIndexChanged.connect(self._on_batch_film_stock_changed)
        self.iso_edit.textChanged.connect(self._on_batch_iso_changed)
        self.roll_notes_edit.textChanged.connect(self._on_batch_notes_changed)
        self.lens_combo.currentIndexChanged.connect(self._on_selection_lens_changed)
        self.aperture_edit.textChanged.connect(self._on_selection_aperture_changed)
        self.shutter_edit.textChanged.connect(self._on_selection_shutter_changed)
        self.apply_button.clicked.connect(self._apply_changes)

    # --- Applying metadata ---

    def _apply_changes(self):
        if not self.image_data:
            QMessageBox.warning(self, "No Images Loaded", "Please load a roll of film before applying changes.")
            return
        if not self.exiftool_available:
            QMessageBox.warning(self, "ExifTool Unavailable",
                                 "ExifTool isn't available, so metadata can't be written. "
                                 "Check Settings > Set ExifTool Path...")
            return

        ordered_paths = [self.filmstrip_list.item(i).data(Qt.ItemDataRole.UserRole)
                          for i in range(self.filmstrip_list.count())]
        preview = ApplyPreviewDialog(self.image_data, ordered_paths, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return

        tasks = self._prepare_task_list()
        if not tasks:
            QMessageBox.critical(self, "Error", "Could not prepare data for writing. Please check your presets.")
            return
        self._set_ui_enabled(False)
        self.status_bar.showMessage("Applying changes...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        backup_enabled = self.backup_checkbox.isChecked()
        self.write_worker = ExifWriteWorker(tasks, backup_enabled)
        self.write_thread = QThread()
        self.write_worker.moveToThread(self.write_thread)
        self.write_worker.progress.connect(self._on_write_progress)
        self.write_worker.finished.connect(self._on_apply_finished)
        self.write_thread.started.connect(self.write_worker.run)
        self.write_thread.start()

    def _on_write_progress(self, value: int, message: str):
        self.progress_bar.setValue(value)
        self.status_bar.showMessage(message)

    def _prepare_task_list(self) -> list:
        tasks = []
        all_presets = {
            'cameras': preset_manager.load_presets('cameras'),
            'lenses': preset_manager.load_presets('lenses'),
        }
        for path, data in self.image_data.items():
            final_exif = {}

            camera_name = data.get('Camera')
            if camera_name and camera_name in all_presets['cameras']:
                final_exif.update(all_presets['cameras'][camera_name])

            lens_name = data.get('Lens')
            if lens_name and lens_name in all_presets['lenses']:
                final_exif.update(all_presets['lenses'][lens_name])

            if data.get('Aperture'):
                final_exif['FNumber'] = data['Aperture']
            if data.get('ShutterSpeed'):
                final_exif['ShutterSpeedValue'] = data['ShutterSpeed']
            if data.get('RollNotes'):
                final_exif['ImageDescription'] = data['RollNotes']
            if data.get('ISO'):
                final_exif['ISO'] = data['ISO']
            if data.get('FilmStock'):
                # Film stock has no standard EXIF tag. Written as a
                # fully-qualified XMP tag so exiftool_manager writes it
                # verbatim as a searchable keyword/subject rather than a
                # caption.
                final_exif['XMP-dc:Subject'] = data['FilmStock']

            final_exif_cleaned = {k: v for k, v in final_exif.items() if v}
            tasks.append((path, final_exif_cleaned))
        return tasks

    def _on_apply_finished(self, result: dict):
        self.progress_bar.setVisible(False)
        self.status_bar.showMessage("Ready.")

        succeeded = result['succeeded']
        failed = result['failed']
        backup_path = result['backup_path']
        cancelled = result['cancelled']

        if failed:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Completed With Errors")
            summary = f"{succeeded} file(s) tagged successfully.\n{len(failed)} file(s) failed"
            summary += " (batch was cancelled before finishing)." if cancelled else "."
            msg.setText(summary)
            msg.setDetailedText("\n".join(f"{name}: {reason}" for name, reason in failed))
            msg.exec()
        elif cancelled:
            QMessageBox.information(self, "Cancelled", f"Cancelled after tagging {succeeded} file(s).")
        else:
            QMessageBox.information(self, "Success", f"Metadata applied to all {succeeded} file(s) successfully.")

        # Only offer to clean up the backup if nothing failed. If some files
        # failed, the backup is kept regardless of the checkbox state until
        # the user has had a chance to investigate -- it's the only safety
        # net for whatever went wrong.
        if not failed and self.backup_checkbox.isChecked() and backup_path and os.path.exists(backup_path):
            dialog = BackupCleanupDialog(backup_path, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    shutil.rmtree(backup_path)
                    self.status_bar.showMessage("Temporary backup deleted.", 5000)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not delete backup folder: {e}")

        self._set_ui_enabled(True)
        if self.write_thread:
            self.write_thread.quit()
            self.write_thread.wait()
        self.write_thread = None
        self.write_worker = None

    def _set_ui_enabled(self, enabled: bool):
        self.main_splitter.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)
        self.load_button.setEnabled(enabled)
        self.apply_button.setEnabled(enabled and self.exiftool_available)
        self.backup_checkbox.setEnabled(enabled)
        self.recursive_checkbox.setEnabled(enabled)

    # --- Batch panel handlers ---

    def _on_batch_camera_changed(self, index):
        if self._is_updating_ui:
            return
        camera_name = self.camera_combo.itemText(index)
        for path in self.image_data:
            self.image_data[path]['Camera'] = camera_name

    def _on_batch_film_stock_changed(self, index):
        if self._is_updating_ui:
            return
        film_name = self.film_stock_combo.itemText(index)
        for path in self.image_data:
            self.image_data[path]['FilmStock'] = film_name

        # Pre-fill ISO from the film stock's box speed. Left editable so a
        # pushed/pulled roll can be overridden without touching the preset.
        film_presets = preset_manager.load_presets('film_stocks')
        default_iso = film_presets.get(film_name, {}).get('ISO', '')
        self.iso_edit.setText(default_iso)

    def _on_batch_iso_changed(self, text):
        if self._is_updating_ui:
            return
        for path in self.image_data:
            self.image_data[path]['ISO'] = text

    def _on_batch_notes_changed(self):
        if self._is_updating_ui:
            return
        notes = self.roll_notes_edit.toPlainText()
        for path in self.image_data:
            self.image_data[path]['RollNotes'] = notes

    def _update_frame_indicator(self, path: str):
        """
        Flags a frame in the filmstrip as still needing per-frame data
        (Lens/Aperture/Shutter -- the stage-two fields) so it's visible at
        a glance while browsing, not just discovered later in the preview
        dialog or after writing.
        """
        item = self._filmstrip_items.get(path)
        if item is None:
            return
        data = self.image_data.get(path, {})
        complete = bool(data.get('Lens')) and bool(data.get('Aperture')) and bool(data.get('ShutterSpeed'))
        filename = os.path.basename(path)
        if complete:
            item.setText(filename)
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
        else:
            item.setText(f"\u26a0 {filename}")
            item.setForeground(QColor("#b26a00"))

    # --- Selection panel handlers ---

    def _on_selection_lens_changed(self, index):
        if self._is_updating_ui:
            return
        lens_name = self.lens_combo.itemText(index)
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['Lens'] = lens_name
                self._update_frame_indicator(path)

    def _on_selection_aperture_changed(self, text):
        if self._is_updating_ui:
            return
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['Aperture'] = text
                self._update_frame_indicator(path)

    def _on_selection_shutter_changed(self, text):
        if self._is_updating_ui:
            return
        for item in self.filmstrip_list.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.image_data:
                self.image_data[path]['ShutterSpeed'] = text
                self._update_frame_indicator(path)

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

    # --- Loading a roll ---

    def _load_roll(self):
        start_dir = self.settings.value("lastSourceFolder", "")
        directory = QFileDialog.getExistingDirectory(self, "Select Roll Folder", start_dir)
        if not directory:
            return

        self.settings.setValue("lastSourceFolder", directory)
        self.filmstrip_list.clear()
        self.image_data.clear()
        self._filmstrip_items.clear()
        self._load_generation += 1
        generation = self._load_generation

        if self.recursive_checkbox.isChecked():
            image_files = []
            for root, _dirs, files in os.walk(directory):
                for f in files:
                    if f.lower().endswith(IMAGE_EXTENSIONS):
                        image_files.append(os.path.join(root, f))
        else:
            image_files = [
                os.path.join(directory, f) for f in os.listdir(directory)
                if f.lower().endswith(IMAGE_EXTENSIONS) and os.path.isfile(os.path.join(directory, f))
            ]
        image_files.sort(key=_natural_sort_key)
        if not image_files:
            self.status_bar.showMessage("No compatible image files found.", 5000)
            return

        # Populate placeholder items in the final, correct order up front.
        # Thumbnails are then filled in *in place* as each background task
        # finishes (which can happen in any order) rather than appended,
        # so frame order on screen never depends on thread completion timing.
        placeholder_icon = self._create_placeholder_icon()
        for path in image_files:
            self.image_data[path] = {}
            item = QListWidgetItem(placeholder_icon, os.path.basename(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.filmstrip_list.addItem(item)
            self._filmstrip_items[path] = item
            self._update_frame_indicator(path)

        self.status_bar.showMessage(f"Loading {len(image_files)} images...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(image_files))
        self.progress_bar.setValue(0)

        for image_path in image_files:
            task = ThumbnailTask(image_path, generation=generation)
            task.signals.finished.connect(self._add_thumbnail_to_filmstrip)
            self.threadpool.start(task)

    def _create_placeholder_icon(self) -> QIcon:
        """Creates a generic grey placeholder icon for failed/pending thumbnails."""
        size = self.filmstrip_list.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(QColor("lightgray"))

        painter = QPainter(pixmap)
        painter.setPen(QColor("black"))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "No Preview")
        painter.end()

        return QIcon(pixmap)

    def _add_thumbnail_to_filmstrip(self, image_path, icon, generation):
        # Discard results from a roll load that's since been superseded by
        # a newer one, so a slow thumbnail from the previous folder can't
        # land in the currently-displayed filmstrip.
        if generation != self._load_generation:
            return

        item = self._filmstrip_items.get(image_path)
        if item is None:
            return

        if not icon.isNull():
            item.setIcon(icon)
        # else: leave the placeholder icon already on the item in place.

        current_value = self.progress_bar.value() + 1
        self.progress_bar.setValue(current_value)
        if current_value == self.progress_bar.maximum():
            self.status_bar.showMessage("Roll loaded successfully.", 5000)
            self.progress_bar.setVisible(False)
            self._on_batch_camera_changed(self.camera_combo.currentIndex())
            self._on_batch_film_stock_changed(self.film_stock_combo.currentIndex())

    def _load_last_source_folder(self):
        """Just restores the file-dialog starting point; doesn't auto-load images."""
        pass

    # --- Presets ---

    def open_preset_editor(self):
        dialog = PresetEditorDialog(self)
        dialog.exec()
        self._populate_preset_combos()

    def _populate_preset_combos(self):
        self.camera_combo.clear()
        self.camera_combo.addItem("--- Select Camera ---")
        self.camera_combo.addItems(sorted(preset_manager.load_presets('cameras').keys()))
        self.film_stock_combo.clear()
        self.film_stock_combo.addItem("--- Select Film Stock ---")
        self.film_stock_combo.addItems(sorted(preset_manager.load_presets('film_stocks').keys()))
        self.lens_combo.clear()
        self.lens_combo.addItem("--- Select Lens ---")
        self.lens_combo.addItems(sorted(preset_manager.load_presets('lenses').keys()))
        self.camera_combo.setEnabled(True)
        self.film_stock_combo.setEnabled(True)
        self.iso_edit.setEnabled(True)
        self.roll_notes_edit.setEnabled(True)
        self.lens_combo.setEnabled(True)
        self.aperture_edit.setEnabled(True)
        self.shutter_edit.setEnabled(True)

    # --- ExifTool status & configuration ---

    def _refresh_exiftool_status(self):
        success, message = exiftool_manager.ensure_exiftool_available()
        self.exiftool_available = success
        # Keep the status bar label short -- the full message (which can be
        # a long sentence with a URL in it) goes in the tooltip instead.
        # Putting the whole message directly into a permanent status bar
        # widget forces Qt to size the label (and therefore the window's
        # minimum width) to fit it on one line, which can exceed the
        # screen width on smaller/narrower monitors.
        self.exiftool_status_label.setText("ExifTool: OK" if success else "ExifTool: Unavailable")
        self.exiftool_status_label.setToolTip(message)
        self.exiftool_status_label.setStyleSheet(OK_STYLE if success else WARNING_STYLE)
        self.apply_button.setEnabled(success)
        self.apply_button.setToolTip(
            "" if success else "ExifTool is unavailable -- set a path in Settings > Set ExifTool Path..."
        )

    def _on_set_exiftool_path(self):
        import platform
        exe_filter = "exiftool.exe (exiftool.exe)" if platform.system() == "Windows" else "exiftool (exiftool)"
        path, _ = QFileDialog.getOpenFileName(self, "Select ExifTool Executable", "", exe_filter + ";;All Files (*)")
        if not path:
            return
        exiftool_manager.set_custom_path(path)
        self._refresh_exiftool_status()

    def _on_clear_exiftool_path(self):
        exiftool_manager.set_custom_path("")
        self._refresh_exiftool_status()
        QMessageBox.information(self, "ExifTool Path Cleared",
                                 "Custom path cleared. The app will auto-detect ExifTool again.")

    def _show_about_dialog(self):
        QMessageBox.about(
            self, "About Film Tagger",
            f"<b>Film Tagger</b><p>Version: {APP_VERSION}</p>"
            "<p>Adds camera, film stock, lens, aperture and shutter speed metadata "
            "to scanned or digitally-photographed 35mm film rolls.</p>"
        )

    # --- UI construction ---

    def _create_batch_metadata_panel(self):
        self.batch_metadata_group = QGroupBox("Batch Metadata (Entire Roll)")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Camera Body:"))
        self.camera_combo = QComboBox()
        layout.addWidget(self.camera_combo)
        layout.addWidget(QLabel("Film Stock:"))
        self.film_stock_combo = QComboBox()
        layout.addWidget(self.film_stock_combo)
        layout.addWidget(QLabel("ISO (box speed, or as shot if pushed/pulled):"))
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("e.g., 200")
        layout.addWidget(self.iso_edit)
        layout.addWidget(QLabel("Roll Notes:"))
        self.roll_notes_edit = QTextEdit()
        layout.addWidget(self.roll_notes_edit)
        layout.addStretch()
        self.batch_metadata_group.setLayout(layout)

    def _create_filmstrip_panel(self):
        self.filmstrip_group = QGroupBox("Filmstrip View")
        layout = QVBoxLayout()
        self.filmstrip_list = QListWidget()
        # IconMode is what actually gives grid/contact-sheet layout;
        # Flow + Wrapping alone (the previous setup) still uses ListMode's
        # row-based layout rules underneath, which is why wrapping looked
        # wrong before.
        self.filmstrip_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.filmstrip_list.setMovement(QListWidget.Movement.Static)
        self.filmstrip_list.setIconSize(QSize(180, 180))
        self.filmstrip_list.setGridSize(QSize(210, 220))
        self.filmstrip_list.setSpacing(8)
        self.filmstrip_list.setFlow(QListWidget.Flow.LeftToRight)
        self.filmstrip_list.setWrapping(True)
        self.filmstrip_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.filmstrip_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.filmstrip_list.setWordWrap(True)
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

        edit_menu = menu_bar.addMenu("&Edit")
        manage_presets_action = QAction("Manage Presets...", self)
        manage_presets_action.triggered.connect(self.open_preset_editor)
        edit_menu.addAction(manage_presets_action)

        settings_menu = menu_bar.addMenu("&Settings")
        exiftool_path_action = QAction("Set &ExifTool Path...", self)
        exiftool_path_action.triggered.connect(self._on_set_exiftool_path)
        settings_menu.addAction(exiftool_path_action)
        clear_exiftool_path_action = QAction("&Clear Custom ExifTool Path", self)
        clear_exiftool_path_action.triggered.connect(self._on_clear_exiftool_path)
        settings_menu.addAction(clear_exiftool_path_action)

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.exiftool_status_label = QLabel("ExifTool: checking...")
        self.exiftool_status_label.setStyleSheet(NORMAL_STYLE)
        # Hard cap so no future status text (long paths, long messages) can
        # blow out the status bar's minimum width the way the original
        # unwrapped warning message did.
        self.exiftool_status_label.setMaximumWidth(160)
        self.status_bar.addPermanentWidget(self.exiftool_status_label)

        self.load_button = QPushButton("Load Roll...")
        self.load_button.clicked.connect(self._load_roll)
        self.recursive_checkbox = QCheckBox("Include subfolders")
        self.recursive_checkbox.setToolTip("Search subfolders too, for rolls organized in nested date/roll folders.")
        self.recursive_checkbox.setChecked(self.settings.value("recursiveLoad", False, type=bool))
        self.recursive_checkbox.toggled.connect(lambda checked: self.settings.setValue("recursiveLoad", checked))
        self.backup_checkbox = QCheckBox("Create temporary backup")
        self.backup_checkbox.setChecked(self.settings.value("backupEnabled", True, type=bool))
        self.backup_checkbox.setToolTip("If checked, original files will be backed up before metadata is written.")
        self.backup_checkbox.toggled.connect(lambda checked: self.settings.setValue("backupEnabled", checked))
        self.apply_button = QPushButton("Apply Changes")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.load_button)
        self.status_bar.addPermanentWidget(self.recursive_checkbox)
        self.status_bar.addPermanentWidget(self.backup_checkbox)
        self.status_bar.addPermanentWidget(self.apply_button)
        self.status_bar.addPermanentWidget(self.progress_bar)

    # --- Shutdown ---

    def closeEvent(self, event):
        if self.write_worker:
            self.write_worker.stop()
        if self.write_thread and self.write_thread.isRunning():
            self.write_thread.quit()
            self.write_thread.wait()
        # Bump the generation so any thumbnail results still in flight are
        # discarded rather than touching a filmstrip that's about to close.
        self._load_generation += 1
        self.threadpool.waitForDone(3000)
        event.accept()
