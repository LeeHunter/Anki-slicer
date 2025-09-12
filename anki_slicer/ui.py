from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings
from .player import PlayerUI
from .subs import SRTParser


class FileSelectorUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anki‑Slicer – Select Files")
        self.setMinimumSize(400, 200)

        # State for selected paths
        self.audio_path = None
        self.orig_srt = None
        self.trans_srt = None

        # Settings object to remember last directory
        self.settings = QSettings("AnkiSlicer", "FileSelectorUI")

        layout = QVBoxLayout(self)

        # Labels to show chosen files
        self.audio_label = QLabel("No audio file selected")
        self.orig_label = QLabel("No original subs selected")
        self.trans_label = QLabel("No translation subs selected")

        # Browse buttons
        self.audio_btn = QPushButton("Select Audio file")
        self.orig_btn = QPushButton("Select Original SRT")
        self.trans_btn = QPushButton("Select Translation SRT")

        # Start button
        self.start_btn = QPushButton("Start")

        # Assemble layout
        layout.addWidget(self.audio_label)
        layout.addWidget(self.audio_btn)
        layout.addWidget(self.orig_label)
        layout.addWidget(self.orig_btn)
        layout.addWidget(self.trans_label)
        layout.addWidget(self.trans_btn)
        layout.addStretch(1)
        layout.addWidget(self.start_btn)

        # Connect actions
        self.audio_btn.clicked.connect(self.select_audio)
        self.orig_btn.clicked.connect(self.select_orig)
        self.trans_btn.clicked.connect(self.select_trans)
        self.start_btn.clicked.connect(self.start_player)

        # Reference for player window
        self.player = None

    def _get_last_dir(self) -> str:
        """Fetch last-used directory from settings (default blank)."""
        return self.settings.value("last_directory", "")

    def _set_last_dir(self, filepath: str):
        """Save the directory portion of the given filepath."""
        if filepath:
            self.settings.setValue("last_directory", str(filepath.rsplit("/", 1)[0]))

    def select_audio(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            last_dir,
            "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac);;All Files (*)",
        )
        if path:
            self.audio_path = path
            self.audio_label.setText(path)
            self._set_last_dir(path)

    def select_orig(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Original Subtitles", last_dir, "Subtitle Files (*.srt)"
        )
        if path:
            self.orig_srt = path
            self.orig_label.setText(path)
            self._set_last_dir(path)

    def select_trans(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Translation Subtitles", last_dir, "Subtitle Files (*.srt)"
        )
        if path:
            self.trans_srt = path
            self.trans_label.setText(path)
            self._set_last_dir(path)

    def start_player(self):
        if not (self.audio_path and self.orig_srt and self.trans_srt):
            QMessageBox.warning(
                self, "Missing Files", "Please select all three files before starting."
            )
            return

        # Load subtitles using your actual parser
        try:
            orig_entries = SRTParser.parse_srt_file(self.orig_srt)
            trans_entries = SRTParser.parse_srt_file(self.trans_srt)
        except Exception as e:
            QMessageBox.critical(
                self, "Subtitle Error", f"Failed to parse subtitle files:\n{e}"
            )
            return

        # Optional: validate alignment
        is_valid, message = SRTParser.validate_alignment(orig_entries, trans_entries)
        if not is_valid:
            reply = QMessageBox.question(
                self,
                "Alignment Warning",
                f"{message}\n\nDo you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Launch PlayerUI (store ref so it doesn't get garbage collected)
        self.player = PlayerUI(self.audio_path, orig_entries, trans_entries)
        self.player.show()

        # Optionally: close the file selector window
        self.close()
