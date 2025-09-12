# Updated slice_audio function for slicer.py
# Add override_start and override_end parameters


def slice_audio(
    mp3_path: str, entry, out_dir: str, override_start=None, override_end=None
):
    """
    Slice audio file based on subtitle entry timing or override values.

    Args:
        mp3_path: Path to the source audio file
        entry: SubtitleEntry object with timing and text
        out_dir: Output directory for the sliced audio
        override_start: Optional start time in seconds (overrides entry.start_time)
        override_end: Optional end time in seconds (overrides entry.end_time)

    Returns:
        str: Path to the created audio clip
    """
    from pydub import AudioSegment
    import os

    # Use override times if provided, otherwise use subtitle entry times
    start_time = override_start if override_start is not None else entry.start_time
    end_time = override_end if override_end is not None else entry.end_time

    # Convert to milliseconds for pydub
    start_ms = int(start_time * 1000)
    end_ms = int(end_time * 1000)

    # Load and slice the audio
    audio = AudioSegment.from_file(mp3_path)
    clip = audio[start_ms:end_ms]

    # Create output directory if it doesn't exist
    os.makedirs(out_dir, exist_ok=True)

    # Generate filename (sanitize the text for filename)
    safe_text = "".join(
        c for c in entry.text[:30] if c.isalnum() or c in (" ", "-", "_")
    ).rstrip()
    filename = f"{entry.index:03d}_{safe_text}.mp3"
    output_path = os.path.join(out_dir, filename)

    # Export the clip
    clip.export(output_path, format="mp3")

    return output_path
