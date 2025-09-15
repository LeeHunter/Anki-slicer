import re
import logging
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
        """Parse an SRT file and return list of SubtitleEntry objects."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read().strip()

        entries = []
        blocks = re.split(r"\n\n(?=\d+\n)", content)

        logger.debug("SRT blocks loaded (%d blocks)", len(blocks))
        for block in blocks:
            logger.debug("--- BLOCK ---\n%s", block)

        for block in blocks:
            if not block.strip():
                continue

            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue

            try:
                index = int(lines[0])
                time_line = lines[1]
                start_str, end_str = time_line.split(" --> ")
                start_time = SRTParser._parse_timestamp(start_str)
                end_time = SRTParser._parse_timestamp(end_str)
                text = "\n".join(lines[2:]).strip()
                logger.debug("SubtitleEntry index=%s text=\n%s\n", index, text)
                entries.append(SubtitleEntry(index, start_time, end_time, text))
            except (ValueError, IndexError) as e:
                logger.warning(
                    "Skipping malformed SRT block: %s... Error: %s",
                    block[:50],
                    e,
                )
                continue

        return entries

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> float:
        """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
        # Remove any whitespace
        timestamp_str = timestamp_str.strip()

        # Handle both comma and period as decimal separator
        timestamp_str = timestamp_str.replace(",", ".")

        # Parse HH:MM:SS.mmm
        match = re.match(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})", timestamp_str)
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
