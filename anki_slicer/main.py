from PyQt6.QtWidgets import QApplication
from .ui import FileSelectorUI


def main():
    app = QApplication([])
    window = FileSelectorUI()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
