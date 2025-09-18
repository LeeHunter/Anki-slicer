"""Utilities to download YouTube audio tracks for waveform analysis."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from yt_dlp import YoutubeDL
from pydub import AudioSegment

logger = logging.getLogger(__name__)


def download_audio_as_wav(video_id: str) -> Optional[str]:
    """Download the best available audio track and convert it to WAV.

    Returns
    -------
    Optional[str]
        Path to the temporary WAV file, or ``None`` if the download failed.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="anki_slicer_yt_audio_"))
    outtmpl = str(tmp_dir / f"{video_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "outtmpl": outtmpl,
        "noplaylist": True,
        "ignoreerrors": True,
    }

    url = f"https://www.youtube.com/watch?v={video_id}"
    downloaded_path: Optional[Path] = None

    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            if isinstance(result, dict):
                ext = result.get("ext", "m4a")
                downloaded_path = tmp_dir / f"{video_id}.{ext}"
    except Exception as exc:  # pragma: no cover - network/yt-dlp errors
        logger.warning("Failed to download audio for %s: %s", video_id, exc)
        return None

    if not downloaded_path or not downloaded_path.exists():
        logger.info("Audio file not created for video %s", video_id)
        return None

    try:
        audio = AudioSegment.from_file(downloaded_path)
        wav_path = tmp_dir / f"{video_id}.wav"
        audio.export(wav_path, format="wav")
    except Exception as exc:
        logger.warning("Failed to convert audio for %s to WAV: %s", video_id, exc)
        return None

    return str(wav_path)
