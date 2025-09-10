# anki_slicer/segment_adjuster.py
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtMultimedia import QMediaPlayer
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pydub import AudioSegment
import numpy as np
import os


class SegmentAdjusterWidget(QWidget):
    """
    A waveform viewer/editor for fine-tuning a selected audio segment.

    - Displays waveform with ±1s context around the selection.
    - Highlights the selected segment.
    - Left +/- adjust the start; Right +/- adjust the end.
    - After 500ms of inactivity following button clicks, plays a preview of the adjusted segment.
    - Uses an existing QMediaPlayer to preview and pauses at the adjusted end automatically.
    """

    def __init__(
        self,
        audio_path: str,
        player: QMediaPlayer,
        step_seconds: float = 0.1,
        min_length_seconds: float = 0.2,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.audio_path = audio_path
        self.player = player
        self.step = step_seconds
        self.min_len = min_length_seconds

        # Load full audio once
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")
        self.audio_seg = AudioSegment.from_file(audio_path)
        self.duration_sec = len(self.audio_seg) / 1000.0

        # State
        self.adjusted_start = 0.0
        self.adjusted_end = 0.0
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(500)  # 0.5s delay before preview
        self.preview_timer.timeout.connect(self._play_preview)

        # Track preview to auto-pause at end
        self._preview_active = False
        self._preview_target_end_ms = 0
        # Connect once to player's positionChanged for stopping preview
        self.player.positionChanged.connect(self._on_player_position_changed)

        self._build_ui()
        self._redraw_waveform()

    def _build_ui(self):
        root = QHBoxLayout(self)

        # Left controls (adjust start)
        left_col = QVBoxLayout()
        btn_start_plus = QPushButton("+")
        btn_start_minus = QPushButton("-")
        btn_start_plus.setToolTip("Expand at beginning (move start earlier)")
        btn_start_minus.setToolTip("Contract at beginning (move start later)")
        btn_start_plus.clicked.connect(lambda: self._nudge_start(-self.step))
        btn_start_minus.clicked.connect(lambda: self._nudge_start(+self.step))
        left_col.addWidget(btn_start_plus)
        left_col.addWidget(btn_start_minus)
        left_col.addStretch(1)

        # Right controls (adjust end)
        right_col = QVBoxLayout()
        btn_end_plus = QPushButton("+")
        btn_end_minus = QPushButton("-")
        btn_end_plus.setToolTip("Expand at end (move end later)")
        btn_end_minus.setToolTip("Contract at end (move end earlier)")
        btn_end_plus.clicked.connect(lambda: self._nudge_end(+self.step))
        btn_end_minus.clicked.connect(lambda: self._nudge_end(-self.step))
        right_col.addWidget(btn_end_plus)
        right_col.addWidget(btn_end_minus)
        right_col.addStretch(1)

        # Center: waveform canvas + label
        center_col = QVBoxLayout()
        self.info_label = QLabel("Selection: 0.00s → 0.00s")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fig = Figure(figsize=(6, 2.2), tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)

        center_col.addWidget(self.info_label)
        center_col.addWidget(self.canvas, stretch=1)

        root.addLayout(left_col)
        root.addLayout(center_col, stretch=1)
        root.addLayout(right_col)

        self.setLayout(root)

    # Public API

    def set_segment(self, start_sec: float, end_sec: float):
        """Set the current selection (seconds)."""
        start_sec = max(0.0, min(start_sec, self.duration_sec))
        end_sec = max(0.0, min(end_sec, self.duration_sec))
        if end_sec < start_sec:
            start_sec, end_sec = end_sec, start_sec

        # Enforce minimum length
        if end_sec - start_sec < self.min_len:
            end_sec = min(start_sec + self.min_len, self.duration_sec)
            if end_sec - start_sec < self.min_len:
                # audio too short; clamp start backward if possible
                start_sec = max(0.0, end_sec - self.min_len)

        self.adjusted_start = start_sec
        self.adjusted_end = end_sec
        self._update_info()
        self._redraw_waveform()

    def get_adjusted_segment(self) -> tuple[float, float]:
        return self.adjusted_start, self.adjusted_end

    # Internal: adjustments

    def _nudge_start(self, delta: float):
        # delta negative = move earlier; positive = move later
        new_start = self.adjusted_start + delta
        new_start = max(0.0, min(new_start, self.adjusted_end - self.min_len))
        self.adjusted_start = new_start
        self._update_info()
        self._redraw_waveform()
        self._schedule_preview()

    def _nudge_end(self, delta: float):
        # delta positive = move later; negative = move earlier
        new_end = self.adjusted_end + delta
        new_end = min(
            self.duration_sec, max(new_end, self.adjusted_start + self.min_len)
        )
        self.adjusted_end = new_end
        self._update_info()
        self._redraw_waveform()
        self._schedule_preview()

    def _update_info(self):
        self.info_label.setText(
            f"Selection: {self.adjusted_start:.2f}s → {self.adjusted_end:.2f}s  (len {self.adjusted_end - self.adjusted_start:.2f}s)"
        )

    # Preview playback

    def _schedule_preview(self):
        # restart the timer to allow multiple quick clicks before playing
        self.preview_timer.stop()
        self.preview_timer.start()

    def _play_preview(self):
        # set position and play until adjusted_end, then pause automatically
        start_ms = int(self.adjusted_start * 1000)
        end_ms = int(self.adjusted_end * 1000)
        self._preview_target_end_ms = end_ms
        self._preview_active = True

        # Always pause and reposition before playing preview
        self.player.pause()
        self.player.setPosition(start_ms)
        self.player.play()

    def _on_player_position_changed(self, pos_ms: int):
        if self._preview_active and pos_ms >= self._preview_target_end_ms:
            # Stop preview exactly at the end
            self.player.pause()
            self._preview_active = False

    # Waveform drawing

    def _redraw_waveform(self):
        # Compute context window ±1s
        ctx_start = max(0.0, self.adjusted_start - 1.0)
        ctx_end = min(self.duration_sec, self.adjusted_end + 1.0)
        ms1 = int(ctx_start * 1000)
        ms2 = int(ctx_end * 1000)
        if ms2 <= ms1:
            ms2 = ms1 + 1

        seg = self.audio_seg[ms1:ms2]
        samples = np.array(seg.get_array_of_samples())
        if seg.channels == 2:
            samples = samples.reshape((-1, 2)).mean(axis=1)

        # Normalize
        peak = float(1 << (8 * seg.sample_width - 1))
        y = samples / peak if peak > 0 else samples.astype(np.float32)
        x = np.linspace(ctx_start, ctx_end, num=y.shape[0], endpoint=False)

        self.ax.clear()
        self.ax.plot(x, y, color="#3b82f6", linewidth=0.8)
        # Highlight adjusted selection
        self.ax.axvspan(
            self.adjusted_start, self.adjusted_end, color="#f59e0b", alpha=0.35
        )
        self.ax.set_xlim(ctx_start, ctx_end)
        self.ax.set_ylim(-1.0, 1.0)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_yticks([])
        self.ax.grid(True, alpha=0.15)
        self.canvas.draw_idle()
