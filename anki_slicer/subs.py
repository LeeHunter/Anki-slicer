import re
import logging
import os
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    index: int
    start_time: float  # seconds
    end_time: float  # seconds
    text: str


class SRTParser:
    @staticmethod
    def parse_srt_file(filepath: str) -> List[SubtitleEntry]:
        """Parse an SRT file and return list of SubtitleEntry objects.
        More robust handling of CRLF, BOM, and leading blank lines.
        """
        try:
            with open(filepath, "r", encoding="utf-8", errors="strict") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1", errors="ignore") as f:
                content = f.read()

        # Normalize newlines and strip BOM
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        content = content.lstrip("\ufeff")
        # Keep trailing newline structure; don't strip() entire file which can drop first/last lines

        entries: List[SubtitleEntry] = []

        # Split on blank line(s) followed by an index line
        blocks = re.split(r"\n{2,}(?=\d+\s*\n)", content)

        logger.debug("SRT blocks loaded (%d blocks) from %s", len(blocks), filepath)

        debug_dump = bool(os.getenv("ANKI_SLICER_DEBUG"))
        for raw_block in blocks:
            block = raw_block.strip("\n")
            if not block.strip():
                continue

            lines = [ln.strip("\ufeff") for ln in block.split("\n")]
            # Skip leading empties
            i = 0
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                continue

            # Index line may contain BOM or spaces
            idx_line = lines[i].strip()
            # Some generators omit the numeric index; detect and synthesize
            try:
                index = int(re.match(r"\D*(\d+)", idx_line).group(1))
                i += 1
            except Exception:
                # If the first non-empty line is actually the timestamp, synthesize index
                index = len(entries) + 1

            if i >= len(lines):
                continue

            # Timestamp line
            time_line = lines[i].strip()
            if "-->" not in time_line:
                # Try next line if index line consumed but timestamp is on following line
                i += 1
                if i >= len(lines):
                    continue
                time_line = lines[i].strip()
            try:
                start_str, end_str = [s.strip() for s in time_line.split("-->")]
                start_time = SRTParser._parse_timestamp(start_str)
                end_time = SRTParser._parse_timestamp(end_str)
            except Exception as e:
                logger.warning("Skipping block with bad timestamp: %r (%s)", time_line, e)
                continue

            # Remaining lines are text (preserve internal newlines)
            text_lines = lines[i + 1 :]
            text = "\n".join(text_lines).strip()

            if debug_dump and len(entries) < 2:
                # Dump a detailed view of the first two blocks to help diagnose parsing
                logger.debug(
                    "[DEBUG SRT] file=%s idx=%s raw_block=%r lines=%r text=%r",
                    filepath,
                    index,
                    raw_block[:200],
                    lines,
                    text,
                )
            logger.debug("SubtitleEntry index=%s text_len=%d", index, len(text))
            entries.append(SubtitleEntry(index, start_time, end_time, text))

        return entries

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> float:
        """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
        # Remove any whitespace
        timestamp_str = timestamp_str.strip()

        # Handle both comma and period as decimal separator
        timestamp_str = timestamp_str.replace(",", ".")

        # Parse HH:MM:SS.mmm
        match = re.match(r"(\d{1,2}):(\d{2}):(\d{2})[\.,](\d{3})", timestamp_str)
        if not match:
            raise ValueError(f"Invalid timestamp format: {timestamp_str}")

        hours, minutes, seconds, milliseconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    @staticmethod
    def validate_alignment(
        orig_entries: List[SubtitleEntry], trans_entries: List[SubtitleEntry]
    ) -> Tuple[bool, str]:
        """
        Check if two SRT files are properly aligned.
        Returns (is_valid, error_message)
        """
        if len(orig_entries) != len(trans_entries):
            return (
                False,
                f"Entry count mismatch: Original has {len(orig_entries)} entries, Translation has {len(trans_entries)}",
            )

        if len(orig_entries) == 0:
            return False, "Both SRT files are empty"

        misaligned_entries = []
        time_tolerance = 0.1  # Allow 100ms difference in timestamps

        for i, (orig, trans) in enumerate(zip(orig_entries, trans_entries)):
            # Check if timestamps are roughly aligned
            start_diff = abs(orig.start_time - trans.start_time)
            end_diff = abs(orig.end_time - trans.end_time)

            if start_diff > time_tolerance or end_diff > time_tolerance:
                misaligned_entries.append(i + 1)

        if misaligned_entries:
            if len(misaligned_entries) <= 5:
                entries_str = ", ".join(map(str, misaligned_entries))
                return False, f"Timestamp misalignment in entries: {entries_str}"
            else:
                return (
                    False,
                    f"Timestamp misalignment in {len(misaligned_entries)} entries (first few: {', '.join(map(str, misaligned_entries[:5]))})",
                )

        return True, f"✓ Files are properly aligned ({len(orig_entries)} entries)"
