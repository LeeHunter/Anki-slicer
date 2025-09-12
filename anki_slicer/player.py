from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QSlider,
    QLineEdit,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
    QSizePolicy,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QTimer, Qt, QSettings, QEvent
from PyQt6.QtGui import QKeySequence, QAction, QFont
from anki_slicer.subs import SubtitleEntry
from anki_slicer.segment_adjuster import SegmentAdjusterWidget
from anki_slicer.ankiconnect import AnkiConnect
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
        self.setMinimumSize(950, 650)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.mp3_path = mp3_path
        self.orig_entries = orig_entries
        self.trans_entries = trans_entries
        self.current_index = 0

        # State
        self.auto_pause_mode = False
        self.slider_active = False
        self.pending_index = None
        self.waiting_for_resume = False
        self.card_created_for_current_segment = False
        self.is_adjusted_preview = False  # track preview vs normal pause

        # More wiggle room around each subtitle
        self.MARGIN_SEC = 1.0

        # For search
        self.search_matches: list[int] = []
        self.search_index = 0

        # Player setup
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.player.setAudioOutput(self.audio_output)

        # Convert to wav for stable playback
        from pydub import AudioSegment

        self._tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio = AudioSegment.from_file(mp3_path)
        audio = audio.set_frame_rate(44100).set_channels(2)
        audio.export(self._tmp_wav.name, format="wav")
        self.player.setSource(QUrl.fromLocalFile(self._tmp_wav.name))

        # Timers
        self.timer = QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_subtitles)

        # Single-shot timer for stopping at end of range
        self.auto_pause_timer = QTimer(self)
        self.auto_pause_timer.setSingleShot(True)
        self.auto_pause_timer.timeout.connect(self._auto_pause_hit)

        # Slider signals
        self.player.positionChanged.connect(self.update_slider)
        self.player.durationChanged.connect(self.update_duration)
        self.total_duration = 0

        # Settings
        self.settings = QSettings("AnkiSlicer", "PlayerUI")

        # Build UI
        self.setup_ui()
        self.timer.start()

        # Keyboard shortcut for Play/Pause (space bar)
        self.play_action = QAction("Play/Pause", self)
        self.play_action.setShortcut(QKeySequence("Space"))
        self.play_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.play_action.triggered.connect(self.toggle_play)
        self.addAction(self.play_action)

        # Initialize waveform with the first subtitle segment (with margin)
        if self.orig_entries:
            entry0 = self.orig_entries[0]
            raw_start = max(0.0, entry0.start_time - self.MARGIN_SEC)
            raw_end = entry0.end_time + self.MARGIN_SEC
            self.adjuster.set_bounds_and_selection(
                raw_start, raw_end, entry0.start_time, entry0.end_time
            )

        # Waveform click-to-preview
        self.adjuster.installEventFilter(self)

    def save_anki_deck_name(self, *_):
        # Accepts the signal’s str arg (or none) without complaining
        self.settings.setValue("anki_deck_name", self.anki_deck_input.text().strip())

    def setup_ui(self):
        layout = QVBoxLayout()

        # === Search controls ===
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search subtitles...")
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.run_search)
        self.next_match_btn = QPushButton("Next Match")
        self.next_match_btn.clicked.connect(self.next_match)
        search_row.addWidget(self.search_input)
        search_row.addWidget(self.search_btn)
        search_row.addWidget(self.next_match_btn)
        layout.addLayout(search_row)

        # === Search Scope ===
        scope_group_box = QGroupBox("Search Scope")
        scope_layout = QHBoxLayout()
        self.scope_group = QButtonGroup(self)
        self.radio_orig = QRadioButton("Original")
        self.radio_trans = QRadioButton("Translation")
        self.radio_both = QRadioButton("Both")
        self.radio_both.setChecked(True)
        for rb in (self.radio_orig, self.radio_trans, self.radio_both):
            self.scope_group.addButton(rb)
            scope_layout.addWidget(rb)
        scope_group_box.setLayout(scope_layout)
        layout.addWidget(scope_group_box)

        # === Subtitle displays ===
        base_style = "font-size: 16px; padding: 10px; border: 1px solid #ccc;"

        orig_title = QLabel("Original")
        orig_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-top: 10px;"
        )
        trans_title = QLabel("Translation")
        trans_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; margin-top: 10px;"
        )

        self.orig_label = QLabel("(waiting for audio...)")
        self.orig_label.setWordWrap(False)  # single line
        self.orig_label.setStyleSheet(base_style)
        self.orig_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self.trans_label = QLabel("(waiting for audio...)")
        self.trans_label.setWordWrap(True)
        self.trans_label.setStyleSheet(base_style)
        self.trans_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        # Fix heights: Original ~1 line; Translation ~6 lines
        fm = self.orig_label.fontMetrics()
        line_h = fm.lineSpacing()
        self.orig_label.setFixedHeight(int(line_h + 20))  # 1 line + padding
        self.trans_label.setFixedHeight(int(line_h * 6 + 20))  # ~6 lines + padding

        layout.addWidget(orig_title)
        layout.addWidget(self.orig_label)
        layout.addWidget(trans_title)
        layout.addWidget(self.trans_label)

        # === Slider + time ===
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

        # === Playback controls ===
        # Swap positions: Back on the left, Forward on the right.
        controls = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(self.back_to_previous)
        self.forward_btn = QPushButton("Forward")
        self.forward_btn.clicked.connect(self.forward_to_next)
        self.mode_btn = QPushButton("Mode: Continuous")
        self.mode_btn.setCheckable(True)
        self.mode_btn.clicked.connect(self.toggle_mode)
        controls.addWidget(self.back_btn)
        controls.addWidget(self.forward_btn)
        controls.addWidget(self.mode_btn)
        layout.addLayout(controls)

        # === Progress ===
        self.progress_label = QLabel(f"Subtitle 1 of {len(self.orig_entries)}")
        layout.addWidget(self.progress_label)

        # === Waveform widget ===
        self.adjuster = SegmentAdjusterWidget(self.mp3_path, self.player)
        self.adjuster.setFixedHeight(160)
        layout.addWidget(self.adjuster)

        # === Segment adjustment controls ===
        segment_controls_row = QHBoxLayout()
        segment_controls_row.setSpacing(10)

        start_label = QLabel("Adjust Start:")
        start_label.setStyleSheet("font-weight: bold;")
        self.start_minus = QPushButton("−")
        self.start_plus = QPushButton("+")
        for btn in (self.start_minus, self.start_plus):
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        segment_controls_row.addWidget(start_label)
        segment_controls_row.addWidget(self.start_minus)
        segment_controls_row.addWidget(self.start_plus)

        segment_controls_row.addStretch(1)

        end_label = QLabel("Adjust End:")
        end_label.setStyleSheet("font-weight: bold;")
        self.end_minus = QPushButton("−")
        self.end_plus = QPushButton("+")
        for btn in (self.end_minus, self.end_plus):
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        segment_controls_row.addWidget(end_label)
        segment_controls_row.addWidget(self.end_minus)
        segment_controls_row.addWidget(self.end_plus)

        layout.addLayout(segment_controls_row)

        # Connect nudges
        self.start_minus.clicked.connect(lambda: self.nudge_segment("start", -0.05))
        self.start_plus.clicked.connect(lambda: self.nudge_segment("start", +0.05))
        self.end_minus.clicked.connect(lambda: self.nudge_segment("end", -0.05))
        self.end_plus.clicked.connect(lambda: self.nudge_segment("end", +0.05))

        # === Anki controls ===
        anki_controls_row = QHBoxLayout()
        self.anki_deck_label = QLabel("Anki Deck:")
        self.anki_deck_input = QLineEdit()
        self.anki_deck_input.setText(
            self.settings.value("anki_deck_name", "AnkiSlicer")
        )
        self.anki_deck_input.textChanged.connect(self.save_anki_deck_name)
        self.create_card_btn = QPushButton("Create Anki Card")
        self.set_create_button_enabled(False)
        anki_controls_row.addWidget(self.anki_deck_label)
        anki_controls_row.addWidget(self.anki_deck_input, stretch=1)
        anki_controls_row.addStretch(1)
        anki_controls_row.addWidget(self.create_card_btn)
        layout.addLayout(anki_controls_row)

        self.create_card_btn.clicked.connect(self.create_anki_card)

        self.setLayout(layout)
        self.update_subtitle_display()

    # Styled enable/disable for the Create button
    def set_create_button_enabled(self, enabled: bool):
        self.create_card_btn.setEnabled(enabled)
        if enabled:
            self.create_card_btn.setStyleSheet(
                "background-color: #2ecc71; color: white; font-weight: bold;"
            )
        else:
            self.create_card_btn.setStyleSheet(
                "background-color: #cccccc; color: #666666;"
            )

    # === Helper methods for audio export ===
    def _sanitize_filename(self, name: str) -> str:
        safe = "".join(
            ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in name
        )
        safe = "_".join(safe.split())
        return safe[:80] if safe else "clip"

    def _export_clip_fallback(
        self, out_dir: str, start_sec: float, end_sec: float, index_for_name: int
    ) -> str:
        from pydub import AudioSegment

        os.makedirs(out_dir, exist_ok=True)
        audio = AudioSegment.from_file(self.mp3_path)
        s = max(0, int(start_sec * 1000))
        e = max(s + 10, int(end_sec * 1000))
        base = f"{index_for_name:04d}_{int(start_sec*1000)}-{int(end_sec*1000)}"
        base = self._sanitize_filename(base)
        out_path = os.path.abspath(os.path.join(out_dir, base + ".mp3"))
        audio[s:e].export(out_path, format="mp3")
        return out_path

    # === Segment Adjustment Helper ===
    def nudge_segment(self, which: str, delta: float):
        start, end = self.adjuster.get_adjusted_segment()
        raw_start, raw_end = self.adjuster.raw_start, self.adjuster.raw_end

        if which == "start":
            if delta < 0:
                new_start = min(end - 0.1, start + abs(delta))
            else:
                new_start = max(raw_start, start - abs(delta))
            self.adjuster.adj_start = new_start

        elif which == "end":
            if delta < 0:
                new_end = max(start + 0.1, end - abs(delta))
            else:
                new_end = min(raw_end, end + abs(delta))
            self.adjuster.adj_end = new_end

        self.adjuster.adj_start = max(
            raw_start, min(self.adjuster.adj_start, self.adjuster.adj_end - 0.05)
        )
        self.adjuster.adj_end = min(
            raw_end, max(self.adjuster.adj_end, self.adjuster.adj_start + 0.05)
        )
        self.adjuster.update()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

        self.play_adjusted_segment()

    def play_adjusted_segment(self):
        start, end = self.adjuster.get_adjusted_segment()
        self.auto_pause_timer.stop()
        self.is_adjusted_preview = True

        self.player.setPosition(int(start * 1000))
        self.player.play()

        duration_ms = max(0, int((end - start) * 1000))
        self.auto_pause_timer.start(duration_ms)

    # === Playback + Subtitles ===
    def find_subtitle_index(self, position_sec: float) -> int:
        if not self.orig_entries:
            return 0
        # Before first subtitle starts -> index 0
        if position_sec <= self.orig_entries[0].start_time:
            return 0
        # After last subtitle ends -> last index
        if position_sec >= self.orig_entries[-1].end_time:
            return len(self.orig_entries) - 1

        for i, entry in enumerate(self.orig_entries):
            if entry.start_time <= position_sec <= entry.end_time:
                return i
            if i < len(self.orig_entries) - 1:
                nxt = self.orig_entries[i + 1]
                if entry.end_time < position_sec < nxt.start_time:
                    return i
        return 0  # safe fallback

    def update_subtitles(self):
        # Don't change subtitle index during adjusted previews
        if self.slider_active or self.is_adjusted_preview:
            return
        position_sec = self.player.position() / 1000.0
        new_index = self.find_subtitle_index(position_sec)
        if new_index != self.current_index:
            self.current_index = new_index
            self.update_subtitle_display()

    def show_current_segment_in_adjuster(self):
        entry = self.orig_entries[self.current_index]
        total_sec = max(0.0, (self.total_duration or 0) / 1000.0)

        margin = float(self.MARGIN_SEC)
        raw_start = max(0.0, entry.start_time - margin)
        raw_end = entry.end_time + margin
        if total_sec > 0:
            raw_end = min(raw_end, total_sec)

        self.adjuster.set_bounds_and_selection(
            raw_start, raw_end, entry.start_time, entry.end_time
        )

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

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
        self.show_current_segment_in_adjuster()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    # Spacebar play/pause
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.auto_pause_timer.stop()
            self.player.pause()
            self.show_current_segment_in_adjuster()
            return

        # Resume or start at current subtitle start
        if self.waiting_for_resume and self.pending_index is not None:
            self.current_index = self.pending_index
            self.pending_index = None
            self.update_subtitle_display()
            self.waiting_for_resume = False
            entry = self.orig_entries[self.current_index]
            self.player.setPosition(int(entry.start_time * 1000))
        elif not self.is_adjusted_preview:
            entry = self.orig_entries[self.current_index]
            self.player.setPosition(int(entry.start_time * 1000))

        self.player.play()

        # Schedule auto-pause if enabled
        if self.auto_pause_mode:
            entry = self.orig_entries[self.current_index]
            remaining_ms = max(0, int(entry.end_time * 1000 - self.player.position()))
            self.auto_pause_timer.stop()
            self.auto_pause_timer.start(remaining_ms)

    def _auto_pause_hit(self):
        self.player.pause()

        if self.is_adjusted_preview:
            self.is_adjusted_preview = False
            return

        self.pending_index = min(self.current_index + 1, len(self.orig_entries) - 1)
        self.waiting_for_resume = True

    # Mode toggle: enforce immediate scheduling if already playing
    def toggle_mode(self):
        self.auto_pause_mode = self.mode_btn.isChecked()
        self.mode_btn.setText(
            "Mode: Auto‑Pause" if self.auto_pause_mode else "Mode: Continuous"
        )

        self.auto_pause_timer.stop()
        if (
            self.auto_pause_mode
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            pos_sec = self.player.position() / 1000.0
            self.current_index = self.find_subtitle_index(pos_sec)
            entry = self.orig_entries[self.current_index]
            remaining_ms = max(0, int(entry.end_time * 1000 - self.player.position()))
            self.auto_pause_timer.start(remaining_ms)

    # === Forward/Back ===
    def forward_to_next(self):
        # If we haven't started yet (at t=0 on first item), play the first subtitle
        if (
            self.current_index == 0
            and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
            and self.pos_slider.value() == 0
        ):
            self.jump_to_current_subtitle_and_play()
            return

        if self.current_index < len(self.orig_entries) - 1:
            self.current_index += 1
        self.jump_to_current_subtitle_and_play()

    def back_to_previous(self):
        if self.current_index > 0:
            self.current_index -= 1
        self.jump_to_current_subtitle_and_play()

    def jump_to_current_subtitle_and_play(self):
        entry = self.orig_entries[self.current_index]
        self.player.setPosition(int(entry.start_time * 1000))
        self.update_subtitle_display()
        self.waiting_for_resume = False
        self.player.play()
        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

        if self.auto_pause_mode:
            self.auto_pause_timer.stop()
            remaining_ms = max(0, int(entry.end_time * 1000 - self.player.position()))
            self.auto_pause_timer.start(remaining_ms)

    # === Slider ===
    def on_slider_pressed(self):
        self.slider_active = True

    def on_slider_released(self):
        self.slider_active = False
        pos = self.pos_slider.value()
        self.player.setPosition(pos)
        self.current_index = self.find_subtitle_index(pos / 1000.0)
        self.update_subtitle_display()
        self.waiting_for_resume = False
        self.show_current_segment_in_adjuster()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

        self.auto_pause_timer.stop()
        if (
            self.auto_pause_mode
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            entry = self.orig_entries[self.current_index]
            remaining_ms = max(0, int(entry.end_time * 1000 - self.player.position()))
            self.auto_pause_timer.start(remaining_ms)

    def update_slider(self, pos):
        if not self.pos_slider.isSliderDown():
            self.pos_slider.setValue(pos)
        self.time_label.setText(
            f"{self.format_time(pos)} / {self.format_time(self.total_duration)}"
        )

    def update_duration(self, dur):
        self.total_duration = dur
        self.pos_slider.setRange(0, dur)
        self.show_current_segment_in_adjuster()

    def seek(self, pos):
        self.player.setPosition(pos)

    @staticmethod
    def format_time(ms: int) -> str:
        seconds = ms // 1000
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02}"

    # === Search Features ===
    def run_search(self):
        term = self.search_input.text().strip().lower()
        if not term:
            QMessageBox.warning(self, "Empty Search", "Please enter a search term.")
            return
        self.search_matches = []
        for i, entry in enumerate(self.orig_entries):
            orig_text = entry.text.lower()
            trans_text = (
                self.trans_entries[i].text.lower()
                if i < len(self.trans_entries)
                else ""
            )
            match_orig = self.radio_orig.isChecked() and term in orig_text
            match_trans = self.radio_trans.isChecked() and term in trans_text
            match_both = self.radio_both.isChecked() and (
                term in orig_text or term in trans_text
            )
            if match_orig or match_trans or match_both:
                self.search_matches.append(i)
        if not self.search_matches:
            QMessageBox.information(self, "No Results", f"No matches for '{term}'.")
            return
        self.search_index = 0
        self.jump_to_match()

    def jump_to_match(self):
        if not self.search_matches:
            return
        idx = self.search_matches[self.search_index]
        self.current_index = idx
        entry = self.orig_entries[idx]
        self.player.setPosition(int(entry.start_time * 1000))
        self.update_subtitle_display()
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.show_current_segment_in_adjuster()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    def next_match(self):
        self.jump_to_match()

    # === Anki Card Creation ===
    def create_anki_card(self):
        # Local imports to avoid circulars
        from anki_slicer.ankiconnect import AnkiConnect
        from anki_slicer.slicer import slice_audio
        import os

        # 1) Check Anki availability FIRST (show a friendly message if not running)
        anki = AnkiConnect()
        try:
            if hasattr(anki, "is_available"):
                if not anki.is_available():
                    QMessageBox.warning(
                        self,
                        "Anki Not Running",
                        "Anki with the Anki-Connect add-on must be running.",
                    )
                    return
            else:
                # Fallback ping
                anki._invoke("version")
        except Exception:
            QMessageBox.warning(
                self,
                "Anki Not Running",
                "Anki with the Anki-Connect add-on must be running.",
            )
            return

        # 2) Prevent double-create for the same segment
        if self.card_created_for_current_segment:
            QMessageBox.information(
                self,
                "Already Created",
                "An Anki card has already been created for this segment. Play to a new segment to enable the button.",
            )
            return

        # 3) Gather data
        current_entry = self.orig_entries[self.current_index]
        trans_entry = (
            self.trans_entries[self.current_index]
            if self.current_index < len(self.trans_entries)
            else None
        )
        start_sec, end_sec = self.adjuster.get_adjusted_segment()
        deck_name = self.anki_deck_input.text().strip() or "AnkiSlicer"

        # 4) Main operation (single try/except)
        try:
            # Ensure deck exists
            if hasattr(anki, "ensure_deck"):
                anki.ensure_deck(deck_name)
            else:
                anki.create_deck(deck_name)

            # Ensure output dir
            out_dir = "anki_clips"
            os.makedirs(out_dir, exist_ok=True)

            # Slice audio
            clip_path = slice_audio(
                self.mp3_path,
                current_entry,
                out_dir,
                override_start=start_sec,
                override_end=end_sec,
            )
            clip_path = os.path.abspath(clip_path)

            # Fallback if the slicer didn’t produce a file (rare)
            if not os.path.exists(clip_path):
                clip_path = self._export_clip_fallback(
                    out_dir, start_sec, end_sec, self.current_index + 1
                )
            if not os.path.exists(clip_path):
                raise FileNotFoundError(f"Clip not found after slicing: {clip_path}")

            # Add note to Anki
            anki.add_note(
                current_entry.text,
                trans_entry.text if trans_entry else "(no translation)",
                clip_path,
                deck_name=deck_name,
            )

            # Success UI + state
            QMessageBox.information(
                self,
                "Card Created",
                f"Anki card created for segment {self.current_index + 1} in deck '{deck_name}'.",
            )
            self.card_created_for_current_segment = True
            self.set_create_button_enabled(False)

        except Exception as e:
            QMessageBox.critical(
                self,
                "Anki Error",
                f"Failed to create Anki card: {e}. Ensure Anki and the Anki‑Connect add‑on are running.",
            )
