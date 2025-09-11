import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QListWidget, QPushButton, QLineEdit, QDialogButtonBox,
    QMessageBox, QLabel, QFormLayout
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
            # Define the fields for each preset type
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
                fields_definition = {"ISO": "e.g., 200", "FilmType": "e.g., Color Negative"}

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
        layout.addWidget(self.preset_list, 2) # Give more space to the list

        button_layout = QVBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.delete_button = QPushButton("Delete")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
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

            # Remove old entry and add new one
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

