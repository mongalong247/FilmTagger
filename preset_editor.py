import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QListWidget, QPushButton, QLineEdit, QDialogButtonBox,
    QMessageBox, QFormLayout, QGroupBox, QLabel, QFileDialog
)

import preset_manager


class PresetEditorDialog(QDialog):
    """A dialog for managing detailed presets for cameras, lenses, and film."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preset Manager")
        self.setMinimumSize(500, 400)
        main_layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self.tabs = {}
        for preset_type in preset_manager.PRESET_TYPES:
            tab_title = preset_type.replace('_', ' ').title()
            fields_definition = {}
            if preset_type == 'cameras':
                fields_definition = {"Make": "e.g., Nikon", "Model": "e.g., F3"}
            elif preset_type == 'lenses':
                fields_definition = {
                    "LensMake": "e.g., Canon",
                    "LensModel": "e.g., nFD",
                    "FocalLength": "e.g., 50mm",
                    "FNumber": "e.g., 1.4",
                    "LensSerialNumber": "Optional"
                }
            elif preset_type == 'film_stocks':
                fields_definition = {"ISO": "e.g., 200 (box speed)", "FilmType": "e.g., Color Negative"}

            management_widget = PresetManagementWidget(preset_type, fields_definition)
            self.tab_widget.addTab(management_widget, tab_title)
            self.tabs[preset_type] = management_widget

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        main_layout.addWidget(button_box)


class PresetManagementWidget(QWidget):
    """A generic widget for managing a list of presets with detailed fields."""
    def __init__(self, preset_type: str, fields_definition: dict, parent=None):
        super().__init__(parent)
        self.preset_type = preset_type
        self.fields_definition = fields_definition
        self.presets = preset_manager.load_presets(self.preset_type)

        layout = QHBoxLayout(self)
        self.preset_list = QListWidget()
        layout.addWidget(self.preset_list, 2)

        button_layout = QVBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.delete_button = QPushButton("Delete")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()

        io_group = QGroupBox("Backup & Sharing")
        io_layout = QVBoxLayout(io_group)
        io_layout.addWidget(QLabel("Export all presets in this tab to a file, or import from one."))
        io_button_layout = QHBoxLayout()
        self.export_button = QPushButton("Export...")
        self.export_button.setToolTip(f"Save all {self.preset_type.replace('_', ' ')} presets to a .json file.")
        self.export_button.clicked.connect(self._on_export_presets)
        self.import_button = QPushButton("Import...")
        self.import_button.setToolTip("Load presets from a previously exported .json file.")
        self.import_button.clicked.connect(self._on_import_presets)
        io_button_layout.addStretch(1)
        io_button_layout.addWidget(self.import_button)
        io_button_layout.addWidget(self.export_button)
        io_layout.addLayout(io_button_layout)
        button_layout.addWidget(io_group)

        layout.addLayout(button_layout, 1)

        self._populate_list()
        self.add_button.clicked.connect(self._add_preset)
        self.edit_button.clicked.connect(self._edit_preset)
        self.delete_button.clicked.connect(self._delete_preset)
        self.preset_list.itemDoubleClicked.connect(self._edit_preset)

    def _populate_list(self):
        self.preset_list.clear()
        for name in sorted(self.presets.keys()):
            self.preset_list.addItem(name)

    def _add_preset(self):
        dialog = PresetDataDialog(f"Add New {self.preset_type.replace('_', ' ').title()}", self.fields_definition)
        if dialog.exec():
            preset_name, data = dialog.get_data()
            if not preset_name:
                QMessageBox.warning(self, "Input Error", "Preset name cannot be empty.")
                return
            if preset_name in self.presets:
                QMessageBox.warning(self, "Input Error", "A preset with this name already exists.")
                return
            self.presets[preset_name] = data
            preset_manager.save_presets(self.preset_type, self.presets)
            self._populate_list()

    def _edit_preset(self):
        selected_item = self.preset_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Error", "Please select a preset to edit.")
            return

        original_name = selected_item.text()
        existing_data = self.presets.get(original_name, {})

        dialog = PresetDataDialog(f"Edit {original_name}", self.fields_definition, existing_data, original_name)
        if dialog.exec():
            new_name, new_data = dialog.get_data()
            if not new_name:
                QMessageBox.warning(self, "Input Error", "Preset name cannot be empty.")
                return

            if new_name != original_name and new_name in self.presets:
                QMessageBox.warning(self, "Input Error", "A preset with this name already exists.")
                return

            del self.presets[original_name]
            self.presets[new_name] = new_data
            preset_manager.save_presets(self.preset_type, self.presets)
            self._populate_list()

    def _delete_preset(self):
        selected_item = self.preset_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Error", "Please select a preset to delete.")
            return
        preset_name = selected_item.text()
        reply = QMessageBox.question(self, "Confirm Delete",
                                     f"Are you sure you want to delete '{preset_name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if preset_name in self.presets:
                del self.presets[preset_name]
                preset_manager.save_presets(self.preset_type, self.presets)
                self._populate_list()


    # --- Export / Import (ported from ImageImporter's metadata_panel.py) ---

    def _on_export_presets(self):
        """Exports this tab's presets to a user-chosen .json file."""
        if not self.presets:
            QMessageBox.information(self, "Nothing to Export",
                                     f"There are no saved {self.preset_type.replace('_', ' ')} presets to export yet.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Presets", f"{self.preset_type}_export.json", "JSON Files (*.json)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        try:
            with open(file_path, 'w') as f:
                json.dump(self.presets, f, indent=4)
            QMessageBox.information(self, "Export Complete", f"Exported {len(self.presets)} preset(s) to:\n{file_path}")
        except IOError as e:
            QMessageBox.critical(self, "Export Failed", f"Could not write to that file:\n{e}")

    @staticmethod
    def _is_valid_presets_structure(data) -> bool:
        """
        Validates that imported data has the expected shape: a dict mapping
        preset name (str) -> preset fields (dict). Rejects anything else so
        a malformed or hand-edited file can't corrupt the preset store or
        crash the panel later when it expects certain keys/types.
        """
        if not isinstance(data, dict):
            return False
        for name, preset_data in data.items():
            if not isinstance(name, str) or not isinstance(preset_data, dict):
                return False
        return True

    def _on_import_presets(self):
        """Imports presets into this tab from a user-chosen .json file, with conflict handling."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Presets", "", "JSON Files (*.json)")
        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                imported_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            QMessageBox.critical(self, "Import Failed", f"Could not read that file as valid JSON:\n{e}")
            return

        if not self._is_valid_presets_structure(imported_data):
            QMessageBox.critical(
                self, "Import Failed",
                "That file doesn't look like a valid presets export. Expected a JSON object "
                "mapping preset names to preset fields."
            )
            return

        if not imported_data:
            QMessageBox.information(self, "Nothing to Import", "That file doesn't contain any presets.")
            return

        # Note: this only validates shape (name -> dict of fields), not the
        # specific field names for this preset type. Importing a file
        # exported from a different tab/app (e.g. ImageImporter's lens
        # presets, which also carry an "ImageDescription" field this tab
        # doesn't show) still works -- unrecognized fields are preserved
        # and simply won't appear in the Add/Edit form.
        conflicts = sorted(set(imported_data.keys()) & set(self.presets.keys()))
        overwrite_conflicts = True

        if conflicts:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Preset Conflicts")
            msg_box.setText(
                f"{len(conflicts)} preset(s) in this file have the same name as existing presets:\n\n"
                + ", ".join(conflicts)
                + "\n\nHow would you like to handle these?"
            )
            overwrite_btn = msg_box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
            skip_btn = msg_box.addButton("Skip Conflicts", QMessageBox.ButtonRole.ActionRole)
            cancel_btn = msg_box.addButton("Cancel Import", QMessageBox.ButtonRole.RejectRole)
            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == cancel_btn:
                return
            overwrite_conflicts = (clicked == overwrite_btn)

        imported_count = 0
        skipped_count = 0
        for name, preset_data in imported_data.items():
            if name in self.presets and not overwrite_conflicts:
                skipped_count += 1
                continue
            self.presets[name] = preset_data
            imported_count += 1

        preset_manager.save_presets(self.preset_type, self.presets)
        self._populate_list()

        summary = f"Imported {imported_count} preset(s)."
        if skipped_count:
            summary += f" Skipped {skipped_count} conflicting preset(s)."
        QMessageBox.information(self, "Import Complete", summary)


class PresetDataDialog(QDialog):
    """A generic dialog for entering/editing data for a single preset."""
    def __init__(self, title, fields_definition, existing_data=None, preset_name=""):
        super().__init__()
        self.setWindowTitle(title)
        form_layout = QFormLayout(self)

        self.name_edit = QLineEdit(preset_name)
        form_layout.addRow("Preset Name:", self.name_edit)

        self.fields = {}
        for key, placeholder in fields_definition.items():
            current_value = existing_data.get(key, "") if existing_data else ""
            self.fields[key] = QLineEdit(current_value)
            self.fields[key].setPlaceholderText(placeholder)
            form_layout.addRow(f"{key}:", self.fields[key])

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form_layout.addWidget(button_box)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    def get_data(self):
        preset_name = self.name_edit.text().strip()
        data = {key: field.text().strip() for key, field in self.fields.items()}
        return preset_name, data
