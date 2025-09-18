"""Utilities for discovering and fetching YouTube caption tracks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

import requests
from yt_dlp import YoutubeDL

from anki_slicer.subs import SubtitleEntry

logger = logging.getLogger(__name__)


PREFERRED_FORMATS = ("json3",)


@dataclass
class TranscriptOption:
    """Represents a selectable caption track."""

    key: str
    label: str
    url: str
    language_code: str
    format: str
    is_generated: bool = False
    translation_code: Optional[str] = None
    source_language_code: Optional[str] = None


def list_transcript_options(video_id: str) -> List[TranscriptOption]:
    """Return caption options for the given YouTube video.

    The data is sourced via yt-dlp so we can rely on signed caption URLs and the
    modern ``json3`` format, which remains accessible even when the legacy
    timedtext endpoints return empty responses.
    """

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "noplaylist": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # pragma: no cover - network/yt-dlp errors
        logger.warning("Failed to list transcripts for %s: %s", video_id, exc)
        return []

    base_language = (info.get("language") or "").lower()
    options: List[TranscriptOption] = []
    seen_keys: set[str] = set()

    def add_option(
        *,
        key: str,
        label: str,
        track_url: str,
        lang_code: str,
        fmt: str,
        is_generated: bool,
        translation_code: Optional[str],
        source_lang: Optional[str],
    ) -> None:
        if not track_url or key in seen_keys:
            return
        options.append(
            TranscriptOption(
                key=key,
                label=label,
                url=track_url,
                language_code=lang_code,
                format=fmt,
                is_generated=is_generated,
                translation_code=translation_code,
                source_language_code=source_lang,
            )
        )
        seen_keys.add(key)

    def select_format(formats: List[dict]) -> Optional[dict]:
        for preferred in PREFERRED_FORMATS:
            for fmt in formats:
                if fmt.get("ext") == preferred:
                    return fmt
        return None

    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}

    manual_langs = list(subtitles.keys())
    auto_langs = list(automatic.keys())

    def match_language(codes: list[str], target: str) -> str:
        target = target.lower()
        for code in codes:
            if code.lower() == target:
                return code
        return ""

    def prefer_language(codes: list[str]) -> str:
        if not codes:
            return ""
        for code in codes:
            if not code.lower().startswith("en"):
                return code
        return codes[0]

    primary_lang = ""
    primary_from_auto = False

    if base_language:
        match = match_language(manual_langs, base_language)
        if match:
            primary_lang = match
        else:
            match = match_language(auto_langs, base_language)
            if match:
                primary_lang = match
                primary_from_auto = True

    if not primary_lang:
        if manual_langs:
            primary_lang = prefer_language(manual_langs)
        elif auto_langs:
            primary_lang = prefer_language(auto_langs)
            primary_from_auto = True

    original_langs: set[str] = set()
    primary_base = ""

    def remember_original(lang: str) -> None:
        if not lang:
            return
        lower = lang.lower()
        original_langs.add(lower)
        nonlocal primary_base
        primary_base = lower.split("-")[0]

    def add_original(lang_code: str, fmt: dict, is_generated: bool) -> None:
        label_name = fmt.get("name") or lang_code
        label = f"{label_name} ({lang_code})"
        if is_generated:
            label += " [auto]"
        mode = "auto" if is_generated else "manual"
        key = f"orig::{lang_code}::{mode}"
        add_option(
            key=key,
            label=label,
            track_url=fmt.get("url", ""),
            lang_code=lang_code,
            fmt=fmt.get("ext", "json3"),
            is_generated=is_generated,
            translation_code=None,
            source_lang=lang_code,
        )
        remember_original(lang_code)

    if primary_lang:
        if primary_from_auto:
            fmt = select_format(automatic.get(primary_lang, []))
            if fmt:
                add_original(primary_lang, fmt, True)
        else:
            fmt = select_format(subtitles.get(primary_lang, []))
            if fmt:
                add_original(primary_lang, fmt, False)

    if not original_langs:
        for lang_code, formats in subtitles.items():
            fmt = select_format(formats)
            if fmt:
                add_original(lang_code, fmt, False)
                break
        if not original_langs:
            for lang_code, formats in automatic.items():
                fmt = select_format(formats)
                if fmt:
                    add_original(lang_code, fmt, True)
                    break

    source_lang_for_trans = next(iter(original_langs), base_language or "orig")

    def should_skip_translation(lang_code: str) -> bool:
        lower = lang_code.lower()
        if lower in original_langs:
            return True
        base = lower.split("-")[0]
        return primary_base and base == primary_base

    for lang_code, formats in subtitles.items():
        if should_skip_translation(lang_code):
            continue
        fmt = select_format(formats)
        if not fmt:
            continue
        label_name = fmt.get("name") or lang_code
        label = f"{label_name} ({lang_code}) [manual]"
        key = f"trans::{source_lang_for_trans}->{lang_code}::manual"
        add_option(
            key=key,
            label=label,
            track_url=fmt.get("url", ""),
            lang_code=lang_code,
            fmt=fmt.get("ext", "json3"),
            is_generated=False,
            translation_code=lang_code,
            source_lang=source_lang_for_trans,
        )

    for lang_code, formats in automatic.items():
        if should_skip_translation(lang_code):
            continue
        fmt = select_format(formats)
        if not fmt:
            continue
        label_name = fmt.get("name") or lang_code
        label = f"{label_name} ({lang_code}) [auto]"
        key = f"trans::{source_lang_for_trans}->{lang_code}::auto"
        add_option(
            key=key,
            label=label,
            track_url=fmt.get("url", ""),
            lang_code=lang_code,
            fmt=fmt.get("ext", "json3"),
            is_generated=True,
            translation_code=lang_code,
            source_lang=source_lang_for_trans,
        )

    return options


def fetch_caption_entries(option: TranscriptOption) -> List[SubtitleEntry]:
    """Download and parse caption entries for the selected option."""

    try:
        response = requests.get(option.url, timeout=10)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning("Failed to fetch transcript for key %s: %s", option.key, exc)
        return []

    fmt = option.format
    if fmt == "json3":
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON transcript for key %s: %s", option.key, exc)
            return []
        return _parse_json3(data)

    text = response.text
    if fmt == "vtt":
        return _parse_vtt(text)
    if fmt == "srt":
        return _parse_srt(text)

    logger.info("Unsupported caption format %s for key %s", fmt, option.key)
    return []


def _parse_json3(payload: dict) -> List[SubtitleEntry]:
    entries: List[SubtitleEntry] = []
    events = payload.get("events") or []
    for event in events:
        segments = event.get("segs") or []
        if not segments:
            continue
        start_ms = event.get("tStartMs")
        if start_ms is None:
            continue
        duration_ms = event.get("dDurationMs", 0)
        text = "".join(seg.get("utf8", "") for seg in segments)
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        start = float(start_ms) / 1000.0
        end = start + float(duration_ms or 0) / 1000.0
        entries.append(
            SubtitleEntry(index=len(entries) + 1, start_time=start, end_time=end, text=text)
        )
    return entries


def _parse_vtt(content: str) -> List[SubtitleEntry]:
    entries: List[SubtitleEntry] = []
    blocks = content.replace("\r", "").strip().split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        if "-->" in lines[0]:
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) >= 3 and "-->" in lines[1]:
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            continue
        try:
            start_str, end_str = [part.strip() for part in time_line.split("-->")]
            start = _parse_timestamp(start_str)
            end = _parse_timestamp(end_str)
        except ValueError:
            continue
        text = " ".join(text_lines).strip()
        if not text:
            continue
        entries.append(
            SubtitleEntry(index=len(entries) + 1, start_time=start, end_time=end, text=text)
        )
    return entries


def _parse_srt(content: str) -> List[SubtitleEntry]:
    entries: List[SubtitleEntry] = []
    blocks = content.replace("\r", "").strip().split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        if "-->" in lines[0]:
            time_line = lines[0]
            text_lines = lines[1:]
        elif len(lines) >= 3 and "-->" in lines[1]:
            time_line = lines[1]
            text_lines = lines[2:]
        else:
            continue
        try:
            start_str, end_str = [part.strip() for part in time_line.split("-->")]
            start = _parse_timestamp(start_str.replace(",", "."))
            end = _parse_timestamp(end_str.replace(",", "."))
        except ValueError:
            continue
        text = " ".join(text_lines).strip()
        if not text:
            continue
        entries.append(
            SubtitleEntry(index=len(entries) + 1, start_time=start, end_time=end, text=text)
        )
    return entries


def _parse_timestamp(value: str) -> float:
    hours, minutes, seconds = 0, 0, 0.0
    if value.count(":") == 2:
        hours_str, minutes_str, seconds_str = value.split(":")
        hours = int(hours_str)
        minutes = int(minutes_str)
    elif value.count(":") == 1:
        minutes_str, seconds_str = value.split(":")
        minutes = int(minutes_str)
    else:
        seconds_str = value
    seconds = float(seconds_str)
    return hours * 3600.0 + minutes * 60.0 + seconds
