from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QLineEdit,
    QHBoxLayout,
    QMessageBox,
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import Union
import os
from config import load_config, save_config


class FileSelectorUI(QWidget):
    # Emitted when all three files are selected and user clicks Start
    start_requested = pyqtSignal(str, str, str)  # mp3_path, orig_srt, trans_srt

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anki-slicer")
        self.setMinimumSize(700, 350)

        self.mp3_path_edit = QLineEdit()
        self.orig_srt_edit = QLineEdit()
        self.trans_srt_edit = QLineEdit()

        # Make path fields read-only; users pick via Browse
        for e in (self.mp3_path_edit, self.orig_srt_edit, self.trans_srt_edit):
            e.setReadOnly(True)

        self.start_button = QPushButton("Start")
        self.start_button.setEnabled(False)  # enabled only when all files chosen
        self.start_button.setToolTip(
            "Please select an MP3/M4A/WAV file and two SRT files to enable Start"
        )
        self.start_button.clicked.connect(self.on_start_clicked)

        layout = QVBoxLayout()
        layout.setSpacing(12)

        layout.addWidget(QLabel("Choose your files:"))
        layout.addLayout(self._row("MP3 file", self.mp3_path_edit, self._select_mp3))
        layout.addLayout(
            self._row(
                "Original SRT (transcript)", self.orig_srt_edit, self._select_orig_srt
            )
        )
        layout.addLayout(
            self._row("Translation SRT", self.trans_srt_edit, self._select_trans_srt)
        )

        layout.addStretch(1)
        layout.addWidget(self.start_button, alignment=Qt.AlignmentFlag.AlignRight)

        self.setLayout(layout)

    def _row(self, label_text: str, line_edit: QLineEdit, onclick):
        row = QHBoxLayout()
        label = QLabel(label_text + ":")
        label.setMinimumWidth(190)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(onclick)

        row.addWidget(label)
        row.addWidget(line_edit, stretch=1)
        row.addWidget(browse_btn)
        return row

    def _select_mp3(self):
        options = QFileDialog.Option.DontUseNativeDialog
        config = load_config()
        last_dir = config.get("last_dir", "")

        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select MP3",
            last_dir,
            "Audio Files (*.mp3 *.m4a *.wav)",
            options=options,
        )
        if file:
            self.mp3_path_edit.setText(file)
            config["last_dir"] = os.path.dirname(file)
            save_config(config)
            self._update_start_enabled()

    def _select_orig_srt(self):
        options = QFileDialog.Option.DontUseNativeDialog
        config = load_config()
        last_dir = config.get("last_dir", "")

        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Original SRT",
            last_dir,
            "SubRip Files (*.srt)",
            options=options,
        )
        if file:
            self.orig_srt_edit.setText(file)
            config["last_dir"] = os.path.dirname(file)
            save_config(config)
            self._update_start_enabled()

    def _select_trans_srt(self):
        options = QFileDialog.Option.DontUseNativeDialog
        config = load_config()
        last_dir = config.get("last_dir", "")

        file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Translation SRT",
            last_dir,
            "SubRip Files (*.srt)",
            options=options,
        )
        if file:
            self.trans_srt_edit.setText(file)
            config["last_dir"] = os.path.dirname(file)
            save_config(config)
            self._update_start_enabled()

    def _update_start_enabled(self):
        ok = all(
            (
                self._is_file(self.mp3_path_edit.text(), (".mp3", ".m4a", ".wav")),
                self._is_file(self.orig_srt_edit.text(), ".srt"),
                self._is_file(self.trans_srt_edit.text(), ".srt"),
            )
        )
        self.start_button.setEnabled(ok)

        if ok:
            self.start_button.setToolTip("Click to start Anki-slicer")
        else:
            self.start_button.setToolTip(
                "Please select an MP3/M4A/WAV file and two SRT files to enable Start"
            )

    @staticmethod
    def _is_file(path: str, exts: Union[str, tuple[str, ...]]) -> bool:
        """
        Check file exists and has extension in exts (string or tuple of allowed endings).
        """
        return bool(path) and os.path.isfile(path) and path.lower().endswith(exts)

    def on_start_clicked(self):
        mp3 = self.mp3_path_edit.text().strip()
        orig = self.orig_srt_edit.text().strip()
        trans = self.trans_srt_edit.text().strip()

        # Final sanity checks
        if (
            not self._is_file(mp3, (".mp3", ".m4a", ".wav"))
            or not self._is_file(orig, ".srt")
            or not self._is_file(trans, ".srt")
        ):
            QMessageBox.warning(
                self,
                "Invalid selection",
                "Please select a valid audio file and two SRT files.",
            )
            return

        self.start_requested.emit(mp3, orig, trans)
