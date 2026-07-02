import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from main_window import MainWindow


def main():
    """
    Main function to initialize and run the Film Tagger application.
    """
    app = QApplication(sys.argv)

    # ExifTool availability is not treated as fatal: the app launches either
    # way, and MainWindow._refresh_exiftool_status() (called from its
    # __init__) reflects the real status in the status bar and disables
    # "Apply Changes" specifically if nothing usable was found. Loading and
    # browsing a roll still works fine without ExifTool.
    window = MainWindow()
    if not window.exiftool_available:
        QMessageBox.warning(
            window, "ExifTool Not Found",
            "ExifTool could not be found, so writing metadata is disabled for this "
            "session.\n\nLoading and reviewing a roll will still work normally. To "
            "enable tagging, install ExifTool and either add it to your system PATH, "
            "or point the app at it directly via Settings > Set ExifTool Path..."
        )

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
