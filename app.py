import sys
from PyQt6.QtWidgets import QApplication, QMessageBox

# Import the main window class from our ui folder
from ui.main_window import MainWindow
# We also import the exiftool manager to check for it on startup
import exiftool_manager

def main():
    """
    Main function to initialize and run the Film Tagger application.
    """
    # 1. Check for ExifTool dependency first.
    #    This is a critical check from your original project and is good practice.
    if not exiftool_manager.check_or_install_exiftool():
        # A basic QMessageBox can be used before the main app is running.
        QMessageBox.critical(
            None,
            "Critical Error",
            "Could not install or find ExifTool. The application cannot continue.\n\n"
            "Please check your internet connection or place 'exiftool.exe' "
            "in the 'resources' folder."
        )
        sys.exit(1) # Exit the application if the dependency is missing.

    # 2. Create the application instance.
    app = QApplication(sys.argv)

    # 3. Create an instance of our main window.
    window = MainWindow()

    # 4. Show the window.
    window.show()

    # 5. Start the application's event loop.
    sys.exit(app.exec())


# This ensures the main() function is called only when the script is executed directly.
if __name__ == '__main__':
    main()
