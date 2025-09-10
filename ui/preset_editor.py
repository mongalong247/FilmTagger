import sys
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QListWidget, QPushButton, QLineEdit, QDialogButtonBox,
    QMessageBox, QLabel, QFormLayout
)
# We need to import our preset manager to use its functions
import preset_manager

class PresetEditorDialog(QDialog):
    """
    A dialog window for adding, editing, and deleting presets for cameras,
    lenses, and film stocks.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preset Manager")
        self.setMinimumSize(500, 400)

        # Main layout
        main_layout = QVBoxLayout(self)

        # Tab widget for different preset types
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create a tab for each preset type
        self.tabs = {}
        for preset_type in preset_manager.PRESET_TYPES:
            # Create a generic management widget for each type
            # The title is the preset_type with underscores replaced and capitalized
            tab_title = preset_type.replace('_', ' ').title()
            management_widget = PresetManagementWidget(preset_type)
            self.tab_widget.addTab(management_widget, tab_title)
            self.tabs[preset_type] = management_widget

        # Dialog buttons (OK/Cancel)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)


class PresetManagementWidget(QWidget):
    """
    A generic widget that provides a UI for managing a list of presets.
    """
    def __init__(self, preset_type: str, parent=None):
        super().__init__(parent)
        self.preset_type = preset_type
        
        # Load the presets for this type
        self.presets = preset_manager.load_presets(self.preset_type)

        # --- Layout ---
        layout = QHBoxLayout(self)
        
        # Left side: List of presets
        self.preset_list = QListWidget()
        layout.addWidget(self.preset_list)
        
        # Right side: Buttons for actions
        button_layout = QVBoxLayout()
        self.add_button = QPushButton("Add...")
        self.edit_button = QPushButton("Edit...")
        self.delete_button = QPushButton("Delete")
        
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        # --- Populate and Connect ---
        self._populate_list()
        self.add_button.clicked.connect(self._add_preset)
        self.delete_button.clicked.connect(self._delete_preset)
        # Edit functionality can be added later if needed to keep it simple for now

    def _populate_list(self):
        """Clears and refills the list widget with current presets."""
        self.preset_list.clear()
        # Add items in alphabetical order
        for name in sorted(self.presets.keys()):
            self.preset_list.addItem(name)

    def _add_preset(self):
        """Opens a dialog to add a new preset."""
        # For simplicity, we'll use a generic input dialog for now.
        # This will be improved later.
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Add New {self.preset_type.replace('_', ' ').title()}")
        
        form_layout = QFormLayout(dialog)
        
        # Preset name is common to all
        name_edit = QLineEdit()
        form_layout.addRow("Preset Name:", name_edit)
        
        # Add specific fields based on preset type
        fields = {}
        if self.preset_type == 'cameras':
            fields['Make'] = QLineEdit()
            fields['Model'] = QLineEdit()
            form_layout.addRow("Make:", fields['Make'])
            form_layout.addRow("Model:", fields['Model'])
        elif self.preset_type == 'lenses':
            fields['LensModel'] = QLineEdit()
            form_layout.addRow("Lens Model:", fields['LensModel'])
        elif self.preset_type == 'film_stocks':
            fields['ISO'] = QLineEdit()
            form_layout.addRow("ISO:", fields['ISO'])

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form_layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        # If the user clicks OK
        if dialog.exec():
            preset_name = name_edit.text().strip()
            if not preset_name:
                QMessageBox.warning(self, "Input Error", "Preset name cannot be empty.")
                return

            if preset_name in self.presets:
                QMessageBox.warning(self, "Input Error", "A preset with this name already exists.")
                return

            # Save the data
            self.presets[preset_name] = {key: field.text().strip() for key, field in fields.items()}
            preset_manager.save_presets(self.preset_type, self.presets)
            self._populate_list()


    def _delete_preset(self):
        """Deletes the selected preset."""
        selected_item = self.preset_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Error", "Please select a preset to delete.")
            return

        preset_name = selected_item.text()
        reply = QMessageBox.question(self, "Confirm Delete",
                                     f"Are you sure you want to delete the preset '{preset_name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            if preset_name in self.presets:
                del self.presets[preset_name]
                preset_manager.save_presets(self.preset_type, self.presets)
                self._populate_list()
