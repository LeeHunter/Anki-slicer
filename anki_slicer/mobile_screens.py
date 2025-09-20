"""Mobile workflow screens for the YouTube feature branch.

Provides PySide6 widgets that mirror the mobile mockups and expose hooks so
controller logic can attach live playback, waveform, and translation data.
"""

from __future__ import annotations

import logging
import os
import tempfile

from PySide6.QtCore import Qt, QSize, Signal, QTimer, QEvent, QUrl
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QLabel,
    QPushButton,
    QSlider,
    QCheckBox,
    QTextEdit,
    QLineEdit,
    QFrame,
    QSizePolicy,
    QSpacerItem,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .segment_adjuster import SegmentAdjusterWidget
from .youtube.embed_view import YouTubeEmbedView
from .subs import SubtitleEntry


logger = logging.getLogger(__name__)


class MobileMainScreen(QWidget):
    """Primary screen for loading media, slicing, and jumping to preview."""

    previewRequested = Signal()
    settingsRequested = Signal()
    loadRequested = Signal()
    forwardNudge = Signal()
    backNudge = Signal()
    autoPauseToggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mobileMainScreen")
        self.setStyleSheet("background-color: #3a1c1c; color: #f4f0f0;")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Top row: Settings / Load controls
        top_row = QHBoxLayout()
        self.settings_button = QPushButton(self.tr("Settings"))
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.clicked.connect(self.settingsRequested)
        self.load_button = QPushButton(self.tr("Load"))
        self.load_button.setObjectName("loadButton")
        self.load_button.clicked.connect(self.loadRequested)
        top_row.addWidget(self.settings_button)
        top_row.addStretch(1)
        top_row.addWidget(self.load_button)
        root.addLayout(top_row)

        # Video area container (placeholder until controller attaches embed)
        self.video_container = QFrame()
        self.video_container.setObjectName("videoContainer")
        self.video_container.setStyleSheet(
            "background-color: #1f1b1b; border-radius: 8px;"
        )
        self.video_container.setFixedHeight(180)
        self._video_layout = QVBoxLayout(self.video_container)
        self._video_layout.setContentsMargins(0, 0, 0, 0)
        self._video_layout.setSpacing(0)
        self.video_placeholder = QLabel(self.tr("Video Preview"))
        self.video_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_placeholder.setObjectName("videoPlaceholder")
        self._video_layout.addWidget(self.video_placeholder)
        root.addWidget(self.video_container)

        # Playback slider row
        slider_row = QVBoxLayout()
        self.playback_slider = QSlider(Qt.Orientation.Horizontal)
        self.playback_slider.setObjectName("playbackSlider")
        slider_row.addWidget(self.playback_slider)

        slider_meta = QHBoxLayout()
        slider_meta.addStretch(1)
        self.timestamp_label = QLabel("0:00 / 0:00")
        self.timestamp_label.setObjectName("timestampLabel")
        slider_meta.addWidget(self.timestamp_label)
        slider_row.addLayout(slider_meta)
        root.addLayout(slider_row)

        # Transport controls
        transport_row = QHBoxLayout()
        self.forward_button = QPushButton(self.tr("Forward"))
        self.forward_button.setObjectName("forwardButton")
        self.forward_button.clicked.connect(self.forwardNudge)
        self.back_button = QPushButton(self.tr("Back"))
        self.back_button.setObjectName("backButton")
        self.back_button.clicked.connect(self.backNudge)
        self.auto_pause_button = QPushButton(self.tr("Auto Pause"))
        self.auto_pause_button.setCheckable(True)
        self.auto_pause_button.setObjectName("autoPauseButton")
        self.auto_pause_button.toggled.connect(self.autoPauseToggled)

        for btn in (self.forward_button, self.back_button, self.auto_pause_button):
            btn.setMinimumHeight(36)

        transport_row.addWidget(self.forward_button)
        transport_row.addWidget(self.back_button)
        transport_row.addWidget(self.auto_pause_button)
        root.addLayout(transport_row)

        # Waveform widget with trim handles
        waveform_container = QVBoxLayout()
        self.waveform_view = SegmentAdjusterWidget()
        self.waveform_view.setObjectName("waveformView")
        waveform_container.addWidget(self.waveform_view)

        waveform_controls = QHBoxLayout()
        self.trim_shrink_left = QPushButton("-")
        self.trim_grow_left = QPushButton("+")
        self.extend_button = QPushButton(self.tr("Extend -> ->"))
        self.trim_shrink_right = QPushButton("-")
        self.trim_grow_right = QPushButton("+")
        for btn in (
            self.trim_shrink_left,
            self.trim_grow_left,
            self.extend_button,
            self.trim_shrink_right,
            self.trim_grow_right,
        ):
            btn.setMinimumWidth(48)

        waveform_controls.addWidget(self.trim_shrink_left)
        waveform_controls.addWidget(self.trim_grow_left)
        waveform_controls.addWidget(self.extend_button)
        waveform_controls.addWidget(self.trim_shrink_right)
        waveform_controls.addWidget(self.trim_grow_right)
        waveform_container.addLayout(waveform_controls)
        root.addLayout(waveform_container)

        # Text preview labels
        self.original_text_label = QLabel(
            self.tr("This is how the original text will be displayed on the screen.")
        )
        self.original_text_label.setWordWrap(True)
        self.original_text_label.setObjectName("originalTextLabel")
        try:
            self.original_text_label.setTextFormat(Qt.TextFormat.PlainText)
        except Exception:
            pass
        root.addWidget(self.original_text_label)

        self.translation_label = QLabel(
            self.tr("Así es como se mostrará el texto traducido en la pantalla.")
        )
        self.translation_label.setWordWrap(True)
        self.translation_label.setObjectName("translationLabel")
        try:
            self.translation_label.setTextFormat(Qt.TextFormat.PlainText)
        except Exception:
            pass
        root.addWidget(self.translation_label)

        root.addItem(QSpacerItem(0, 16, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Preview navigation
        self.preview_button = QPushButton(self.tr("Preview"))
        self.preview_button.setObjectName("previewButton")
        self.preview_button.setMinimumHeight(40)
        self.preview_button.clicked.connect(self.previewRequested)
        root.addWidget(self.preview_button)

    # ------------------------------------------------------------------
    def attach_default_video_view(self) -> YouTubeEmbedView:
        """Create a YouTube embed view if none is attached and return it."""

        existing = self.video_widget()
        if isinstance(existing, YouTubeEmbedView):
            return existing

        view = YouTubeEmbedView(self)
        self.set_video_widget(view)
        return view

    def set_video_widget(self, widget: QWidget | None) -> None:
        """Replace the video area contents with the provided widget."""

        while self._video_layout.count():
            child = self._video_layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.setParent(None)

        if widget is None:
            self._video_layout.addWidget(self.video_placeholder)
        else:
            self._video_layout.addWidget(widget)

    def video_widget(self) -> QWidget | None:
        """Return the currently displayed video widget (if any)."""

        if self._video_layout.count() == 0:
            return None
        item = self._video_layout.itemAt(0)
        return item.widget() if item else None


class MobilePreviewScreen(QWidget):
    """Second screen where users adjust metadata before exporting to Anki."""

    exportRequested = Signal()
    cancelRequested = Signal()
    translateRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mobilePreviewScreen")
        self.setStyleSheet("background-color: #3a1c1c; color: #f4f0f0;")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Video snapshot placeholder + include image toggle
        self.preview_video_placeholder = QLabel(self.tr("Preview Frame"))
        self.preview_video_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_video_placeholder.setFixedHeight(180)
        self.preview_video_placeholder.setStyleSheet(
            "background-color: #1f1b1b; border-radius: 8px;"
        )
        self.preview_video_placeholder.setObjectName("previewVideoPlaceholder")
        root.addWidget(self.preview_video_placeholder)

        self.include_image_checkbox = QCheckBox(self.tr("Include image"))
        self.include_image_checkbox.setObjectName("includeImageCheckbox")
        root.addWidget(self.include_image_checkbox)

        # Instructional copy
        self.instructions_label = QLabel(
            self.tr("Select a word to designate as the vocabulary target.")
        )
        self.instructions_label.setObjectName("instructionsLabel")
        self.instructions_label.setStyleSheet("color: #f7c35a;")
        self.instructions_label.setWordWrap(True)
        root.addWidget(self.instructions_label)

        self.original_text_preview = QLabel(
            self.tr("This represents the original text. This represents the original text.")
        )
        self.original_text_preview.setWordWrap(True)
        self.original_text_preview.setObjectName("previewOriginalText")
        try:
            self.original_text_preview.setTextFormat(Qt.TextFormat.PlainText)
        except Exception:
            pass
        root.addWidget(self.original_text_preview)

        self.translation_edit = QTextEdit()
        self.translation_edit.setObjectName("translationEdit")
        try:
            self.translation_edit.setAcceptRichText(False)
            self.translation_edit.setTabChangesFocus(True)
        except Exception:
            pass
        self.translation_edit.setPlaceholderText(
            self.tr("Así es como se mostrará el texto traducido en la pantalla.")
        )
        self.translation_edit.setMinimumHeight(100)
        root.addWidget(self.translation_edit)

        self.translate_button = QPushButton(self.tr("Translate/Retranslate"))
        self.translate_button.setObjectName("translateButton")
        self.translate_button.clicked.connect(self.translateRequested)
        root.addWidget(self.translate_button)

        # Metadata entry fields
        self.vocabulary_field = QLineEdit()
        self.vocabulary_field.setObjectName("vocabularyField")
        self.vocabulary_field.setPlaceholderText(self.tr("Vocabulary"))

        self.deck_field = QLineEdit()
        self.deck_field.setObjectName("deckField")
        self.deck_field.setPlaceholderText(self.tr("Anki Deck"))

        self.tags_field = QLineEdit()
        self.tags_field.setObjectName("tagsField")
        self.tags_field.setPlaceholderText(self.tr("Tags"))

        for line_edit in (self.vocabulary_field, self.deck_field, self.tags_field):
            line_edit.setMinimumHeight(34)
            root.addWidget(line_edit)

        root.addItem(QSpacerItem(0, 12, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Footer controls
        footer = QHBoxLayout()
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.cancelRequested)

        footer.addWidget(self.cancel_button)
        footer.addStretch(1)

        self.export_button = QPushButton(self.tr("Export to Anki"))
        self.export_button.setObjectName("exportButton")
        self.export_button.setMinimumSize(QSize(140, 40))
        self.export_button.clicked.connect(self.exportRequested)
        footer.addWidget(self.export_button)

        root.addLayout(footer)


class MobileWorkflowWindow(QWidget):
    """Container window that swaps between screens and drives playback."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mobileWorkflowWindow")
        self.setWindowTitle(self.tr("Anki-Slicer Mobile"))
        self.setMinimumSize(360, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.main_screen = MobileMainScreen()
        self.preview_screen = MobilePreviewScreen()

        self.stack.addWidget(self.main_screen)
        self.stack.addWidget(self.preview_screen)
        root.addWidget(self.stack)

        # Playback components
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)

        # Slider configuration
        self.main_screen.playback_slider.setRange(0, 1000)
        self.main_screen.playback_slider.setEnabled(False)

        # Internal state
        self.orig_entries: list[SubtitleEntry] = []
        self.trans_entries: list[SubtitleEntry] = []
        self.trans_overrides: dict[int, str] = {}
        self.current_index = 0
        self.MARGIN_SEC = 1.0
        self.auto_pause_enabled = False
        self._auto_pause_armed = False
        self._slider_active = False
        self._updating_preview_translation = False

        self._ephemeral_audio_paths: set[str] = set()
        self._active_audio_path: str | None = None

        # Attach embedded video surface
        self.youtube_view = self.main_screen.attach_default_video_view()

        # Wire UI interactions
        ms = self.main_screen
        ms.forwardNudge.connect(self.next_segment)
        ms.backNudge.connect(self.previous_segment)
        ms.autoPauseToggled.connect(self._on_auto_pause_toggled)
        ms.playback_slider.sliderPressed.connect(self._slider_pressed)
        ms.playback_slider.sliderReleased.connect(self._slider_released)
        ms.playback_slider.sliderMoved.connect(self._slider_moved)
        ms.trim_shrink_left.clicked.connect(lambda: self._adjust_selection("start", +0.05))
        ms.trim_grow_left.clicked.connect(lambda: self._adjust_selection("start", -0.05))
        ms.trim_shrink_right.clicked.connect(lambda: self._adjust_selection("end", -0.05))
        ms.trim_grow_right.clicked.connect(lambda: self._adjust_selection("end", +0.05))
        ms.extend_button.clicked.connect(self._extend_selection)
        ms.waveform_view.installEventFilter(self)

        self.main_screen.previewRequested.connect(self._handle_preview_request)

        ps = self.preview_screen
        ps.cancelRequested.connect(self.show_main)
        ps.translation_edit.textChanged.connect(self._on_preview_translation_changed)

    # ------------------------------------------------------------------
    # Public API
    def load_media(
        self,
        *,
        audio_path: str,
        original_subs: list[SubtitleEntry],
        translation_subs: list[SubtitleEntry] | None = None,
        treat_audio_as_ephemeral: bool = False,
        convert_if_needed: bool = True,
    ) -> None:
        """Load local media plus subtitle entries into the workflow."""

        self.orig_entries = list(original_subs)
        self.trans_entries = list(translation_subs or [])
        self.trans_overrides.clear()
        self.current_index = 0

        self._load_audio(
            audio_path,
            treat_as_ephemeral=treat_audio_as_ephemeral,
            convert_if_needed=convert_if_needed,
        )
        self._update_segment_context(play=False)

    def load_youtube_video(self, video_id: str, *, autoplay: bool = False) -> None:
        """Render the requested YouTube clip in the embedded view."""

        self.youtube_view.load_video(video_id, autoplay=autoplay)

    def load_youtube_audio(self, video_id: str) -> None:
        """Fetch YouTube audio and prepare playback/waveform data."""

        from .youtube.audio import download_audio_as_wav

        wav_path = download_audio_as_wav(video_id)
        if not wav_path:
            logger.warning("Failed to download audio for %s", video_id)
            return
        self._ephemeral_audio_paths.add(wav_path)
        self._load_audio(wav_path, treat_as_ephemeral=True, convert_if_needed=False)

    # ------------------------------------------------------------------
    def show_preview(self) -> None:
        self.stack.setCurrentWidget(self.preview_screen)

    def show_main(self) -> None:
        self.stack.setCurrentWidget(self.main_screen)

    # ------------------------------------------------------------------
    def next_segment(self) -> None:
        if not self.orig_entries:
            return
        if self.current_index < len(self.orig_entries) - 1:
            self.current_index += 1
            self._update_segment_context(play=True)

    def previous_segment(self) -> None:
        if not self.orig_entries:
            return
        if self.current_index > 0:
            self.current_index -= 1
            self._update_segment_context(play=True)

    def play_current_segment(self) -> None:
        if not self.orig_entries:
            return
        start, _ = self._current_selection()
        self.player.setPosition(int(start * 1000))
        self._arm_auto_pause()
        self.player.play()

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # type: ignore[override]
        self._cleanup_ephemeral_audio()
        super().closeEvent(event)

    def eventFilter(self, obj, event):  # type: ignore[override]
        if obj is self.main_screen.waveform_view and event.type() in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.TouchEnd,
        ):
            if self.auto_pause_enabled:
                self._arm_auto_pause()
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    def _handle_preview_request(self) -> None:
        self._populate_preview_screen()
        self.show_preview()

    def _populate_preview_screen(self) -> None:
        orig_text = self._current_original_text()
        trans_text = self._current_translation_text()

        self.preview_screen.original_text_preview.setText(orig_text)
        self._updating_preview_translation = True
        self.preview_screen.translation_edit.setPlainText(trans_text)
        self._updating_preview_translation = False

    def _on_preview_translation_changed(self) -> None:
        if self._updating_preview_translation:
            return
        text = self.preview_screen.translation_edit.toPlainText().strip()
        if text:
            self.trans_overrides[self.current_index] = text
        else:
            self.trans_overrides.pop(self.current_index, None)
        self._refresh_translation_label()

    # ------------------------------------------------------------------
    def _load_audio(
        self,
        path: str,
        *,
        treat_as_ephemeral: bool,
        convert_if_needed: bool,
    ) -> None:
        self._release_active_audio()

        target_path = path
        ephemeral = treat_as_ephemeral

        if convert_if_needed and not path.lower().endswith(".wav"):
            try:
                target_path = self._convert_audio_to_wav(path)
                ephemeral = True
            except Exception as exc:
                logger.warning("Falling back to original audio %s: %s", path, exc)
                target_path = path
                ephemeral = treat_as_ephemeral

        if ephemeral:
            self._ephemeral_audio_paths.add(target_path)

        self._active_audio_path = target_path
        try:
            self.player.setSource(QUrl.fromLocalFile(target_path))
        except Exception as exc:
            logger.error("Unable to set audio source %s: %s", target_path, exc)
            return

        try:
            self.main_screen.waveform_view.load_waveform(target_path)
        except Exception as exc:
            logger.warning("Waveform failed for %s: %s", target_path, exc)

        self.player.setPosition(0)
        self.player.pause()
        self.main_screen.playback_slider.setEnabled(True)
        self._update_timestamp_label(0)

    def _convert_audio_to_wav(self, source_path: str) -> str:
        from pydub import AudioSegment

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.close()

        audio = AudioSegment.from_file(source_path)
        audio = audio.set_frame_rate(44100).set_channels(2)
        audio.export(tmp_path, format="wav")

        return tmp_path

    def _release_active_audio(self) -> None:
        if self._active_audio_path and self._active_audio_path in self._ephemeral_audio_paths:
            try:
                os.remove(self._active_audio_path)
            except Exception as exc:
                logger.debug("Failed removing temp audio %s: %s", self._active_audio_path, exc)
            self._ephemeral_audio_paths.discard(self._active_audio_path)
        self._active_audio_path = None

    def _cleanup_ephemeral_audio(self) -> None:
        self._release_active_audio()
        for path in list(self._ephemeral_audio_paths):
            try:
                os.remove(path)
            except Exception as exc:
                logger.debug("Late cleanup failure for %s: %s", path, exc)
            self._ephemeral_audio_paths.discard(path)

    # ------------------------------------------------------------------
    def _update_segment_context(self, *, play: bool) -> None:
        if not self.orig_entries:
            self._display_empty_state()
            return

        entry = self.orig_entries[self.current_index]
        raw_start = max(0.0, entry.start_time - self.MARGIN_SEC)
        raw_end = entry.end_time + self.MARGIN_SEC
        self.main_screen.waveform_view.set_bounds_and_selection(
            raw_start, raw_end, entry.start_time, entry.end_time
        )

        self._refresh_text_labels()
        self.player.setPosition(int(entry.start_time * 1000))
        self._update_timestamp_label(self.player.position())

        if play:
            self._arm_auto_pause()
            self.player.play()
        else:
            self.player.pause()

    def _display_empty_state(self) -> None:
        self.main_screen.original_text_label.setText(self.tr("No subtitles loaded."))
        self.main_screen.translation_label.setText("")
        self.preview_screen.original_text_preview.setText("")
        self.preview_screen.translation_edit.clear()
        self.main_screen.playback_slider.setEnabled(False)

    def _refresh_text_labels(self) -> None:
        orig_text = self._current_original_text()
        self.main_screen.original_text_label.setText(orig_text)
        self.preview_screen.original_text_preview.setText(orig_text)
        self._refresh_translation_label()

    def _refresh_translation_label(self) -> None:
        trans_text = self._current_translation_text()
        self.main_screen.translation_label.setText(trans_text)
        self._updating_preview_translation = True
        self.preview_screen.translation_edit.setPlainText(trans_text)
        self._updating_preview_translation = False

    def _current_original_text(self) -> str:
        if 0 <= self.current_index < len(self.orig_entries):
            return self.orig_entries[self.current_index].text
        return ""

    def _current_translation_text(self) -> str:
        if self.current_index in self.trans_overrides:
            return self.trans_overrides[self.current_index]
        if 0 <= self.current_index < len(self.trans_entries):
            return self.trans_entries[self.current_index].text
        return ""

    def _current_selection(self) -> tuple[float, float]:
        wf = self.main_screen.waveform_view
        return float(wf.adj_start), float(wf.adj_end)

    # ------------------------------------------------------------------
    def _on_position_changed(self, position_ms: int) -> None:
        if not self.main_screen.playback_slider.isEnabled():
            return

        if not self._slider_active:
            slider = self.main_screen.playback_slider
            duration = max(1, self.player.duration())
            value = int((position_ms / duration) * slider.maximum())
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)

        self._update_timestamp_label(position_ms)
        self._check_auto_pause(position_ms)

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.main_screen.playback_slider.setEnabled(duration_ms > 0)
        self._update_timestamp_label(self.player.position(), override_duration=duration_ms)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState and self.auto_pause_enabled:
            self._auto_pause_armed = True

    def _slider_pressed(self) -> None:
        self._slider_active = True

    def _slider_moved(self, value: int) -> None:
        if not self._slider_active:
            return
        duration = self.player.duration()
        if duration <= 0:
            return
        target_ms = int((value / self.main_screen.playback_slider.maximum()) * duration)
        self._update_timestamp_label(target_ms)

    def _slider_released(self) -> None:
        slider = self.main_screen.playback_slider
        duration = self.player.duration()
        if duration <= 0:
            self._slider_active = False
            return
        target_ms = int((slider.value() / slider.maximum()) * duration)
        self._slider_active = False
        self.player.setPosition(target_ms)
        self._arm_auto_pause()

    def _update_timestamp_label(self, current_ms: int, *, override_duration: int | None = None) -> None:
        duration_ms = override_duration if override_duration is not None else self.player.duration()
        if duration_ms < 0:
            duration_ms = 0
        text = f"{self._format_time(current_ms)} / {self._format_time(duration_ms)}"
        self.main_screen.timestamp_label.setText(text)

    @staticmethod
    def _format_time(ms: int) -> str:
        total_seconds = max(0, ms // 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _arm_auto_pause(self) -> None:
        if self.auto_pause_enabled:
            self._auto_pause_armed = True
        else:
            self._auto_pause_armed = False

    def _on_auto_pause_toggled(self, enabled: bool) -> None:
        self.auto_pause_enabled = enabled
        self._auto_pause_armed = enabled

    def _check_auto_pause(self, position_ms: int) -> None:
        if not self.auto_pause_enabled or not self._auto_pause_armed:
            return
        _, end = self._current_selection()
        if end <= 0:
            return
        if position_ms >= int(end * 1000):
            self._auto_pause_armed = False
            self.player.pause()

    def _adjust_selection(self, side: str, delta: float) -> None:
        wf = self.main_screen.waveform_view
        start = wf.adj_start
        end = wf.adj_end
        raw_start = wf.raw_start
        raw_end = wf.raw_end
        minimum = 0.05

        if side == "start":
            start = max(raw_start, min(start + delta, end - minimum))
        else:
            end = min(raw_end, max(start + minimum, end + delta))

        wf.set_bounds_and_selection(raw_start, raw_end, start, end)
        self._arm_auto_pause()

    def _extend_selection(self) -> None:
        wf = self.main_screen.waveform_view
        raw_start = wf.raw_start
        raw_end = wf.raw_end
        start = max(raw_start, wf.adj_start - 0.05)
        end = min(raw_end, wf.adj_end + 0.05)
        if end - start < 0.05:
            end = min(raw_end, start + 0.05)
        wf.set_bounds_and_selection(raw_start, raw_end, start, end)
        self._arm_auto_pause()
