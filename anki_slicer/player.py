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
    QComboBox,
    QListView,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl, QTimer, Qt, QSettings, QEvent
from PyQt6.QtGui import QKeySequence, QAction, QFont, QTextCursor
import logging
import re
import unicodedata
from typing import List
from urllib.parse import urlparse, parse_qs
from time import monotonic
from anki_slicer.subs import SubtitleEntry
from anki_slicer.segment_adjuster import SegmentAdjusterWidget
from anki_slicer.ankiconnect import AnkiConnect
from anki_slicer.youtube.embed_view import YouTubeEmbedView
from anki_slicer.youtube.captions import (
    fetch_caption_entries,
    list_transcript_options,
    TranscriptOption,
)
from anki_slicer.youtube.audio import download_audio_as_wav
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
        *,
        allow_streaming: bool = False,
    ):
        super().__init__()
        self.setWindowTitle(self.tr("Anki-slicer Player"))
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
        self.streaming_enabled = allow_streaming
        self._current_video_id: str | None = None
        self._temp_audio_files: list[str] = []
        self._video_duration_ms = 0
        self._last_video_time = 0.0
        self._video_syncing = False
        self._video_sync_target = 0.0
        self._video_playing = False
        self._caption_options: dict[str, TranscriptOption] = {}
        self._pending_video_seek: float | None = None
        self._pending_video_play: bool | None = None
        self._last_video_report_ts: float | None = None
        self._last_video_sync_command_at: float | None = None
        self._search_match_sources: dict[int, set[str]] = {}
        self._search_term_raw: str = ""
        self._search_term_norm: str = ""
        self._translator_instance = None
        self._translator_unavailable = False

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.player.setAudioOutput(self.audio_output)
        # Update play/pause UI when state changes
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

        self._tmp_wav = None
        if mp3_path:
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
        self.play_action = QAction(self.tr("Play/Pause"), self)
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

    def closeEvent(self, event):  # type: ignore[override]
        for path in self._temp_audio_files:
            try:
                os.remove(path)
            except Exception:
                pass
        super().closeEvent(event)

    def save_anki_deck_name(self, *_):
        # Accepts the signal's str arg (or none) without complaining
        self.settings.setValue("anki_deck_name", self.anki_deck_input.text().strip())

    def _handle_load_video(self, *, initial: bool = False) -> None:
        if not self.streaming_enabled:
            QMessageBox.information(
                self,
                self.tr("Streaming Disabled"),
                self.tr("This build does not support streaming video."),
            )
            return

        url = (self.source_input.text() or "").strip()
        if not url:
            if not initial:
                QMessageBox.information(
                    self,
                    self.tr("Missing URL"),
                    self.tr("Paste a YouTube link before loading."),
                )
            return

        video_id = self._extract_video_id(url)
        if not video_id:
            if not initial:
                QMessageBox.warning(
                    self,
                    self.tr("Invalid URL"),
                    self.tr("Could not extract a YouTube video ID from that link."),
                )
            return

        self._current_video_id = video_id
        self.youtube_view.load_video(video_id, autoplay=False)

        options = list_transcript_options(video_id)
        self._populate_caption_combos(options)

        if self._tmp_wav is None:
            wav_path = download_audio_as_wav(video_id)
            if wav_path:
                self._temp_audio_files.append(wav_path)
                try:
                    self.adjuster.load_waveform(wav_path)
                    self.player.setSource(QUrl.fromLocalFile(wav_path))
                    self.player.setPosition(0)
                    self.pos_slider.setEnabled(True)
                    self.time_label.setText(self.tr("00:00 / 00:00"))
                    self._tmp_wav = object()
                except Exception as exc:
                    logger.warning("Failed to load waveform for %s: %s", video_id, exc)
                    self.pos_slider.setEnabled(False)
                    self.time_label.setText(self.tr("Streaming (audio unavailable)"))
            else:
                self.pos_slider.setEnabled(False)
                self.time_label.setText(self.tr("Streaming (audio unavailable)"))

    @staticmethod
    def _extract_video_id(value: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        # Raw video ID
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value

        parsed = urlparse(value)
        if not parsed.scheme:
            # Try again assuming missing scheme
            parsed = urlparse("https://" + value)

        host = parsed.netloc.lower()
        path = parsed.path or ""

        if host.endswith("youtu.be"):
            vid = path.lstrip("/")
            return vid[:11] if len(vid) >= 11 else None

        if "youtube" in host:
            query = parse_qs(parsed.query)
            if "v" in query and query["v"]:
                return query["v"][0][:11]
            segments = [seg for seg in path.split("/") if seg]
            if segments:
                if segments[0] in {"embed", "shorts", "v"} and len(segments) > 1:
                    return segments[1][:11]

        return None

    def _populate_caption_combos(self, options: List[TranscriptOption]) -> None:
        self._caption_options = {opt.key: opt for opt in options}

        if not options:
            for combo in (self.orig_caption_combo, self.trans_caption_combo):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(self.tr("None"), "")
                combo.blockSignals(False)
            self.orig_entries = []
            self.trans_entries = []
            self.current_index = 0
            self.update_subtitle_display()
            self.show_current_segment_in_adjuster()
            return

        orig_saved = self.settings.value("yt_orig_caption", "")
        trans_saved = self.settings.value("yt_trans_caption", "")

        self._fill_caption_combo(self.orig_caption_combo, orig_saved, options, "orig")
        self._fill_caption_combo(self.trans_caption_combo, trans_saved, options, "trans")

        self._apply_caption_selection("orig")
        self._apply_caption_selection("trans")

    def _fill_caption_combo(
        self,
        combo: QComboBox,
        saved_key: str,
        options: List[TranscriptOption],
        kind: str,
    ) -> str:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.tr("None"), "")
        filtered_keys: list[str] = []
        for opt in options:
            if kind == "orig" and opt.translation_code is not None:
                continue
            if kind == "trans" and opt.translation_code is None:
                continue
            combo.addItem(opt.label, opt.key)
            filtered_keys.append(opt.key)

        target = ""
        if saved_key and saved_key in filtered_keys:
            target = saved_key
        else:
            default_key = self._default_caption_key(kind, options)
            if default_key in filtered_keys:
                target = default_key

        combo.setCurrentIndex(combo.findData(target) if target else 0)
        combo.blockSignals(False)
        return target

    def _default_caption_key(self, kind: str, options: List[TranscriptOption]) -> str:
        if kind == "orig":
            for opt in options:
                if opt.translation_code is None and not opt.is_generated:
                    return opt.key
            for opt in options:
                if opt.translation_code is None:
                    return opt.key
        else:
            preferred = ("en", "en-US")
            for pref in preferred:
                for opt in options:
                    if opt.translation_code == pref:
                        return opt.key
            for opt in options:
                if opt.translation_code is not None:
                    return opt.key
        return ""

    def _apply_caption_selection(self, kind: str) -> None:
        combo = self.orig_caption_combo if kind == "orig" else self.trans_caption_combo
        key = combo.currentData()

        if kind == "orig":
            self.settings.setValue("yt_orig_caption", key or "")
            if not key:
                self.orig_entries = []
                self.current_index = 0
                self.update_subtitle_display()
                self.show_current_segment_in_adjuster()
                return
        else:
            self.settings.setValue("yt_trans_caption", key or "")
            if not key:
                self.trans_entries = []
                self.update_subtitle_display()
                return

        option = self._caption_options.get(key)
        if not option:
            return

        entries = fetch_caption_entries(option)
        if kind == "orig":
            self.orig_entries = entries
            self.current_index = 0
            self.update_subtitle_display()
            self.show_current_segment_in_adjuster()
        else:
            if self.orig_entries and entries:
                self.trans_entries = self._align_translation_entries(
                    self.orig_entries, entries
                )
            else:
                self.trans_entries = entries
            self.update_subtitle_display()

    def _init_caption_combo(self, combo: QComboBox) -> None:
        combo.setMinimumContentsLength(36)
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumWidth(260)

        view = QListView(combo)
        view.setUniformItemSizes(True)
        view.setWordWrap(False)
        view.setSpacing(2)
        view.setMinimumWidth(360)
        view.setMinimumHeight(280)
        view.setAlternatingRowColors(True)
        combo.setView(view)

    def setup_ui(self):
        layout = QVBoxLayout()
        self._updating_ui = False

        # Top bar (grey area): Load files button
        top_bar = QHBoxLayout()
        self.load_files_btn = QPushButton(self.tr("Load files"))
        self.load_files_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.load_files_btn.setStyleSheet(
            "border:1px solid #dddddd; border-radius:4px; padding:4px 10px; background:#ffffff;"
        )
        self.load_files_btn.clicked.connect(self.open_file_selector)
        top_bar.addWidget(self.load_files_btn)
        top_bar.addStretch(1)
        layout.addLayout(top_bar)

        # === Text panel (Search + Original/Translation) ===
        self.text_panel = QFrame()
        self.text_panel.setObjectName("text_panel")
        self.text_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        text_layout = QVBoxLayout(self.text_panel)
        text_layout.setContentsMargins(16, 16, 16, 16)
        text_layout.setSpacing(10)

        # Search controls (single row: input, button, counter)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("Search subtitles..."))
        # Compact width: just enough for the placeholder text
        try:
            ph = self.search_input.placeholderText() or "Search subtitles..."
            w = self.search_input.fontMetrics().horizontalAdvance(ph) + 20
            self.search_input.setFixedWidth(max(140, w))
        except Exception:
            # Sensible fallback
            self.search_input.setFixedWidth(160)
        self.search_btn = QPushButton(self.tr("Search"))
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
        reserve_w = self.fontMetrics().horizontalAdvance(self.tr("999 of 999")) + 12
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

        trans_title = QLabel(self.tr("Translation"))
        trans_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #E0E0E0;"
        )

        # Header row for Original label (progress removed)
        orig_header_row = QHBoxLayout()
        orig_title = QLabel(self.tr("Original"))
        orig_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #E0E0E0;"
        )
        orig_header_row.addWidget(orig_title)
        orig_header_row.addStretch(1)
        text_layout.addLayout(orig_header_row)

        # Original: editable single-line
        self.orig_input = QLineEdit()
        self.orig_input.setPlaceholderText(self.tr("Edit original subtitle…"))
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
        self.orig_input.textChanged.connect(self._update_translate_button_state)
        try:
            self.orig_input.selectionChanged.connect(self._update_selected_word)
        except Exception:
            pass

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

        text_fields_container = QWidget()
        text_fields_layout = QVBoxLayout(text_fields_container)
        text_fields_layout.setContentsMargins(0, 0, 0, 0)
        text_fields_layout.setSpacing(8)
        text_fields_container.setMinimumWidth(320)
        text_fields_container.setMaximumWidth(560)

        text_fields_layout.addWidget(self.orig_input)
        text_fields_layout.addWidget(trans_title)
        text_fields_layout.addWidget(self.trans_editor)

        text_content_row = QHBoxLayout()
        text_content_row.setSpacing(12)
        text_content_row.addWidget(text_fields_container, stretch=3)

        self.text_future_panel = QFrame()
        self.text_future_panel.setObjectName("text_future_panel")
        self.text_future_panel.setMinimumWidth(240)
        self.text_future_panel.setStyleSheet(
            "QFrame#text_future_panel {"
            "border: 1px dashed #cccccc; border-radius: 6px; background-color: #fafafa;"
            "}"
        )

        future_layout = QVBoxLayout(self.text_future_panel)
        future_layout.setContentsMargins(12, 12, 12, 12)
        future_layout.setSpacing(8)

        translate_header = QLabel(self.tr("Quick Translate"))
        translate_header.setStyleSheet("font-weight:bold; color:#555555; font-size:14px;")
        future_layout.addWidget(translate_header)

        translation_hint = QLabel(
            self.tr("Use this tool when translations are missing. \nSelect a word in the Original field to focus it.")
        )
        translation_hint.setWordWrap(True)
        translation_hint.setStyleSheet("color:#888888; font-size:12px;")
        future_layout.addWidget(translation_hint)

        word_label = QLabel(self.tr("Selected word"))
        word_label.setStyleSheet("font-weight:bold; font-size:12px;")
        future_layout.addWidget(word_label)

        self.vocab_word_display = QLineEdit()
        self.vocab_word_display.setReadOnly(True)
        self.vocab_word_display.setPlaceholderText(self.tr("Select a word in the sentence…"))
        self.vocab_word_display.setStyleSheet(
            "border: 1px solid #dddddd; border-radius: 4px; padding:4px; background-color:#fefefe;"
        )
        future_layout.addWidget(self.vocab_word_display)

        translate_row = QHBoxLayout()
        self.translate_button = QPushButton(self.tr("Translate"))
        self.translate_button.setEnabled(False)
        self.translate_button.setStyleSheet(
            "QPushButton{padding:6px 12px; border-radius:4px; border:1px solid #d0d0d0; background:#ffffff;}"
            "QPushButton:disabled{color:#aaaaaa; border-color:#e0e0e0;}"
        )
        self.translate_button.clicked.connect(self._handle_translate_request)
        translate_row.addWidget(self.translate_button)
        translate_row.addStretch(1)
        future_layout.addLayout(translate_row)

        vocab_label = QLabel(self.tr("Anki Vocabulary"))
        vocab_label.setStyleSheet("font-weight:bold; font-size:12px;")
        future_layout.addWidget(vocab_label)

        self.vocab_output_edit = QTextEdit()
        self.vocab_output_edit.setAcceptRichText(False)
        self.vocab_output_edit.setPlaceholderText(self.tr("Word meaning, usage notes, etc."))
        self.vocab_output_edit.setFixedHeight(90)
        self.vocab_output_edit.setStyleSheet(
            "border:1px solid #dddddd; border-radius:4px; padding:6px; background-color:#ffffff;"
        )
        self.vocab_output_edit.textChanged.connect(self._mark_vocab_modified)
        future_layout.addWidget(self.vocab_output_edit)

        future_layout.addStretch(1)

        text_content_row.addWidget(self.text_future_panel, stretch=2)
        text_layout.addLayout(text_content_row)

        # Add text panel to main layout
        layout.addWidget(self.text_panel)

        # === Audio + Video panel ===
        media_row = QHBoxLayout()
        media_row.setSpacing(12)

        self.sound_panel = QFrame()
        self.sound_panel.setObjectName("sound_panel")
        self.sound_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        audio_layout = QVBoxLayout(self.sound_panel)
        audio_layout.setContentsMargins(16, 16, 16, 16)
        audio_layout.setSpacing(10)

        # Slider + time
        slider_row = QHBoxLayout()
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 0)
        self.pos_slider.sliderMoved.connect(self.seek)
        self.pos_slider.sliderPressed.connect(self.on_slider_pressed)
        self.pos_slider.sliderReleased.connect(self.on_slider_released)
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

        if self._tmp_wav is None:
            self.pos_slider.setEnabled(False)
            self.time_label.setText(self.tr("No audio loaded"))

        # Waveform widget
        self.adjuster = SegmentAdjusterWidget(self.mp3_path, self.player)
        self.adjuster.setFixedHeight(160)
        audio_layout.addWidget(self.adjuster)

        # === Playback controls ===
        # Swap positions: Back on the left, Forward on the right. Placed under the waveform per request.
        controls = QHBoxLayout()
        self.back_btn = QPushButton(self.tr("Back"))
        self.back_btn.setStyleSheet("border: 1px solid #dddddd; border-radius: 4px;")
        self.back_btn.clicked.connect(self.back_to_previous)
        self.forward_btn = QPushButton(self.tr("Forward"))
        self.forward_btn.setStyleSheet("border: 1px solid #dddddd; border-radius: 4px;")
        self.forward_btn.clicked.connect(self.forward_or_pause)
        self.mode_btn = QPushButton(self.tr("Switch to Auto-Pause"))
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
        audio_layout.addSpacing(12)

        # === Segment adjustment controls ===
        segment_controls_row = QHBoxLayout()
        segment_controls_row.setSpacing(10)

        start_label = QLabel(self.tr("Adjust Start:"))
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
        self.add_next_btn = QPushButton(self.tr("Extend Selection →→"))
        self.add_next_btn.clicked.connect(self.toggle_extend_selection)
        self.add_next_btn.setMinimumWidth(200)
        self.add_next_btn.setStyleSheet(
            "border: 1px solid #dddddd; border-radius: 4px; padding: 6px 16px; background:#ffffff; color:#000; font-weight:bold;"
        )
        segment_controls_row.addWidget(self.add_next_btn)

        segment_controls_row.addStretch(1)

        end_label = QLabel(self.tr("Adjust End:"))
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
            self.add_next_btn.setText(self.tr("Extend Selection →→"))
        except Exception:
            pass
        media_row.addWidget(self.sound_panel, stretch=2)

        # === Video panel ===
        self.youtube_panel = QFrame()
        self.youtube_panel.setObjectName("youtube_panel")
        self.youtube_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        video_layout = QVBoxLayout(self.youtube_panel)
        video_layout.setContentsMargins(16, 16, 16, 16)
        video_layout.setSpacing(10)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        url_label = QLabel(self.tr("YouTube URL:"))
        url_label.setStyleSheet("font-weight:bold;")
        url_row.addWidget(url_label)

        self.source_input = QLineEdit()
        self.source_input.setStyleSheet(
            "border:1px solid #dddddd; border-radius:4px; background-color:#ffffff; padding:6px;"
        )
        self.source_input.setPlaceholderText(self.tr("Paste YouTube link…"))
        self.source_input.setText(self.settings.value("anki_source", ""))
        try:
            self.source_input.setCursorPosition(0)
        except Exception:
            pass
        self.source_input.textChanged.connect(
            lambda *_: self.settings.setValue("anki_source", self.source_input.text())
        )
        self.source_input.returnPressed.connect(self._handle_load_video)
        url_row.addWidget(self.source_input, stretch=1)

        self.load_video_btn = QPushButton(self.tr("Load"))
        self.load_video_btn.setEnabled(self.streaming_enabled)
        self.load_video_btn.clicked.connect(self._handle_load_video)
        url_row.addWidget(self.load_video_btn)

        video_layout.addLayout(url_row)

        self.youtube_view = YouTubeEmbedView()
        self.youtube_view.setMinimumSize(360, 200)
        self.youtube_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        video_layout.addWidget(self.youtube_view, stretch=1)

        self.youtube_view.bridge.ready.connect(self._on_video_ready)
        self.youtube_view.bridge.durationChanged.connect(self._on_video_duration)
        self.youtube_view.bridge.timeChanged.connect(self._on_video_time)
        self.youtube_view.bridge.stateChanged.connect(self._on_video_state)

        captions_form = QFormLayout()
        captions_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.orig_caption_combo = QComboBox()
        self._init_caption_combo(self.orig_caption_combo)
        self.orig_caption_combo.addItem(self.tr("None"), "")
        self.orig_caption_combo.currentIndexChanged.connect(
            lambda _: self._apply_caption_selection("orig")
        )
        captions_form.addRow(self.tr("Original captions:"), self.orig_caption_combo)

        self.trans_caption_combo = QComboBox()
        self._init_caption_combo(self.trans_caption_combo)
        self.trans_caption_combo.addItem(self.tr("None"), "")
        self.trans_caption_combo.currentIndexChanged.connect(
            lambda _: self._apply_caption_selection("trans")
        )
        captions_form.addRow(self.tr("Translation captions:"), self.trans_caption_combo)

        video_layout.addLayout(captions_form)

        media_row.addWidget(self.youtube_panel, stretch=1)

        layout.addLayout(media_row)

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
        self.anki_panel = QFrame()
        self.anki_panel.setObjectName("anki_panel")
        self.anki_panel.setStyleSheet("background-color:#ffffff; border:none; border-radius:6px;")
        bottom_row = QHBoxLayout(self.anki_panel)
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
        form.addRow(self.tr("Anki Deck:"), self.anki_deck_input)

        # Tags field
        self.tags_input = QLineEdit()
        self.tags_input.setStyleSheet("border:1px solid #dddddd; border-radius:4px; background-color:#ffffff; padding:6px;")
        self.tags_input.setPlaceholderText(self.tr("comma-separated, e.g., Chinese,news,HSK"))
        self.tags_input.setText(self.settings.value("anki_tags", ""))
        self.tags_input.textChanged.connect(
            lambda *_: self.settings.setValue("anki_tags", self.tags_input.text())
        )
        form.addRow(self.tr("Tags:"), self.tags_input)

        bottom_row.addLayout(form, stretch=3)
        bottom_row.addStretch(1)

        # Create button: bigger and right-aligned
        self.create_card_btn = QPushButton(self.tr("Create Anki Card"))
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
        layout.addWidget(self.anki_panel)

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
        self._update_translate_button_state()

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
        if not self.orig_entries or self.current_index >= len(self.orig_entries):
            self.adjuster.set_bounds_and_selection(0.0, 0.0, 0.0, 0.0)
            self.set_create_button_enabled(False)
            self.update_debug()
            return

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
        if not self.orig_entries:
            try:
                self._updating_ui = True
                self.orig_input.clear()
                self.trans_editor.clear()
            finally:
                self._updating_ui = False
            self.set_create_button_enabled(False)
            self.update_debug()
            return

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
        self._update_selected_word()
        self._update_translate_button_state()
        try:
            self.vocab_output_edit.clear()
        except Exception:
            pass

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
            self.tr("Switch to Continuous")
            if self.auto_pause_mode
            else self.tr("Switch to Auto-Pause")
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
        if not self.orig_entries:
            return
        if self.current_index > 0:
            self.cancel_extend_selection()
            self.save_current_edits()
            self.current_index -= 1
        self.jump_to_current_subtitle_and_play()

    def jump_to_current_subtitle_and_play(self):
        if not self.orig_entries:
            return
        if self.current_index >= len(self.orig_entries):
            self.current_index = max(0, len(self.orig_entries) - 1)
        entry = self.orig_entries[self.current_index]
        self.player.setPosition(int(entry.start_time * 1000))
        self.update_subtitle_display()
        self.waiting_for_resume = False
        self.player.play()
        if self._current_video_id and self.youtube_view.is_ready:
            self.youtube_view.seek_to(entry.start_time, force=True)
            self.youtube_view.set_playing(True)
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
        if self.orig_entries:
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
        if self._current_video_id and self._tmp_wav is not None:
            self._sync_video_to_audio(pos / 1000.0)

    def update_duration(self, dur):
        self.total_duration = dur
        self.pos_slider.setRange(0, dur)
        self.show_current_segment_in_adjuster()
        self.update_debug()

    def _on_playback_state_changed(self, state):
        self._update_forward_button_label()
        if self._current_video_id:
            playing = state == QMediaPlayer.PlaybackState.PlayingState
            if self.youtube_view.is_ready:
                self.youtube_view.set_playing(playing)
            else:
                self._pending_video_play = playing
            if playing and self._tmp_wav is not None:
                self._sync_video_to_audio(self.player.position() / 1000.0, force=True)

    def _update_forward_button_label(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.forward_btn.setText(self.tr("Pause"))
        else:
            self.forward_btn.setText(self.tr("Forward"))
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
        if self._current_video_id and self._tmp_wav is not None:
            self._sync_video_to_audio(pos / 1000.0, force=True)
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

    def _sync_video_to_audio(self, seconds: float, force: bool = False) -> None:
        if not self._current_video_id:
            return

        self._video_sync_target = seconds

        if not self.youtube_view.is_ready:
            self._pending_video_seek = seconds
            return

        now = monotonic()

        if not force and self._last_video_time is not None:
            predicted = self._last_video_time
            if self._video_playing and self._last_video_report_ts is not None:
                predicted += max(0.0, now - self._last_video_report_ts)
            if abs(seconds - predicted) < 0.35:
                return
            if self._last_video_sync_command_at is not None:
                if now - self._last_video_sync_command_at < 0.6:
                    return

        self._video_syncing = True
        self._pending_video_seek = None
        self._last_video_sync_command_at = now
        self.youtube_view.seek_to(seconds, force=True)

    def _on_video_ready(self) -> None:
        self._flush_pending_video_commands()

    def _on_video_duration(self, seconds: float) -> None:
        self._video_duration_ms = int(seconds * 1000)
        if self._tmp_wav is None and self._video_duration_ms:
            if not self.pos_slider.isSliderDown():
                self.pos_slider.setRange(0, self._video_duration_ms)
                self.time_label.setText(
                    f"{self.format_time(0)} / {self.format_time(self._video_duration_ms)}"
                )

    def _on_video_time(self, seconds: float) -> None:
        self._last_video_time = seconds
        self._last_video_report_ts = monotonic()
        if self._video_syncing and abs(seconds - self._video_sync_target) < 0.3:
            self._video_syncing = False
        if self._tmp_wav is None and self._video_duration_ms:
            ms = int(seconds * 1000)
            if not self.pos_slider.isSliderDown():
                self.pos_slider.setRange(0, self._video_duration_ms)
                self.pos_slider.setValue(ms)
            self.time_label.setText(
                f"{self.format_time(ms)} / {self.format_time(self._video_duration_ms)}"
            )

    def _flush_pending_video_commands(self) -> None:
        if not self.youtube_view.is_ready:
            return
        if self._pending_video_seek is not None:
            target = self._pending_video_seek
            self._pending_video_seek = None
            self._last_video_sync_command_at = monotonic()
            self.youtube_view.seek_to(target, force=True)
        if self._pending_video_play is not None:
            play_state = self._pending_video_play
            self._pending_video_play = None
            self.youtube_view.set_playing(play_state)

    def _on_video_state(self, state: int) -> None:
        self._video_playing = state == 1
        if self._tmp_wav is None:
            if state == 1:
                self.forward_btn.setText(self.tr("Pause"))
            elif state in (0, 2):
                self.forward_btn.setText(self.tr("Forward"))

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
                "background-color:#3565B1; color:#ffffff; border:1px solid #dddddd; border-radius:4px; padding:6px 16px; font-weight:bold;"
            )
        else:
            self.add_next_btn.setStyleSheet(
                "border:1px solid #dddddd; border-radius:4px; padding:6px 16px; background:#ffffff; color:#000; font-weight:bold;"
            )

    def refresh_extend_button_ui(self):
        try:
            if getattr(self, 'extend_active', False) and getattr(self, 'extend_count', 0) > 0:
                self.set_extend_button_active_style(True)
                self.add_next_btn.setText(
                    self.tr("Extend Selection →→ ({count})").format(count=self.extend_count)
                )
            else:
                self.set_extend_button_active_style(False)
                self.add_next_btn.setText(self.tr("Extend Selection →→"))
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
        self.add_next_btn.setText(self.tr("Extend Selection →→"))
        # Restore editors to current segment only
        self.update_subtitle_display()
        self.show_current_segment_in_adjuster()
        self.update_debug()

    # === Search Features ===
    def run_search(self):
        raw_value = self.search_input.text()
        term = (raw_value or "").strip()
        if not term:
            self._message(
                QMessageBox.Icon.Warning,
                self.tr("Empty Search"),
                self.tr("Please enter a search term."),
            )
            return

        norm_term = self._normalize_for_search(term)
        if not norm_term:
            self._message(
                QMessageBox.Icon.Warning,
                self.tr("Empty Search"),
                self.tr("Please enter a search term."),
            )
            return

        self.search_matches = []
        self._search_match_sources = {}
        self._search_term_raw = term
        self._search_term_norm = norm_term

        for i, entry in enumerate(self.orig_entries):
            sources: set[str] = set()

            if self._has_search_match(entry.text, term, norm_term):
                sources.add("orig")

            trans_text = ""
            if i < len(self.trans_entries):
                trans_text = self.trans_entries[i].text
            if self._has_search_match(trans_text, term, norm_term):
                sources.add("trans")

            if sources:
                self.search_matches.append(i)
                self._search_match_sources[i] = sources

        if not self.search_matches:
            self._message(
                QMessageBox.Icon.Information,
                self.tr("No Results"),
                self.tr("No matches for '{term}'.").format(term=term),
            )
            self.search_btn.setText(self.tr("Search"))
            self.search_counter.setText("")
            return

        self.search_index = 0
        self.search_total = len(self.search_matches)
        self.search_btn.setText(self.tr("Next Match"))
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
        self._apply_search_highlight(idx)
        # Update counter before incrementing the index
        try:
            current_pos = self.search_index + 1
            total = getattr(self, 'search_total', len(self.search_matches))
            raw_sources = sorted(self._search_match_sources.get(idx, []))
            label_map = {
                "orig": self.tr("original"),
                "trans": self.tr("translation"),
            }
            match_sources = ", ".join(label_map.get(src, src) for src in raw_sources)
            if match_sources:
                self.search_counter.setText(
                    self.tr("{current} of {total} ({source})").format(
                        current=current_pos,
                        total=total,
                        source=match_sources,
                    )
                )
            else:
                self.search_counter.setText(
                    self.tr("{current} of {total}").format(current=current_pos, total=total)
                )
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
        self._search_match_sources = {}
        self._search_term_raw = ""
        self._search_term_norm = ""
        if hasattr(self, 'search_btn'):
            self.search_btn.setText(self.tr("Search"))
        if hasattr(self, 'search_counter'):
            self.search_counter.setText("")
        self._clear_search_highlight()
        self.cancel_extend_selection()
        self.update_debug()

    def next_match(self):
        self.jump_to_match()

    @staticmethod
    def _normalize_for_search(text: str | None) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKC", text)
        normalized = normalized.lower()
        normalized = re.sub(r"[\W_]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _has_search_match(self, text: str | None, term: str, norm_term: str) -> bool:
        if not text:
            return False
        if self._find_case_insensitive(text, term) != -1:
            # direct substring match (case-insensitive)
            return True

        if not norm_term:
            return False
        normalized = self._normalize_for_search(text)
        if not normalized:
            return False
        tokens = normalized.split(" ")
        return norm_term in tokens

    @staticmethod
    def _find_case_insensitive(haystack: str, needle: str) -> int:
        if not haystack or not needle:
            return -1
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        match = pattern.search(haystack)
        return match.start() if match else -1

    def _clear_search_highlight(self) -> None:
        try:
            self.orig_input.deselect()
        except Exception:
            pass
        try:
            cursor = self.trans_editor.textCursor()
            cursor.clearSelection()
            self.trans_editor.setTextCursor(cursor)
        except Exception:
            pass

    def _apply_search_highlight(self, idx: int) -> None:
        self._clear_search_highlight()
        term = (self._search_term_raw or "").strip()
        if not term:
            return
        sources = self._search_match_sources.get(idx, set())
        if "orig" in sources:
            text = self.orig_input.text()
            pos = self._find_case_insensitive(text, term)
            if pos != -1:
                try:
                    self.orig_input.setSelection(pos, len(term))
                except Exception:
                    pass
        if "trans" in sources:
            plain = self.trans_editor.toPlainText()
            pos = self._find_case_insensitive(plain, term)
            if pos != -1:
                try:
                    cursor = self.trans_editor.textCursor()
                    cursor.setPosition(pos)
                    cursor.setPosition(pos + len(term), QTextCursor.MoveMode.KeepAnchor)
                    self.trans_editor.setTextCursor(cursor)
                    self.trans_editor.ensureCursorVisible()
                except Exception:
                    pass

    def _update_selected_word(self) -> None:
        if not hasattr(self, "vocab_word_display"):
            return
        try:
            selected = self.orig_input.selectedText()
        except Exception:
            selected = ""
        selected = (selected or "").strip()
        self.vocab_word_display.setText(selected)

    def _update_translate_button_state(self) -> None:
        if not hasattr(self, "translate_button"):
            return
        text_present = bool((self.orig_input.text() or "").strip())
        enabled = text_present and self._translator_is_available()
        self.translate_button.setEnabled(enabled)
        if not enabled and Translator is None:
            self.translate_button.setToolTip(
                self.tr("Translation library not installed. Install googletrans to enable.")
            )
        elif not enabled and self._translator_unavailable:
            self.translate_button.setToolTip(
                self.tr("Translation service unavailable. Try again later.")
            )
        else:
            self.translate_button.setToolTip("")

    def _translator_is_available(self) -> bool:
        return Translator is not None and not getattr(self, "_translator_unavailable", False)

    def _get_translator(self):
        if not self._translator_is_available():
            return None
        if self._translator_instance is None:
            try:
                self._translator_instance = Translator()
            except Exception:
                self._translator_unavailable = True
                return None
        return self._translator_instance

    def _mark_vocab_modified(self) -> None:
        self.card_created_for_current_segment = False
        self.set_create_button_enabled(True)

    def _handle_translate_request(self) -> None:
        sentence = (self.orig_input.text() or "").strip()
        if not sentence:
            self._message(
                QMessageBox.Icon.Information,
                self.tr("No Text"),
                self.tr("Enter or load subtitle text before requesting a translation."),
            )
            return

        translated_sentence = self._translate_text(sentence)
        if translated_sentence:
            current_translation = self.trans_editor.toPlainText().strip()
            if not current_translation:
                self.trans_editor.setPlainText(translated_sentence)
        else:
            self._message(
                QMessageBox.Icon.Warning,
                self.tr("Translation Failed"),
                self.tr("Could not reach the translation service. Please try again later."),
            )
            return

        selected_word = self.vocab_word_display.text().strip()
        if selected_word:
            translated_word = self._translate_text(selected_word, single_word=True)
            if translated_word:
                self.vocab_output_edit.setPlainText(translated_word)
        else:
            # Preserve existing vocabulary notes if user has already written them.
            if not self.vocab_output_edit.toPlainText().strip():
                self.vocab_output_edit.setPlainText(translated_sentence)

        self._mark_vocab_modified()

    def _translate_text(self, text: str, single_word: bool = False) -> str | None:
        if not text:
            return None
        translator = self._get_translator()
        if not translator:
            return None
        try:
            detection = translator.detect(text)
            src = detection.lang if detection and detection.lang else "auto"
        except Exception:
            src = "auto"

        target = "en"
        if src == target:
            return text

        try:
            result = translator.translate(text, src=src, dest=target)
            return result.text
        except Exception:
            self._translator_unavailable = True
            self._update_translate_button_state()
            return None

    def _align_translation_entries(
        self,
        orig_entries: list[SubtitleEntry],
        trans_entries: list[SubtitleEntry],
        tolerance: float = 2.0,
    ) -> list[SubtitleEntry]:
        aligned: list[SubtitleEntry] = []
        j = 0
        used: set[int] = set()
        n = len(trans_entries)

        for orig in orig_entries:
            best_idx = -1
            best_delta = float("inf")

            # Advance pointer beyond clearly mismatched entries
            while j < n and trans_entries[j].start_time < orig.start_time - tolerance:
                j += 1

            candidates = []
            if j < n:
                candidates.append(j)
            if j - 1 >= 0:
                candidates.append(j - 1)

            for idx in candidates:
                if idx in used:
                    continue
                delta = abs(trans_entries[idx].start_time - orig.start_time)
                if delta <= tolerance and delta < best_delta:
                    best_delta = delta
                    best_idx = idx

            if best_idx != -1:
                used.add(best_idx)
                if best_idx >= j:
                    j = best_idx + 1
                match = trans_entries[best_idx]
                aligned.append(
                    SubtitleEntry(
                        index=orig.index,
                        start_time=orig.start_time,
                        end_time=orig.end_time,
                        text=match.text,
                    )
                )
            else:
                aligned.append(
                    SubtitleEntry(
                        index=orig.index,
                        start_time=orig.start_time,
                        end_time=orig.end_time,
                        text="",
                    )
                )

        return aligned

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
                        self.tr("Anki Not Running"),
                        self.tr("Anki with the Anki-Connect add-on must be running."),
                    )
                    return
            else:
                # Fallback ping
                anki._invoke("version")
        except Exception:
            self._message(
                QMessageBox.Icon.Warning,
                self.tr("Anki Not Running"),
                self.tr("Anki with the Anki-Connect add-on must be running."),
            )
            return

        # 2) Prevent double-create for the same segment
        if self.card_created_for_current_segment:
            self._message(
                QMessageBox.Icon.Information,
                self.tr("Already Created"),
                self.tr(
                    "An Anki card has already been created for this segment. Play to a new segment to enable the button."
                ),
            )
            return

        # 3) Gather data
        # Make sure we capture any in-place edits before creating the card
        self.save_current_edits()

        if not self.orig_entries:
            self._message(
                QMessageBox.Icon.Warning,
                self.tr("No Subtitle Data"),
                self.tr("Load subtitles before creating an Anki card."),
            )
            return

        if self.current_index >= len(self.orig_entries):
            self.current_index = max(0, len(self.orig_entries) - 1)

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
        vocab_word = (self.vocab_word_display.text() or "").strip() if hasattr(self, "vocab_word_display") else ""
        vocab_notes = (
            self.vocab_output_edit.toPlainText().strip()
            if hasattr(self, "vocab_output_edit")
            else ""
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
            back_html = (
                format_markdown(md_current) if md_current else self.tr("(no translation)")
            )
            if source_text:
                back_html = (
                    back_html
                    + self.tr(
                        "<div style=\"margin-top:8px;color:#666;\"><em>Source: {source}</em></div>"
                    ).format(source=source_text)
                )

            if vocab_word or vocab_notes:
                vocab_html = ""
                if vocab_notes:
                    vocab_html = format_markdown(vocab_notes)
                else:
                    vocab_html = self.tr("(translation pending)")
                vocab_block = self.tr(
                    "<div style=\"margin-top:8px;padding:8px;border:1px solid #e0e0e0; border-radius:6px;\">"
                    "<strong>{header}</strong><br/>"
                    "<span style=\"color:#3565B1;\">{word}</span><div>{notes}</div>"
                    "</div>"
                ).format(
                    header=self.tr("Vocabulary"),
                    word=vocab_word or self.tr("(word not selected)"),
                    notes=vocab_html,
                )
                back_html += vocab_block

            anki.add_note(
                self.orig_input.text().strip() or current_entry.text,
                back_html,
                clip_path,
                deck_name=deck_name,
                tags=raw_tags,
            )

            # Determine if we should advance beyond the extended selection once the
            # card is created. Only applies when the extend button was used.
            advance_to_index = None
            if (
                getattr(self, "extend_active", False)
                and self.extend_end_index is not None
            ):
                candidate = self.extend_end_index + 1
                if candidate < len(self.orig_entries):
                    advance_to_index = candidate

            # Success UI + state
            # Friendly message shows combined segment indices when extended
            if getattr(self, "extend_active", False) and self.extend_end_index is not None:
                base_idx = self.extend_base_index if self.extend_base_index is not None else self.current_index
                end_idx = self.extend_end_index
                segs = "+".join(str(i + 1) for i in range(base_idx, end_idx + 1))
                msg = self.tr("Anki card created for segments {segments} in deck '{deck}'.").format(
                    segments=segs, deck=deck_name
                )
            else:
                msg = self.tr("Anki card created for segment {segment} in deck '{deck}'.").format(
                    segment=self.current_index + 1, deck=deck_name
                )
            self._message(QMessageBox.Icon.Information, self.tr("Card Created"), msg)
            self.card_created_for_current_segment = True
            self.set_create_button_enabled(False)
            # Exit extended mode after successful creation
            self.cancel_extend_selection()

            if advance_to_index is not None:
                self.current_index = advance_to_index
                self.jump_to_current_subtitle_and_play()
            else:
                # cancel_extend_selection() refreshes the UI and re-enables the button;
                # restore the "already created" guard when we stay on the same segment.
                self.card_created_for_current_segment = True
                self.set_create_button_enabled(False)

        except Exception as e:
            self._message(
                QMessageBox.Icon.Critical,
                self.tr("Anki Error"),
                self.tr("Failed to create Anki card: {error}. Ensure Anki and the Anki-Connect add-on are running.").format(
                    error=e
                ),
            )
try:
    from googletrans import Translator  # type: ignore
except ImportError:
    Translator = None
