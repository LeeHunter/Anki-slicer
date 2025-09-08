from pydub import AudioSegment
from subs import SubtitleEntry
import os


def slice_audio(input_path: str, entry: SubtitleEntry, out_dir: str) -> str:
    """
    Extracts the audio for a subtitle entry from the input file
    (MP3, M4A, WAV, etc.) and exports as MP3 for Anki.
    """
    os.makedirs(out_dir, exist_ok=True)

    # Use generic loader so any format works (via ffmpeg)
    audio = AudioSegment.from_file(input_path)

    start_ms = int(entry.start_time * 1000)
    end_ms = int(entry.end_time * 1000)

    clip = audio[start_ms:end_ms]

    # Always export as MP3 for Anki compatibility
    out_file = os.path.join(out_dir, f"clip_{entry.index}.mp3")
    clip.export(out_file, format="mp3", bitrate="128k")
    return out_file
