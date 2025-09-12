from typing import Optional
import numpy as np
from pydub import AudioSegment
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF


class SegmentAdjusterWidget(QWidget):
    def __init__(self, audio_path=None, player=None, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(160)
        self.setMaximumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.raw_start, self.raw_end = 0.0, 1.0
        self.adj_start, self.adj_end = 0.0, 1.0

        # Type annotations for static checkers
        self.waveform: Optional[np.ndarray] = None
        self.sample_rate: Optional[int] = None

        if audio_path:
            self.load_waveform(audio_path)

    def load_waveform(self, audio_path: str):
        """Precompute normalized waveform samples for drawing"""
        try:
            audio = AudioSegment.from_file(audio_path)
            samples = np.array(audio.get_array_of_samples()).astype(np.float32)

            # If stereo → convert to mono
            if audio.channels > 1:
                samples = samples.reshape((-1, audio.channels))
                samples = samples.mean(axis=1)

            # Normalize to [-1, 1]
            peak = float(np.max(np.abs(samples))) if samples.size > 0 else 0.0
            if peak > 0:
                samples /= peak

            self.waveform = samples
            self.sample_rate = int(audio.frame_rate)
        except Exception as e:
            print(f"Failed to load waveform: {e}")
            self.waveform = None
            self.sample_rate = None

    def set_bounds_and_selection(
        self, raw_start: float, raw_end: float, sel_start: float, sel_end: float
    ):
        """Set the expandable bounds and initial selection separately."""
        self.raw_start = float(min(raw_start, raw_end))
        self.raw_end = float(max(raw_start, raw_end))
        self.adj_start = max(self.raw_start, float(min(sel_start, sel_end)))
        self.adj_end = min(self.raw_end, float(max(sel_start, sel_end)))

        # Ensure at least a tiny width
        if self.adj_end - self.adj_start < 0.01:
            self.adj_end = min(self.raw_end, self.adj_start + 0.01)
        self.update()

    def set_segment(self, start_sec, end_sec):
        """Backward compatibility: bounds = selection (no margin)."""
        self.set_bounds_and_selection(start_sec, end_sec, start_sec, end_sec)

    def get_adjusted_segment(self):
        return (self.adj_start, self.adj_end)

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Clear background - light gray to distinguish widget
        painter.fillRect(self.rect(), QColor("#f0f0f0"))

        if self.waveform is None or self.raw_end <= self.raw_start:
            return

        w, h = self.width(), self.height()
        pad = 12
        track_rect = QRectF(pad, pad, w - 2 * pad, h - 2 * pad)

        # Draw waveform for the raw segment bounds
        self.draw_waveform(painter, track_rect)

        # Highlight adjusted region (semi-transparent overlay)
        adj_left = (
            track_rect.left()
            + (self.adj_start - self.raw_start)
            / (self.raw_end - self.raw_start)
            * track_rect.width()
        )
        adj_right = (
            track_rect.left()
            + (self.adj_end - self.raw_start)
            / (self.raw_end - self.raw_start)
            * track_rect.width()
        )
        highlight_rect = QRectF(
            adj_left,
            track_rect.top(),
            max(2.0, adj_right - adj_left),
            track_rect.height(),
        )

        painter.fillRect(highlight_rect, QColor(122, 166, 255, 100))  # translucent blue

        # Draw handles at adjusted start/end
        painter.setPen(QPen(QColor("#2f5aa8"), 2))
        painter.setBrush(QColor("#2f5aa8"))
        handle_w = 6
        painter.drawRect(
            QRectF(
                adj_left - handle_w / 2, track_rect.top(), handle_w, track_rect.height()
            )
        )
        painter.drawRect(
            QRectF(
                adj_right - handle_w / 2,
                track_rect.top(),
                handle_w,
                track_rect.height(),
            )
        )

        # Outline of the whole track
        painter.setPen(QPen(QColor("#b0b9c6")))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(track_rect, 8, 8)

    def draw_waveform(self, painter, track_rect):
        """Draw the actual waveform samples within track_rect."""
        wf = self.waveform
        sr = self.sample_rate

        # Static/runtime safety checks
        if wf is None or sr is None or sr <= 0:
            return

        # Convert time bounds to sample indices
        start_sample = max(0, int(self.raw_start * sr))
        end_sample = min(int(self.raw_end * sr), wf.shape[0])

        if end_sample <= start_sample:
            return

        chunk = wf[start_sample:end_sample]
        if chunk.size == 0:
            return

        # Downsample to fit widget width
        target_width = max(1, int(track_rect.width()))
        if chunk.shape[0] > target_width:
            step = max(1, chunk.shape[0] // target_width)
            chunk = chunk[::step]

        # Build waveform polyline
        poly = QPolygonF()
        center_y = track_rect.center().y()
        scale = track_rect.height() / 2.2  # leave some margin
        n = chunk.shape[0]

        for i in range(n):
            x = (
                track_rect.left() + (i / max(1, n - 1)) * track_rect.width()
                if n > 1
                else track_rect.left()
            )
            y = center_y - float(chunk[i]) * scale
            poly.append(QPointF(x, y))

        # Draw waveform
        painter.setPen(QPen(QColor("#2f5aa8"), 1))
        painter.drawPolyline(poly)
