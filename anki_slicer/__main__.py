from .player import PlayerUI


def main():
    from PyQt6.QtWidgets import QApplication
    from .ui import FileSelectorUI

    app = QApplication([])
    window = FileSelectorUI()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
