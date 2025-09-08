from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QSlider,
    QListWidget,
    QListWidgetItem,
    QCheckBox,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QTimer, Qt
from subs import SubtitleEntry
import tempfile
import os


class PlayerUI(QWidget):
    def __init__(
        self,
        mp3_path: str,
        orig_entries: list[SubtitleEntry],
        trans_entries: list[SubtitleEntry],
    ):
        super().__init__()
        self.setWindowTitle("Anki-slicer Player")
        self.setMinimumSize(900, 600)

        self.mp3_path = mp3_path
        self.orig_entries = orig_entries
        self.trans_entries = trans_entries
        self.current_index = 0
        self.flagged = []

        self.auto_pause_mode = False
        self.slider_active = False
        self.pending_index = None
        self.waiting_for_resume = False

        # Player setup
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        # Temp audio conversion
        from pydub import AudioSegment

        self._tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio = AudioSegment.from_file(mp3_path)
        audio = audio.set_frame_rate(44100).set_channels(2)
        audio.export(self._tmp_wav.name, format="wav")
        self.player.setSource(QUrl.fromLocalFile(self._tmp_wav.name))

        # Timer for subtitle sync
        self.timer = QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_subtitles)

        # Slider signals
        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.update_duration)

        self.total_duration = 0

        # Build UI
        self.setup_ui()
        self.timer.start()

    def setup_ui(self):
        layout = QVBoxLayout()

        # Headers
        orig_title = QLabel("Original Subtitle")
        orig_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-top: 10px;"
        )
        trans_title = QLabel("Translation")
        trans_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-top: 10px;"
        )

        # Subtitle displays
        self.orig_label = QLabel("(waiting for audio...)")
        self.orig_label.setWordWrap(True)
        self.orig_label.setStyleSheet(
            "font-size: 14px; padding: 10px; border: 1px solid #ccc;"
        )
        self.trans_label = QLabel("(waiting for audio...)")
        self.trans_label.setWordWrap(True)
        self.trans_label.setStyleSheet(
            "font-size: 14px; padding: 10px; border: 1px solid #ccc;"
        )

        layout.addWidget(orig_title)
        layout.addWidget(self.orig_label)
        layout.addWidget(trans_title)
        layout.addWidget(self.trans_label)

        # Slider + time
        slider_row = QHBoxLayout()
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 0)
        self.pos_slider.sliderMoved.connect(self.seek)
        self.pos_slider.sliderPressed.connect(self.on_slider_pressed)
        self.pos_slider.sliderReleased.connect(self.on_slider_released)

        self.time_label = QLabel("00:00 / 00:00")
        slider_row.addWidget(self.pos_slider, stretch=1)
        slider_row.addWidget(self.time_label)
        layout.addLayout(slider_row)

        # Controls
        controls = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)

        self.prev_btn = QPushButton("Previous")
        self.prev_btn.clicked.connect(self.previous_subtitle)

        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.next_subtitle)

        self.flag_btn = QPushButton("Flag for Anki")
        self.flag_btn.clicked.connect(self.flag_current)

        self.mode_btn = QPushButton("Mode: Continuous")
        self.mode_btn.setCheckable(True)
        self.mode_btn.clicked.connect(self.toggle_mode)

        controls.addWidget(self.play_btn)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.flag_btn)
        controls.addWidget(self.mode_btn)
        layout.addLayout(controls)

        # Progress
        self.progress_label = QLabel(f"Subtitle 1 of {len(self.orig_entries)}")
        layout.addWidget(self.progress_label)

        # === Flagged Segments box ===
        self.flagged_list = QListWidget()
        self.flagged_list.setFixedHeight(180)
        layout.addWidget(QLabel("Flagged Segments"))
        layout.addWidget(self.flagged_list)

        btn_row = QHBoxLayout()
        self.export_btn = QPushButton("Export Selection to Anki")
        self.export_btn.clicked.connect(self.export_to_anki)

        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self.clear_flagged_items)

        btn_row.addWidget(self.export_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self.update_subtitle_display()

    # === Playback + Subtitles ===
    def find_subtitle_index(self, position_sec: float) -> int:
        for i, entry in enumerate(self.orig_entries):
            if entry.start_time <= position_sec <= entry.end_time:
                return i
            if i < len(self.orig_entries) - 1:
                nxt = self.orig_entries[i + 1]
                if entry.end_time < position_sec < nxt.start_time:
                    return i
        return len(self.orig_entries) - 1

    def update_subtitles(self):
        if self.slider_active:
            return

        position_sec = self.player.position() / 1000.0

        if self.auto_pause_mode:
            # Auto-pause mode: check if we've crossed end_time of current subtitle
            if not self.waiting_for_resume:
                current_entry = self.orig_entries[self.current_index]
                if position_sec >= current_entry.end_time:
                    # Hit boundary → pause but keep showing current subtitle
                    self.pending_index = min(
                        self.current_index + 1, len(self.orig_entries) - 1
                    )
                    self.player.pause()
                    self.play_btn.setText("Play")
                    self.waiting_for_resume = True
            # Don't update display in auto-pause mode
            return
        else:
            # Continuous mode: normal position-based mapping
            new_index = self.find_subtitle_index(position_sec)
            if new_index != self.current_index:
                self.current_index = new_index
                self.update_subtitle_display()

    def update_subtitle_display(self):
        orig_entry = self.orig_entries[self.current_index]
        trans_entry = (
            self.trans_entries[self.current_index]
            if self.current_index < len(self.trans_entries)
            else None
        )
        self.orig_label.setText(orig_entry.text)
        self.trans_label.setText(
            trans_entry.text if trans_entry else "(no translation)"
        )
        self.progress_label.setText(
            f"Subtitle {self.current_index + 1} of {len(self.orig_entries)}"
        )

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_btn.setText("Play")
        else:
            # If resuming from auto-pause, advance subtitle now
            if self.waiting_for_resume and self.pending_index is not None:
                self.current_index = self.pending_index
                self.pending_index = None
                self.update_subtitle_display()
                self.waiting_for_resume = False

            self.player.play()
            self.play_btn.setText("Pause")

    # === Flagging ===
    def flag_current(self):
        entry = self.orig_entries[self.current_index]
        if entry not in self.flagged:
            self.flagged.append(entry)
            start_time = self.format_time(int(entry.start_time * 1000))
            orig_snip = " ".join(entry.text.split()[:4]) + (
                "..." if len(entry.text.split()) > 4 else ""
            )
            trans = (
                self.trans_entries[entry.index - 1]
                if entry.index <= len(self.trans_entries)
                else None
            )
            trans_snip = ""
            if trans:
                trans_snip = " / " + " ".join(trans.text.split()[:4])
                if len(trans.text.split()) > 4:
                    trans_snip += "..."
            line = f"{start_time} {orig_snip}{trans_snip}"
            item = QListWidgetItem()
            checkbox = QCheckBox(line)
            checkbox.setChecked(True)
            self.flagged_list.addItem(item)
            self.flagged_list.setItemWidget(item, checkbox)

    def clear_flagged_items(self):
        self.flagged.clear()
        self.flagged_list.clear()

    # === Export ===
    def export_to_anki(self):
        if self.flagged_list.count() == 0:
            QMessageBox.warning(self, "No Flags", "No flagged items to export!")
            return
        from slicer import slice_audio
        from ankiconnect import AnkiConnect

        anki = AnkiConnect()
        anki.ensure_deck()
        out_dir = "anki_clips"
        exported, skipped = 0, 0
        for i in range(self.flagged_list.count()):
            item = self.flagged_list.item(i)
            widget = self.flagged_list.itemWidget(item)
            if (
                isinstance(widget, QCheckBox)
                and widget.isChecked()
                and widget.isEnabled()
            ):
                entry = self.flagged[i]
                trans = (
                    self.trans_entries[entry.index - 1]
                    if entry.index <= len(self.trans_entries)
                    else None
                )
                clip_path = slice_audio(self.mp3_path, entry, out_dir)
                try:
                    anki.add_note(
                        entry.text,
                        trans.text if trans else "(no translation)",
                        clip_path,
                    )
                    exported += 1
                except Exception as e:
                    if "duplicate" in str(e).lower():
                        skipped += 1
                    else:
                        raise
                widget.setEnabled(False)
        QMessageBox.information(
            self,
            "Export Done",
            f"Exported {exported} notes. Skipped {skipped} duplicates.",
        )

    # === Navigation ===
    def previous_subtitle(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.jump_to_current_subtitle()

    def next_subtitle(self):
        if self.current_index < len(self.orig_entries) - 1:
            self.current_index += 1
            self.jump_to_current_subtitle()

    def jump_to_current_subtitle(self):
        entry = self.orig_entries[self.current_index]
        self.player.setPosition(int(entry.start_time * 1000))
        self.update_subtitle_display()
        self.waiting_for_resume = False  # Clear any pending state

    def toggle_mode(self):
        self.auto_pause_mode = self.mode_btn.isChecked()
        self.mode_btn.setText(
            "Mode: Auto‑Pause" if self.auto_pause_mode else "Mode: Continuous"
        )

    # === Slider ===
    def on_slider_pressed(self):
        self.slider_active = True

    def on_slider_released(self):
        self.slider_active = False
        pos = self.pos_slider.value()
        self.player.setPosition(pos)
        self.current_index = self.find_subtitle_index(pos / 1000.0)
        self.update_subtitle_display()
        self.waiting_for_resume = False  # Clear any pending state

    def update_slider(self, pos):
        if not self.pos_slider.isSliderDown():
            self.pos_slider.setValue(pos)
        self.time_label.setText(
            f"{self.format_time(pos)} / {self.format_time(self.total_duration)}"
        )

    def update_duration(self, dur):
        self.total_duration = dur
        self.pos_slider.setRange(0, dur)

    def seek(self, pos):
        self.player.setPosition(pos)

    @staticmethod
    def format_time(ms: int) -> str:
        seconds = ms // 1000
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02}"

    # === Cleanup ===
    def closeEvent(self, event):  # type: ignore[override]
        try:
            self.player.stop()
            os.unlink(self._tmp_wav.name)
        except Exception as e:
            print(f"[DEBUG] Cleanup failed: {e}")
        event.accept()
