# Entry point for Anki-slicer

# main.py
import sys
from PyQt6.QtWidgets import QApplication
from ui import FileSelectorUI

def main():
    app = QApplication(sys.argv)
    window = FileSelectorUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
