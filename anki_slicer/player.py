from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QSlider,
    QLineEdit,
    QTextEdit,
    QSizePolicy,
    QFormLayout,
    QFrame,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QTimer, Qt, QSettings, QEvent
from PyQt6.QtGui import QKeySequence, QAction, QFont
import logging
import re
from anki_slicer.subs import SubtitleEntry
from anki_slicer.segment_adjuster import SegmentAdjusterWidget
from anki_slicer.ankiconnect import AnkiConnect
import tempfile
import os
import markdown
from PyQt6.QtGui import QIcon, QPixmap
from pathlib import Path

logger = logging.getLogger(__name__)


def format_markdown(text: str) -> str:
    """Convert Markdown into HTML so Qt/Anki can render bullets/lists/etc."""
    return markdown.markdown(text)


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

        # Set window icon if present
        try:
            icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        self.mp3_path = mp3_path
        self.orig_entries = orig_entries
        self.trans_entries = trans_entries
        self.current_index = 0

        # Do not mutate parsed subtitles from UI edits; keep user edits separately
        # so parsing issues are easier to diagnose. Keys are 0-based indices.
        self.trans_overrides: dict[int, str] = {}

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
        # Update play/pause UI when state changes
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

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
        # Accepts the signal's str arg (or none) without complaining
        self.settings.setValue("anki_deck_name", self.anki_deck_input.text().strip())

    def setup_ui(self):
        layout = QVBoxLayout()
        self._updating_ui = False

        # Top bar (grey area): Load files button
        top_bar = QHBoxLayout()
        self.load_files_btn = QPushButton("Load files")
        self.load_files_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.load_files_btn.setStyleSheet(
            "border:1px solid #dddddd; border-radius:4px; padding:4px 10px; background:#ffffff;"
        )
        self.load_files_btn.clicked.connect(self.open_file_selector)
        top_bar.addWidget(self.load_files_btn)
        top_bar.addStretch(1)
        layout.addLayout(top_bar)

        # === Text panel (Search + Original/Translation) ===
        text_panel = QFrame()
        text_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(16, 16, 16, 16)
        text_layout.setSpacing(10)

        # Search controls (single row: input, button, counter)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search subtitles...")
        # Compact width: just enough for the placeholder text
        try:
            ph = self.search_input.placeholderText() or "Search subtitles..."
            w = self.search_input.fontMetrics().horizontalAdvance(ph) + 20
            self.search_input.setFixedWidth(max(140, w))
        except Exception:
            # Sensible fallback
            self.search_input.setFixedWidth(160)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.on_search_button)
        self.search_input.returnPressed.connect(self.on_search_button)
        # Make button size follow its label (fixed) with modest padding
        self.search_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.search_btn.setStyleSheet(
            "border:1px solid #dddddd; border-radius:4px; padding:4px 10px; background:#ffffff;"
        )
        self.search_counter = QLabel("")
        self.search_counter.setStyleSheet("color:#666; font-size:12px; padding-left:6px;")
        # Reserve fixed width so search box doesn't resize when counter appears
        reserve_w = self.fontMetrics().horizontalAdvance("999 of 999") + 12
        self.search_counter.setFixedWidth(reserve_w)

        self.search_input.textChanged.connect(self.clear_search_state)

        search_row.addWidget(self.search_input)
        search_row.addWidget(self.search_btn)
        search_row.addWidget(self.search_counter)
        search_row.addStretch(1)
        text_layout.addLayout(search_row)

        # === Subtitle displays ===
        base_style = (
            "padding: 6px; background-color: #ffffff; "
            "border: 1px solid #dddddd; border-radius: 4px; color: #3565B1;"
        )

        trans_title = QLabel("Translation")
        trans_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #E0E0E0;"
        )

        # Header row for Original label (progress removed)
        orig_header_row = QHBoxLayout()
        orig_title = QLabel("Original")
        orig_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #E0E0E0;"
        )
        orig_header_row.addWidget(orig_title)
        orig_header_row.addStretch(1)
        text_layout.addLayout(orig_header_row)

        # Original: editable single-line
        self.orig_input = QLineEdit()
        self.orig_input.setPlaceholderText("Edit original subtitle…")
        # Use a leaner style for the single-line editor to prevent visual clipping
        self.orig_input.setStyleSheet(
            "border: 1px solid #dddddd; border-radius: 4px; "
            "padding: 2px 8px; background-color: #ffffff; color: #3565B1;"
        )
        self.orig_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        # Minimal text margins to avoid overlap with the rounded border
        try:
            self.orig_input.setTextMargins(2, 2, 2, 2)
        except Exception:
            pass
        self.orig_input.textChanged.connect(self.on_original_changed)

        # Translation: editable Markdown with fixed height + scrollbar
        self.trans_editor = QTextEdit()
        # Accept only plain text editing to avoid HTML paste breaking lists
        self.trans_editor.setAcceptRichText(False)
        # Remove placeholder to avoid any chance of masking empty first entries
        # (user requested disabling placeholder)
        try:
            self.trans_editor.setPlaceholderText("")
        except Exception:
            pass
        self.trans_editor.setStyleSheet(base_style)
        self.trans_editor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.trans_editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.trans_editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.trans_editor.textChanged.connect(self.on_translation_changed)
        try:
            # Reduce document margin so text isn't blocked by padding
            self.trans_editor.document().setDocumentMargin(6)
            self.trans_editor.setViewportMargins(0, 0, 0, 0)
        except Exception:
            pass

        # Unify font sizes between Original and Translation to a midpoint of their defaults
        try:
            fo = self.orig_input.font()
            ft = self.trans_editor.font()
            po = fo.pointSize()
            pt = ft.pointSize()
            if po > 0 and pt > 0:
                mid = max(8, int(round((po + pt) / 2)))
                fo.setPointSize(mid)
                ft.setPointSize(mid)
                self.orig_input.setFont(fo)
                self.trans_editor.setFont(ft)
        except Exception:
            pass

        # Fix heights: Original ~1 line; Translation ~6 lines (based on unified fonts)
        fm_o = self.orig_input.fontMetrics()
        fm_t = self.trans_editor.fontMetrics()
        self.orig_input.setMinimumHeight(int(fm_o.lineSpacing() + 12))
        self.trans_editor.setFixedHeight(int(fm_t.lineSpacing() * 6 + 20))

        text_layout.addWidget(self.orig_input)
        text_layout.addWidget(trans_title)
        text_layout.addWidget(self.trans_editor)

        # Add text panel to main layout
        layout.addWidget(text_panel)

        # === Audio panel (Slider, controls, waveform, segment controls) ===
        audio_panel = QFrame()
        audio_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        audio_layout = QVBoxLayout(audio_panel)
        audio_layout.setContentsMargins(16, 16, 16, 16)
        audio_layout.setSpacing(10)

        # Slider + time
        slider_row = QHBoxLayout()
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 0)
        self.pos_slider.sliderMoved.connect(self.seek)
        self.pos_slider.sliderPressed.connect(self.on_slider_pressed)
        self.pos_slider.sliderReleased.connect(self.on_slider_released)
        # Style the slider for better visibility and a grey handle
        self.pos_slider.setStyleSheet(
            "QSlider::groove:horizontal{height:6px;background:#e6e6e6;border-radius:3px;}"
            "QSlider::handle:horizontal{background:#cccccc;border:1px solid #b3b3b3;width:16px;height:16px;margin:-5px 0;border-radius:8px;}"
            "QSlider::handle:horizontal:hover{background:#bdbdbd;}"
            "QSlider::handle:horizontal:pressed{background:#9e9e9e;}"
        )
        self.time_label = QLabel("00:00 / 00:00")
        slider_row.addWidget(self.pos_slider, stretch=1)
        slider_row.addWidget(self.time_label)
        audio_layout.addLayout(slider_row)

        # === Playback controls ===
        # Swap positions: Back on the left, Forward on the right.
        controls = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setStyleSheet("border: 1px solid #dddddd; border-radius: 4px;")
        self.back_btn.clicked.connect(self.back_to_previous)
        self.forward_btn = QPushButton("Forward")
        self.forward_btn.setStyleSheet("border: 1px solid #dddddd; border-radius: 4px;")
        self.forward_btn.clicked.connect(self.forward_or_pause)
        self.mode_btn = QPushButton("Switch to Auto‑Pause")
        self.mode_btn.setCheckable(True)
        self.mode_btn.clicked.connect(self.toggle_mode)
        # Keep mode button color stable (white in both states)
        self.mode_btn.setStyleSheet(
            "QPushButton{background-color:#ffffff; border:1px solid #dddddd; border-radius:4px;} "
            "QPushButton:checked{background-color:#ffffff; border:1px solid #dddddd; border-radius:4px;}"
        )
        controls.addWidget(self.back_btn)
        controls.addWidget(self.forward_btn)
        controls.addWidget(self.mode_btn)
        audio_layout.addLayout(controls)

        # === Waveform widget ===
        self.adjuster = SegmentAdjusterWidget(self.mp3_path, self.player)
        self.adjuster.setFixedHeight(160)
        audio_layout.addWidget(self.adjuster)

        # === Segment adjustment controls ===
        segment_controls_row = QHBoxLayout()
        segment_controls_row.setSpacing(10)

        start_label = QLabel("Adjust Start:")
        start_label.setStyleSheet("font-weight: bold;")
        self.start_minus = QPushButton("−")
        self.start_plus = QPushButton("+")
        for btn in (self.start_minus, self.start_plus):
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("font-size: 16px; font-weight: bold; border:1px solid #dddddd; border-radius:4px;")
        segment_controls_row.addWidget(start_label)
        segment_controls_row.addWidget(self.start_minus)
        segment_controls_row.addWidget(self.start_plus)

        segment_controls_row.addStretch(1)

        # Extend Selection between start and end controls
        self.add_next_btn = QPushButton("Extend Selection →→")
        self.add_next_btn.clicked.connect(self.toggle_extend_selection)
        self.add_next_btn.setMinimumWidth(200)
        self.add_next_btn.setStyleSheet(
            "border: 1px solid #dddddd; border-radius: 4px; padding: 6px 16px; background:#ffffff; color:#000;"
        )
        segment_controls_row.addWidget(self.add_next_btn)

        segment_controls_row.addStretch(1)

        end_label = QLabel("Adjust End:")
        end_label.setStyleSheet("font-weight: bold;")
        self.end_minus = QPushButton("−")
        self.end_plus = QPushButton("+")
        for btn in (self.end_minus, self.end_plus):
            btn.setFixedSize(32, 32)
            btn.setStyleSheet("font-size: 16px; font-weight: bold; border:1px solid #dddddd; border-radius:4px;")
        segment_controls_row.addWidget(end_label)
        segment_controls_row.addWidget(self.end_minus)
        segment_controls_row.addWidget(self.end_plus)

        audio_layout.addLayout(segment_controls_row)
        # Ensure initial inactive styling/text for Extend button
        try:
            self.set_extend_button_active_style(False)
            self.add_next_btn.setText("Extend Selection →→")
        except Exception:
            pass
        # Add audio panel to main layout
        layout.addWidget(audio_panel)

        # Optional on-screen debug label (enabled via ANKI_SLICER_DEBUG)
        self.debug_enabled = bool(os.getenv("ANKI_SLICER_DEBUG"))
        if self.debug_enabled:
            self.debug_label = QLabel("")
            self.debug_label.setStyleSheet(
                "color:#555; font-family: Menlo, Courier, monospace; font-size: 12px; padding: 4px;"
            )
            try:
                self.debug_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            except Exception:
                pass
            layout.addWidget(self.debug_label)

        # Connect nudges
        self.start_minus.clicked.connect(lambda: self.nudge_segment("start", -0.05))
        self.start_plus.clicked.connect(lambda: self.nudge_segment("start", +0.05))
        self.end_minus.clicked.connect(lambda: self.nudge_segment("end", -0.05))
        self.end_plus.clicked.connect(lambda: self.nudge_segment("end", +0.05))

        # === Anki panel ===
        anki_panel = QFrame()
        anki_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        bottom_row = QHBoxLayout(anki_panel)
        bottom_row.setContentsMargins(16, 16, 16, 16)
        bottom_row.setSpacing(10)

        # Form with aligned labels
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # Deck field
        self.anki_deck_input = QLineEdit()
        self.anki_deck_input.setStyleSheet("border:1px solid #dddddd; border-radius:4px; background-color:#ffffff; padding:6px;")
        self.anki_deck_input.setText(
            self.settings.value("anki_deck_name", "AnkiSlicer")
        )
        self.anki_deck_input.textChanged.connect(self.save_anki_deck_name)
        form.addRow("Anki Deck:", self.anki_deck_input)

        # Source field
        self.source_input = QLineEdit()
        self.source_input.setStyleSheet("border:1px solid #dddddd; border-radius:4px; background-color:#ffffff; padding:6px;")
        self.source_input.setPlaceholderText("e.g., YouTube URL or show name")
        self.source_input.setText(self.settings.value("anki_source", ""))
        self.source_input.textChanged.connect(
            lambda *_: self.settings.setValue("anki_source", self.source_input.text())
        )
        form.addRow("Source:", self.source_input)

        # Tags field
        self.tags_input = QLineEdit()
        self.tags_input.setStyleSheet("border:1px solid #dddddd; border-radius:4px; background-color:#ffffff; padding:6px;")
        self.tags_input.setPlaceholderText("comma-separated, e.g., Chinese,news,HSK")
        self.tags_input.setText(self.settings.value("anki_tags", ""))
        self.tags_input.textChanged.connect(
            lambda *_: self.settings.setValue("anki_tags", self.tags_input.text())
        )
        form.addRow("Tags:", self.tags_input)

        bottom_row.addLayout(form, stretch=3)
        bottom_row.addStretch(1)

        # Create button: bigger and right-aligned
        self.create_card_btn = QPushButton("Create Anki Card")
        self.set_create_button_enabled(False)
        self.create_card_btn.setMinimumHeight(96)
        self.create_card_btn.setMinimumWidth(208)
        self.create_card_btn.setStyleSheet(
            "padding: 12px 24px; font-size: 18px; font-weight: bold; border:1px solid #dddddd; border-radius:6px;"
        )
        bottom_row.addWidget(
            self.create_card_btn,
            stretch=0,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        layout.addWidget(anki_panel)

        self.create_card_btn.clicked.connect(self.create_anki_card)

        self.setLayout(layout)
        self.update_subtitle_display()
        # Extended selection state (chainable)
        self.extend_active = False
        self.extend_count = 0  # number of extra segments appended (0..2)
        self.extend_direction = 1  # +1 until 3, then -1 back to 0
        self.extend_end_index = None
        self.extend_base_index = None
        self.extend_sel_start = None
        self.extend_sel_end = None
        self.temp_combined_orig = None
        self.temp_combined_trans = None

    def on_original_changed(self):
        if getattr(self, "_updating_ui", False):
            return
        try:
            if getattr(self, "extend_active", False):
                # Do not persist edits into entries during extended mode
                self.temp_combined_orig = self.orig_input.text()
            else:
                self.orig_entries[self.current_index].text = self.orig_input.text()
        except Exception:
            pass
        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    def on_translation_changed(self):
        if getattr(self, "_updating_ui", False):
            return
        try:
            text = self._get_current_translation_markdown()
            if getattr(self, "extend_active", False):
                self.temp_combined_trans = text
            else:
                # Avoid creating an override that erases a non-empty parsed value
                parsed = (
                    self.trans_entries[self.current_index].text
                    if self.current_index < len(self.trans_entries)
                    else ""
                )
                if not text.strip() and (parsed or "").strip():
                    # ignore empty override when parsed has content
                    pass
                elif text == (parsed or ""):
                    # identical to parsed -> clear override if present
                    if self.current_index in self.trans_overrides:
                        self.trans_overrides.pop(self.current_index, None)
                else:
                    # meaningful user edit
                    self.trans_overrides[self.current_index] = text
        except Exception:
            pass
        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    # Persist edits into the current entries
    def save_current_edits(self):
        try:
            if not getattr(self, "extend_active", False):
                orig_text = self.orig_input.text()
                self.orig_entries[self.current_index].text = orig_text
        except Exception:
            pass
        # No-op for translation: we keep overrides only

    # Styled enable/disable for the Create button
    def set_create_button_enabled(self, enabled: bool):
        # Safeguard: during initial UI setup, this may be called before
        # the create button is constructed.
        if not hasattr(self, "create_card_btn"):
            return
        self.create_card_btn.setEnabled(enabled)
        if enabled:
            self.create_card_btn.setStyleSheet(
                "background-color: #3565B1; color: white; font-weight: bold;"
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
        self._update_forward_button_label()

    # Event filter for waveform clicks: toggle play/pause of current selection only
    def eventFilter(self, obj, event):
        if obj is self.adjuster and event.type() == QEvent.Type.MouseButtonPress:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and self.is_adjusted_preview:
                # Pause current selection preview
                self.auto_pause_timer.stop()
                self.player.pause()
                self.is_adjusted_preview = False
                self._update_forward_button_label()
            else:
                # Start playing the currently adjusted selection only
                self.play_adjusted_segment()
            return True
        return super().eventFilter(obj, event)

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
        # Also freeze the index entirely while extended selection is active
        if self.slider_active or self.is_adjusted_preview or getattr(self, "extend_active", False):
            return
        position_sec = self.player.position() / 1000.0
        new_index = self.find_subtitle_index(position_sec)
        if new_index != self.current_index:
            self.save_current_edits()
            self.current_index = new_index
            self.update_subtitle_display()

    def show_current_segment_in_adjuster(self):
        entry = self.orig_entries[self.current_index]
        total_sec = max(0.0, (self.total_duration or 0) / 1000.0)
        margin = float(self.MARGIN_SEC)

        # If extended, union base..end
        if getattr(self, "extend_active", False) and self.extend_end_index is not None and self.extend_end_index < len(self.orig_entries):
            base_idx = self.extend_base_index if self.extend_base_index is not None else self.current_index
            base_entry = self.orig_entries[base_idx]
            # Use locked selection if available (prevents drifting)
            sel_start = self.extend_sel_start if self.extend_sel_start is not None else base_entry.start_time
            sel_end = self.extend_sel_end if self.extend_sel_end is not None else self.orig_entries[self.extend_end_index].end_time
            raw_start = max(0.0, sel_start - margin)
            raw_end = sel_end + margin
        else:
            sel_start = entry.start_time
            sel_end = entry.end_time
            raw_start = max(0.0, sel_start - margin)
            raw_end = sel_end + margin
        if total_sec > 0:
            raw_end = min(raw_end, total_sec)

        self.adjuster.set_bounds_and_selection(raw_start, raw_end, sel_start, sel_end)

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)
        self.update_debug()

    def update_subtitle_display(self):
        orig_entry = self.orig_entries[self.current_index]
        trans_entry = (
            self.trans_entries[self.current_index]
            if self.current_index < len(self.trans_entries)
            else None
        )

        # Decide what to show based on extended mode.
        if getattr(self, "extend_active", False) and self.extend_end_index is not None and self.extend_end_index < len(self.orig_entries):
            # Always rebuild combined display from the anchored base to end to avoid omissions
            base_idx = self.extend_base_index if self.extend_base_index is not None else self.current_index
            end_idx = self.extend_end_index
            orig_parts = [self.orig_entries[i].text for i in range(base_idx, end_idx + 1)]
            show_orig = " ".join(p.strip() for p in orig_parts if p).strip()
            # Build translation strictly from parsed translation entries only (no fallback).
            trans_parts: list[str] = []
            for i in range(base_idx, end_idx + 1):
                # Use override if present; otherwise parsed text
                if i in self.trans_overrides:
                    t = self.trans_overrides[i]
                else:
                    t = self.trans_entries[i].text if i < len(self.trans_entries) else ""
                # Preserve empty lines to reflect missing translations explicitly
                trans_parts.append(t or "")
            show_trans = "\n".join(trans_parts)
        else:
            show_orig = orig_entry.text
            # Always show exactly what was parsed/overridden for translation (no fallback)
            if self.current_index in self.trans_overrides:
                show_trans = self.trans_overrides[self.current_index]
            else:
                show_trans = trans_entry.text if trans_entry else ""

        # Populate editors without triggering change handlers
        try:
            self._updating_ui = True
            self.orig_input.setText(show_orig)
            if show_trans:
                # Render Markdown in the editor while still disallowing rich-text pastes
                if hasattr(self.trans_editor, 'setMarkdown'):
                    self.trans_editor.setMarkdown(show_trans)
                else:
                    self.trans_editor.setPlainText(show_trans)
            else:
                self.trans_editor.clear()
        finally:
            self._updating_ui = False

        self.show_current_segment_in_adjuster()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)
        self.update_extend_button_enabled()
        self.update_debug()

    # ----- Message helpers (use app icon on dialogs) -----
    def _app_qicon(self) -> QIcon:
        try:
            icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
            if icon_path.exists():
                return QIcon(str(icon_path))
        except Exception:
            pass
        return QIcon()

    def _message(self, icon: QMessageBox.Icon, title: str, text: str):
        box = QMessageBox(self)
        # Set titlebar/dock icon
        box.setWindowIcon(self._app_qicon())
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        # Also set the dialog icon pixmap so the in-dialog graphic is our app icon
        try:
            icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
            if icon_path.exists():
                pm = QPixmap(str(icon_path))
                if not pm.isNull():
                    box.setIconPixmap(pm.scaled(64, 64))
        except Exception:
            pass
        box.exec()

    # Spacebar play/pause
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.auto_pause_timer.stop()
            self.player.pause()
            self.show_current_segment_in_adjuster()
            self._update_forward_button_label()
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
        self._update_forward_button_label()

        # Schedule auto-pause if enabled
        if self.auto_pause_mode:
            end_time = self._current_playback_end_time()
            remaining_ms = max(0, int(end_time * 1000 - self.player.position()))
            self.auto_pause_timer.stop()
            self.auto_pause_timer.start(remaining_ms)

    def _auto_pause_hit(self):
        self.player.pause()

        if self.is_adjusted_preview:
            self.is_adjusted_preview = False
            return

        self.pending_index = min(self.current_index + 1, len(self.orig_entries) - 1)
        self.waiting_for_resume = True
        # Update the Forward button label when paused
        self._update_forward_button_label()

    # Mode toggle: enforce immediate scheduling if already playing
    def toggle_mode(self):
        self.auto_pause_mode = self.mode_btn.isChecked()
        self.mode_btn.setText(
            "Switch to Continuous" if self.auto_pause_mode else "Switch to Auto‑Pause"
        )

        self.auto_pause_timer.stop()
        if (
            self.auto_pause_mode
            and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ):
            pos_sec = self.player.position() / 1000.0
            self.current_index = self.find_subtitle_index(pos_sec)
            end_time = self._current_playback_end_time()
            remaining_ms = max(0, int(end_time * 1000 - self.player.position()))
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
            self.cancel_extend_selection()
            self.save_current_edits()
            self.current_index += 1
        self.jump_to_current_subtitle_and_play()

    def back_to_previous(self):
        if self.current_index > 0:
            self.cancel_extend_selection()
            self.save_current_edits()
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
        new_index = self.find_subtitle_index(pos / 1000.0)
        if new_index != self.current_index:
            self.cancel_extend_selection()
            self.save_current_edits()
            self.current_index = new_index
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
        self.update_debug()

    def _on_playback_state_changed(self, state):
        self._update_forward_button_label()

    def _update_forward_button_label(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.forward_btn.setText("Pause")
        else:
            self.forward_btn.setText("Forward")
        self.update_debug()

    def forward_or_pause(self):
        # If playing, this acts as a Pause button; otherwise it advances
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.auto_pause_timer.stop()
            self.player.pause()
            self._update_forward_button_label()
        else:
            self.forward_to_next()
        self.update_debug()

    def _current_playback_end_time(self) -> float:
        if getattr(self, "extend_active", False) and self.extend_end_index is not None and self.extend_end_index < len(self.orig_entries):
            if self.extend_sel_end is not None:
                return self.extend_sel_end
            return self.orig_entries[self.extend_end_index].end_time
        return self.orig_entries[self.current_index].end_time

    def _infer_index_from_adjuster_start(self) -> int:
        try:
            sel_start, _ = self.adjuster.get_adjusted_segment()
            # Nudge inside the segment to avoid boundary ambiguity
            return self.find_subtitle_index(max(0.0, sel_start + 1e-6))
        except Exception:
            return self.current_index

    def seek(self, pos):
        self.player.setPosition(pos)
        self.update_debug()

    @staticmethod
    def format_time(ms: int) -> str:
        seconds = ms // 1000
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02}"

    # Helpers for translation markdown access
    def _get_current_translation_markdown(self) -> str:
        # Prefer Markdown so bullets/lists/etc. are preserved when exporting to Anki
        if hasattr(self.trans_editor, 'toMarkdown'):
            return self.trans_editor.toMarkdown()
        return self.trans_editor.toPlainText()

    def update_extend_button_enabled(self):
        enabled = self.current_index < len(self.orig_entries) - 1
        self.add_next_btn.setEnabled(enabled)
        self.update_debug()

    def update_debug(self):
        if not getattr(self, 'debug_enabled', False):
            return
        try:
            base_idx = self.extend_base_index if getattr(self, 'extend_base_index', None) is not None else self.current_index
            end_idx = self.extend_end_index if getattr(self, 'extend_end_index', None) is not None else self.current_index
            sel_start, sel_end = self.adjuster.get_adjusted_segment()
            playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            pos_ms = self.player.position()
            # Peek at translation parts for troubleshooting
            # Effective translation values (consider overrides)
            t0 = (
                self.trans_overrides.get(base_idx)
                if base_idx in self.trans_overrides
                else (self.trans_entries[base_idx].text if base_idx < len(self.trans_entries) else "")
            )
            t1 = (
                self.trans_overrides.get(base_idx + 1)
                if (base_idx + 1) in self.trans_overrides
                else (self.trans_entries[base_idx + 1].text if base_idx + 1 < len(self.trans_entries) else "")
            )
            t0s = (t0 or "").replace("\n", " ⏎ ")[:40]
            t1s = (t1 or "").replace("\n", " ⏎ ")[:40]
            peek = (
                f"t0len={len((t0 or '').strip())} t1len={len((t1 or '').strip())} "
                f"t0='{t0s}' t1='{t1s}'"
            )
            text = (
                f"idx={self.current_index+1} base={base_idx+1} end={end_idx+1} "
                f"count={getattr(self,'extend_count',0)} dir={getattr(self,'extend_direction',1)} active={getattr(self,'extend_active',False)} "
                f"sel={sel_start:.3f}-{sel_end:.3f} pos={pos_ms/1000.0:.3f}s playing={playing} autopause={self.auto_pause_mode} {peek}"
            )
            self.debug_label.setText(text)
        except Exception:
            pass

    def open_file_selector(self):
        try:
            self.auto_pause_timer.stop()
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        # Launch the file selector to load a new set of files
        try:
            from .ui import FileSelectorUI
            # Keep a reference so it doesn't get garbage-collected immediately
            self._selector_window = FileSelectorUI()
            try:
                # When selector launches a new player, close this one
                self._selector_window.playerLaunched.connect(self._on_new_player_launched)
            except Exception:
                pass
            self._selector_window.show()
        except Exception:
            pass
        # Do not close this window immediately; it will close when the selector launches the new player

    def _on_new_player_launched(self):
        try:
            self.close()
        except Exception:
            pass

    def set_extend_button_active_style(self, active: bool):
        if active:
            self.add_next_btn.setStyleSheet(
                "background-color:#3565B1; color:#ffffff; border:1px solid #dddddd; border-radius:4px; padding:6px 16px;"
            )
        else:
            self.add_next_btn.setStyleSheet(
                "border:1px solid #dddddd; border-radius:4px; padding:6px 16px; background:#ffffff; color:#000;"
            )

    def refresh_extend_button_ui(self):
        try:
            if getattr(self, 'extend_active', False) and getattr(self, 'extend_count', 0) > 0:
                self.set_extend_button_active_style(True)
                self.add_next_btn.setText(f"Extend Selection →→ ({self.extend_count})")
            else:
                self.set_extend_button_active_style(False)
                self.add_next_btn.setText("Extend Selection →→")
        except Exception:
            pass

    def toggle_extend_selection(self):
        # Stop current preview and pause so rapid clicks always respond
        try:
            self.auto_pause_timer.stop()
            self.is_adjusted_preview = False
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        except Exception:
            pass
        # Cycle extend count: 0→1→2→1→0 ... (max two extra segments)
        base_idx_for_limits = (
            self.extend_base_index if self.extend_active and self.extend_base_index is not None else self.current_index
        )
        max_extras = min(2, len(self.orig_entries) - 1 - base_idx_for_limits)
        if max_extras <= 0:
            self.cancel_extend_selection()
            return
        if not self.extend_active:
            self.extend_count = 0
            self.extend_direction = 1
            # Anchor base to the current adjusted selection start (what user sees)
            self.extend_base_index = self._infer_index_from_adjuster_start()
        next_count = self.extend_count + self.extend_direction
        if next_count > max_extras:
            self.extend_direction = -1
            next_count = self.extend_count + self.extend_direction
        elif next_count < 0:
            next_count = 0
        self.set_extend_count(next_count)
        self.refresh_extend_button_ui()
        self.update_debug()

    def set_extend_count(self, count: int):
        count = max(0, min(2, count))
        base_idx = self.extend_base_index if self.extend_base_index is not None else self.current_index
        max_extras = min(2, len(self.orig_entries) - 1 - base_idx)
        count = min(count, max_extras)
        self.extend_count = count
        self.extend_active = count > 0
        if not self.extend_active:
            # Capture base idx before reset, so we can snap back
            base_idx_local = base_idx
            self.cancel_extend_selection()
            try:
                # Snap selection back to base and pause
                self.current_index = base_idx_local
                entry = self.orig_entries[base_idx_local]
                self.player.pause()
                self.player.setPosition(int(entry.start_time * 1000))
            except Exception:
                pass
            self.update_subtitle_display()
            self.refresh_extend_button_ui()
            return
        # Compute end index and lock selection
        self.extend_end_index = base_idx + self.extend_count
        self.extend_sel_start = self.orig_entries[base_idx].start_time
        self.extend_sel_end = self.orig_entries[self.extend_end_index].end_time
        # Force the visible/current index to the anchored base to prevent UI drift
        self.current_index = base_idx
        # Build combined texts across range
        orig_parts = [self.orig_entries[i].text for i in range(base_idx, self.extend_end_index + 1)]
        self.temp_combined_orig = " ".join(p.strip() for p in orig_parts if p).strip()
        trans_parts = []
        for i in range(base_idx, self.extend_end_index + 1):
            if i < len(self.trans_entries):
                t = self.trans_entries[i].text
                if t:
                    trans_parts.append(t.strip())
        self.temp_combined_trans = "\n".join(trans_parts).strip()
        # Visuals + playback
        self.refresh_extend_button_ui()
        self.update_subtitle_display()
        self.show_current_segment_in_adjuster()
        self.play_adjusted_segment()
        self.update_debug()

    def cancel_extend_selection(self):
        if not getattr(self, "extend_active", False):
            return
        self.extend_active = False
        self.extend_count = 0
        self.extend_direction = 1
        self.extend_end_index = None
        self.extend_base_index = None
        self.extend_sel_start = None
        self.extend_sel_end = None
        self.temp_combined_orig = None
        self.temp_combined_trans = None
        self.set_extend_button_active_style(False)
        self.add_next_btn.setText("Extend Selection →→")
        # Restore editors to current segment only
        self.update_subtitle_display()
        self.show_current_segment_in_adjuster()
        self.update_debug()

    # === Search Features ===
    def run_search(self):
        term = self.search_input.text().strip().lower()
        if not term:
            self._message(QMessageBox.Icon.Warning, "Empty Search", "Please enter a search term.")
            return
        self.search_matches = []
        for i, entry in enumerate(self.orig_entries):
            orig_text = entry.text.lower()
            trans_text = (
                self.trans_entries[i].text.lower()
                if i < len(self.trans_entries)
                else ""
            )
            if term in orig_text or term in trans_text:
                self.search_matches.append(i)
        if not self.search_matches:
            self._message(QMessageBox.Icon.Information, "No Results", f"No matches for '{term}'.")
            self.search_btn.setText("Search")
            self.search_counter.setText("")
            return
        self.search_index = 0
        self.search_total = len(self.search_matches)
        self.search_btn.setText("Next Match")
        self.jump_to_match()

    def on_search_button(self):
        # If we already have matches, the button advances to the next match
        self.cancel_extend_selection()
        if getattr(self, 'search_matches', None):
            self.next_match()
        else:
            self.run_search()

    def jump_to_match(self):
        if not self.search_matches:
            return
        idx = self.search_matches[self.search_index]
        if idx != self.current_index:
            self.cancel_extend_selection()
            self.save_current_edits()
            self.current_index = idx
        entry = self.orig_entries[idx]
        self.player.setPosition(int(entry.start_time * 1000))
        self.update_subtitle_display()
        # Update counter before incrementing the index
        try:
            current_pos = self.search_index + 1
            total = getattr(self, 'search_total', len(self.search_matches))
            self.search_counter.setText(f"{current_pos} of {total}")
        except Exception:
            pass
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.show_current_segment_in_adjuster()

        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    def clear_search_state(self, *_):
        # Reset button/counter when user changes scope or query
        self.search_matches = []
        self.search_index = 0
        self.search_total = 0
        if hasattr(self, 'search_btn'):
            self.search_btn.setText("Search")
        if hasattr(self, 'search_counter'):
            self.search_counter.setText("")
        self.cancel_extend_selection()
        self.update_debug()

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
                    self._message(
                        QMessageBox.Icon.Warning,
                        "Anki Not Running",
                        "Anki with the Anki-Connect add-on must be running.",
                    )
                    return
            else:
                # Fallback ping
                anki._invoke("version")
        except Exception:
            self._message(
                QMessageBox.Icon.Warning,
                "Anki Not Running",
                "Anki with the Anki-Connect add-on must be running.",
            )
            return

        # 2) Prevent double-create for the same segment
        if self.card_created_for_current_segment:
            self._message(
                QMessageBox.Icon.Information,
                "Already Created",
                "An Anki card has already been created for this segment. Play to a new segment to enable the button.",
            )
            return

        # 3) Gather data
        # Make sure we capture any in-place edits before creating the card
        self.save_current_edits()
        current_entry = self.orig_entries[self.current_index]
        trans_entry = (
            self.trans_entries[self.current_index]
            if self.current_index < len(self.trans_entries)
            else None
        )
        start_sec, end_sec = self.adjuster.get_adjusted_segment()
        deck_name = self.anki_deck_input.text().strip() or "AnkiSlicer"
        source_text = (self.source_input.text() or "").strip()
        tags_text = (self.tags_input.text() or "").strip()
        # Normalize tags from comma/space/semicolon separated to list
        raw_tags = (
            [t.strip() for t in re.split(r"[,;\s]+", tags_text) if t.strip()]
            if tags_text
            else []
        )

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

            # Fallback if the slicer didn't produce a file (rare)
            if not os.path.exists(clip_path):
                clip_path = self._export_clip_fallback(
                    out_dir, start_sec, end_sec, self.current_index + 1
                )
            if not os.path.exists(clip_path):
                raise FileNotFoundError(f"Clip not found after slicing: {clip_path}")

            # ✅ Add note to Anki with Markdown → HTML conversion + optional source/tags
            # Use current editor's Markdown (safer than cached entry text)
            if hasattr(self.trans_editor, 'toMarkdown'):
                md_current = self.trans_editor.toMarkdown().strip()
            else:
                md_current = self.trans_editor.toPlainText().strip()
            back_html = format_markdown(md_current) if md_current else "(no translation)"
            if source_text:
                back_html = back_html + f"<div style=\"margin-top:8px;color:#666;\"><em>Source: {source_text}</em></div>"

            anki.add_note(
                self.orig_input.text().strip() or current_entry.text,
                back_html,
                clip_path,
                deck_name=deck_name,
                tags=raw_tags,
            )

            # Success UI + state
            # Friendly message shows combined segment indices when extended
            if getattr(self, "extend_active", False) and self.extend_end_index is not None:
                base_idx = self.extend_base_index if self.extend_base_index is not None else self.current_index
                end_idx = self.extend_end_index
                segs = "+".join(str(i + 1) for i in range(base_idx, end_idx + 1))
                msg = f"Anki card created for segments {segs} in deck '{deck_name}'."
            else:
                msg = f"Anki card created for segment {self.current_index + 1} in deck '{deck_name}'."
            self._message(QMessageBox.Icon.Information, "Card Created", msg)
            self.card_created_for_current_segment = True
            self.set_create_button_enabled(False)
            # Exit extended mode after successful creation
            self.cancel_extend_selection()

        except Exception as e:
            self._message(
                QMessageBox.Icon.Critical,
                "Anki Error",
                f"Failed to create Anki card: {e}. Ensure Anki and the Anki‑Connect add‑on are running.",
            )
