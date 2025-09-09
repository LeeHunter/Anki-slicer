import sys
from PyQt6.QtWidgets import QApplication, QMessageBox
from anki_slicer.ui import FileSelectorUI
from anki_slicer.subs import SRTParser
from anki_slicer.player import PlayerUI

# We'll hold onto the player window in a global variable to keep it alive
_player_window = None


def on_start(mp3_path: str, orig_srt: str, trans_srt: str):
    global _player_window

    orig_entries = SRTParser.parse_srt_file(orig_srt)
    trans_entries = SRTParser.parse_srt_file(trans_srt)

    is_valid, message = SRTParser.validate_alignment(orig_entries, trans_entries)
    if not is_valid:
        QMessageBox.critical(None, "Validation Failed", message)
        return

    # Create and keep reference so Python doesn't garbage-collect it
    _player_window = PlayerUI(mp3_path, orig_entries, trans_entries)
    _player_window.show()
    _player_window.raise_()
    _player_window.activateWindow()


def main():
    app = QApplication(sys.argv)
    window = FileSelectorUI()
    window.start_requested.connect(on_start)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
