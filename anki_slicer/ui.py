from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QMessageBox,
)
from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
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
    # Emitted when a new Player window is launched
    playerLaunched = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr("Anki-Slicer – Select Files"))
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
        self.audio_label = QLabel(self.tr("No audio file selected"))
        self.orig_label = QLabel(self.tr("No original subs selected"))
        self.trans_label = QLabel(self.tr("No translation subs selected"))

        # Buttons
        self.audio_btn = QPushButton(self.tr("Select Audio file"))
        self.orig_btn = QPushButton(self.tr("Select Original Subtitles (.srt)"))
        self.trans_btn = QPushButton(self.tr("Select Translation (.srt or .txt)"))
        self.start_btn = QPushButton(self.tr("Start"))

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

        # In debug runs, prefill last-used files to speed iteration
        try:
            import os as _os
            if _os.getenv("ANKI_SLICER_DEBUG"):
                self._prefill_last_paths_debug()
        except Exception:
            pass

    def _get_last_dir(self) -> str:
        return self.settings.value("last_directory", "")

    def _set_last_dir(self, filepath: str):
        if filepath:
            self.settings.setValue("last_directory", str(filepath.rsplit("/", 1)[0]))

    def _prefill_last_paths_debug(self):
        """Prefill the last selected files (if they still exist) when in debug mode.
        This only sets the fields; it does not auto-start the player.
        """
        import os
        a = self.settings.value("last_audio_path", "") or ""
        o = self.settings.value("last_orig_srt", "") or ""
        t = self.settings.value("last_trans_srt", "") or ""

        if a and os.path.exists(a):
            self.audio_path = a
            self.audio_label.setText(a)
            self._set_last_dir(a)
        if o and os.path.exists(o):
            self.orig_srt = o
            self.orig_label.setText(o)
            self._set_last_dir(o)
        if t and os.path.exists(t):
            self.trans_srt = t
            self.trans_label.setText(t)
            self._set_last_dir(t)

    # ---------- File Selectors ----------

    def select_audio(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Audio File"),
            last_dir,
            self.tr("Audio Files (*.mp3 *.wav *.m4a *.flac *.ogg *.aac);;All Files (*)"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.audio_path = path
            self.audio_label.setText(path)
            self._set_last_dir(path)
            self.settings.setValue("last_audio_path", path)

    def select_orig(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Original Subtitles"),
            last_dir,
            self.tr("Subtitle Files (*.srt);;All Files (*)"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.orig_srt = path
            self.orig_label.setText(path)
            self._set_last_dir(path)
            self.settings.setValue("last_orig_srt", path)

    def select_trans(self):
        last_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Translation Subtitles"),
            last_dir,
            self.tr("Subtitle/Text Files (*.srt *.txt);;All Files (*)"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.trans_srt = path
            self.trans_label.setText(path)
            self._set_last_dir(path)
            self.settings.setValue("last_trans_srt", path)

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
            raise ValueError(self.tr("Original subtitles must be .srt with timing."))
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

        raise ValueError(self.tr("Unsupported translation format: .{ext}").format(ext=ext))

    # ---------- Start Player ----------

    def start_player(self):
        if not (self.audio_path and self.orig_srt and self.trans_srt):
            box = QMessageBox(self)
            try:
                icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
                if icon_path.exists():
                    box.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass
            box.setIcon(QMessageBox.Icon.Warning)
            try:
                # Set in-dialog pixmap AFTER setIcon so it takes effect
                pm = QPixmap(str(icon_path))
                if not pm.isNull():
                    box.setIconPixmap(pm.scaled(64, 64))
            except Exception:
                pass
            box.setWindowTitle(self.tr("Missing Files"))
            box.setText(self.tr("Please select audio, original SRT, and translation file."))
            box.exec()
            return

        try:
            orig_entries = self._load_original_entries(self.orig_srt)
        except Exception as e:
            box = QMessageBox(self)
            try:
                icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
                if icon_path.exists():
                    box.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass
            box.setIcon(QMessageBox.Icon.Critical)
            try:
                pm = QPixmap(str(icon_path))
                if not pm.isNull():
                    box.setIconPixmap(pm.scaled(64, 64))
            except Exception:
                pass
            box.setWindowTitle(self.tr("Subtitle Error"))
            box.setText(
                self.tr("Failed to load original subtitles:\n{error}").format(error=e)
            )
            box.exec()
            return

        try:
            trans_entries = self._load_translation_entries(self.trans_srt, orig_entries)
        except Exception as e:
            box = QMessageBox(self)
            try:
                icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
                if icon_path.exists():
                    box.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass
            box.setIcon(QMessageBox.Icon.Critical)
            try:
                pm = QPixmap(str(icon_path))
                if not pm.isNull():
                    box.setIconPixmap(pm.scaled(64, 64))
            except Exception:
                pass
            box.setWindowTitle(self.tr("Subtitle Error"))
            box.setText(
                self.tr("Failed to load translation subtitles:\n{error}").format(error=e)
            )
            box.exec()
            return

        # Helpful info if counts mismatch
        if len(trans_entries) != len(orig_entries):
            box = QMessageBox(self)
            try:
                icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
                if icon_path.exists():
                    box.setWindowIcon(QIcon(str(icon_path)))
            except Exception:
                pass
            box.setIcon(QMessageBox.Icon.Information)
            try:
                pm = QPixmap(str(icon_path))
                if not pm.isNull():
                    box.setIconPixmap(pm.scaled(64, 64))
            except Exception:
                pass
            box.setWindowTitle(self.tr("Note"))
            box.setText(
                self.tr(
                    "Translation entries: {translation_count} vs Original entries: {original_count}.\nThey have been truncated to the shorter length."
                ).format(
                    translation_count=len(trans_entries), original_count=len(orig_entries)
                )
            )
            box.exec()

        allow_streaming = True  # Future: allow switching between local/YouTube modes
        self.player = PlayerUI(
            self.audio_path,
            orig_entries,
            trans_entries,
            allow_streaming=allow_streaming,
        )
        self.player.show()
        try:
            # Notify listeners (e.g., an existing Player) to close
            self.playerLaunched.emit()
        except Exception:
            pass
        self.close()
