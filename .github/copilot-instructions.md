# Copilot Instructions for Anki-Slicer

## Project Overview
Anki-Slicer is a Python utility for language learners to create Anki flashcards from audio files and dual SRT subtitles (original + translation). It provides a UI for previewing, flagging, and exporting sentences as cards, integrating with Anki via AnkiConnect.

## Architecture & Key Components
- **anki_slicer/**: Main source code. Key modules:
  - `main.py`, `__main__.py`: Entrypoints for running the app.
  - `ui.py`: User interface logic (audio preview, subtitle navigation, card creation).
  - `slicer.py`, `segment_adjuster.py`: Audio slicing and segment adjustment.
  - `subs.py`: Subtitle parsing and search.
  - `ankiconnect.py`: Handles communication with Anki via AnkiConnect API.
  - `exporter.py`: Card export logic.
  - `config.py`: Configuration management.
- **anki_clips/**: Stores generated audio clips for cards.
- **images/**: UI and documentation assets.

## Developer Workflows
- **Install**: `pip install -e .` (after cloning)
- **Run**: `python main.py` (ensure Anki with AnkiConnect is running)
- **Dependencies**: See `requirements.txt` and `pyproject.toml`. Requires Python 3.9+.
- **Testing**: No formal test suite; manual validation recommended. macOS is the primary tested platform.

## Patterns & Conventions
- **Audio/Subtitle Pairing**: Code expects matching audio and SRT files. Subtitle search and segment selection are core UI features.
- **Export**: Cards are created in the specified Anki deck; new decks are auto-created if needed.
- **AnkiConnect**: All Anki integration uses the AnkiConnect API (see `ankiconnect.py`).
- **UI**: Card creation, playback, and subtitle navigation are handled in `ui.py`.
- **RTF Formatting**: Card answer fields support RTF formatting for rich text.

## Integration Points
- **External**: Requires Anki desktop app with AnkiConnect add-on running.
- **SRT Generation**: Users may use external tools (e.g., MacWhisper, Whisper.AI) to generate subtitles.

## Examples
- To add a new export format, extend `exporter.py` and update UI triggers in `ui.py`.
- To support new subtitle formats, modify `subs.py`.
- For new Anki fields or models, update `ankiconnect.py` and related UI logic.

## Platform Notes
- Only macOS is fully validated; Windows/Linux may require tweaks.

---
For questions, open an Issue or review the README for workflow details.
