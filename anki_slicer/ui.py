from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon
from pathlib import Path
from .player import PlayerUI
from .subs import SRTParser, SubtitleEntry
import os
import re
import logging

logger = logging.getLogger(__name__)


TIMESTAMP_RE = re.compile(
    r"^\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
)


class FileSelectorUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anki‑Slicer – Select Files")
        self.setMinimumSize(400, 200)

        # Set window icon if present
        try:
            icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        self.audio_path = None
        self.orig_srt = None
        self.trans_srt = None

        self.settings = QSettings("AnkiSlicer", "FileSelectorUI")

        layout = QVBoxLayout(self)

        # Labels
        self.audio_label = QLabel("No audio file selected")
        self.orig_label = QLabel("No original subs selected")
        self.trans_label = QLabel("No translation subs selected")

        # Buttons
        self.audio_btn = QPushButton("Select Audio file")
        self.orig_btn = QPushButton("Select Original Subtitles (.srt)")
        self.trans_btn = QPushButton("Select Translation (.srt or .txt)")
        self.start_btn = QPushButton("Start")

        layout.addWidget(self.audio_label)
        layout.addWidget(self.audio_btn)
        layout.addWidget(self.orig_label)
        layout.addWidget(self.orig_btn)
        layout.addWidget(self.trans_label)
        layout.addWidget(self.trans_btn)
        layout.addStretch(1)
        layout.addWidget(self.start_btn)

        # Connect
        self.audio_btn.clicked.connect(self.select_audio)
        self.orig_btn.clicked.connect(self.select_orig)
        self.trans_btn.clicked.connect(self.select_trans)
        self.start_btn.clicked.connect(self.start_player)

        self.player = None

    def _get_last_dir(self) -> str:
        return self.settings.value("last_directory", "")

    def _set_last_dir(self, filepath: str):
        if filepath:
            self.settings.setValue("last_directory", str(filepath.rsplit("/", 1)[0]))

    # ---------- File Selectors ----------

    def select_audio(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            last_dir,
            "Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.audio_path = path
            self.audio_label.setText(path)
            self._set_last_dir(path)

    def select_orig(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Original Subtitles",
            last_dir,
            "Subtitle Files (*.srt);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.orig_srt = path
            self.orig_label.setText(path)
            self._set_last_dir(path)

    def select_trans(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Translation Subtitles",
            last_dir,
            "Subtitle/Text Files (*.srt *.txt);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.trans_srt = path
            self.trans_label.setText(path)
            self._set_last_dir(path)

    # ---------- Subtitle Loading ----------

    @staticmethod
    def _ext(path: str) -> str:
        return os.path.splitext(path)[1].lower().lstrip(".")

    @staticmethod
    def _read_text_lines(path: str) -> list[str]:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # Do NOT drop blank lines here; we preserve them so we can parse properly.
        return [line.rstrip("\n") for line in content.splitlines()]

    def _parse_txt_blocks(self, path: str) -> list[str]:
        """
        Parse .txt translations as blocks per subtitle.

        - If the file contains SRT-like timestamp lines, then each block is everything
          from one timestamp line up to (but not including) the next timestamp line.
          We ignore any preceding numeric index lines.
          This allows arbitrary blank lines inside a translation block.

        - If the file has NO timestamp lines, we treat blank lines as block separators.
        """
        lines = self._read_text_lines(path)

        # Find indices of all timestamp lines
        ts_indices = [i for i, ln in enumerate(lines) if TIMESTAMP_RE.match(ln)]

        blocks: list[str] = []

        if ts_indices:
            # Timestamped .txt mode
            num_ts = len(ts_indices)
            for idx in range(num_ts):
                start_ts_line = ts_indices[idx]
                end_ts_line = ts_indices[idx + 1] if idx + 1 < num_ts else len(lines)

                # Collect lines after the timestamp until the next timestamp
                i = start_ts_line + 1

                # Skip a numeric index line (if present) immediately after timestamp
                if i < end_ts_line and lines[i].strip().isdigit():
                    i += 1

                content_lines = lines[i:end_ts_line]

                # Drop leading/trailing blank lines within the segment
                # but keep internal blank lines (for Markdown readability).
                # Trim leading blanks
                while content_lines and not content_lines[0].strip():
                    content_lines.pop(0)
                # Trim trailing blanks
                while content_lines and not content_lines[-1].strip():
                    content_lines.pop()

                blocks.append("\n".join(content_lines).strip())

        else:
            # Non-timestamped .txt mode: split by blank lines
            buf = []
            for line in lines:
                if not line.strip():  # blank line => end of block
                    if buf:
                        blocks.append("\n".join(buf).strip())
                        buf = []
                    continue
                # ignore pure index and timestamp-looking lines just in case
                if line.strip().isdigit():
                    continue
                if "-->" in line:
                    continue
                buf.append(line)
            if buf:
                blocks.append("\n".join(buf).strip())

        return blocks

    def _load_original_entries(self, path: str):
        if self._ext(path) != "srt":
            raise ValueError("Original subtitles must be .srt with timing.")
        return SRTParser.parse_srt_file(path)

    def _load_translation_entries(self, path: str, orig_entries):
        ext = self._ext(path)
        logger.debug("Loading translation file: %s, detected extension: %s", path, ext)
        if ext == "srt":
            return SRTParser.parse_srt_file(path)
        if ext == "txt":
            blocks = self._parse_txt_blocks(path)

            # Map blocks to original timings in order
            n = min(len(blocks), len(orig_entries))
            entries = []
            for i in range(n):
                o = orig_entries[i]
                entries.append(
                    SubtitleEntry(
                        index=i + 1,
                        start_time=o.start_time,
                        end_time=o.end_time,
                        text=blocks[i],
                    )
                )
            return entries

        raise ValueError(f"Unsupported translation format: .{ext}")

    # ---------- Start Player ----------

    def start_player(self):
        if not (self.audio_path and self.orig_srt and self.trans_srt):
            QMessageBox.warning(
                self,
                "Missing Files",
                "Please select audio, original SRT, and translation file.",
            )
            return

        try:
            orig_entries = self._load_original_entries(self.orig_srt)
        except Exception as e:
            QMessageBox.critical(
                self, "Subtitle Error", f"Failed to load original subtitles:\n{e}"
            )
            return

        try:
            trans_entries = self._load_translation_entries(self.trans_srt, orig_entries)
        except Exception as e:
            QMessageBox.critical(
                self, "Subtitle Error", f"Failed to load translation subtitles:\n{e}"
            )
            return

        # Helpful info if counts mismatch
        if len(trans_entries) != len(orig_entries):
            QMessageBox.information(
                self,
                "Note",
                f"Translation entries: {len(trans_entries)} vs Original entries: {len(orig_entries)}.\n"
                "They have been truncated to the shorter length.",
            )

        self.player = PlayerUI(self.audio_path, orig_entries, trans_entries)
        self.player.show()
        self.close()
