🎧 Anki‑Slicer

Anki‑Slicer is a utility that lets you take an audio file (MP3, WAV, etc.) plus two SRT subtitles (original + translation), preview and flag sentences you want to learn, and then export it into an Anki flashcard deck — fully synchronized with the audio.

It’s designed for language learners who want to build rich, sentence‑level listening cards with audio + text, all in just a few clicks.
✨ Features

    ⏯️ Precise adjustment of audio selection (no more clipped audio or extra sounds).
    🕹 Slider & Time Display to seek anywhere in the audio.
    🔎 Search subtitles (original, translation, or both) and jump through results.
    📤 Export flagged items into Anki via AnkiConnect — creates cards automatically.
   

📦 Prerequisites

    Python 3.9 or later
    Anki with the AnkiConnect add‑on installed and running.
    An audio file and two SRT files:
        Original transcript (same language as the audio).
        Translation of the original text.

💡 Tip: I personally use McWhisper (paid app) to generate accurate SRTs and export audio from YouTube or audio files. Other workflows are possible — e.g. extracting captions from YouTube, generating with whisper.AI, etc.


## 🚀 Installation

### Easy install (from PyPI) – **recommended**
```bash
pip install anki-slicer

### Install directly from GitHub
pip install git+https://github.com/LeeHunter/anki-slicer.git

### Developer install (for contributors)
git clone https://github.com/LeeHunter/anki-slicer.git
cd anki-slicer
pip install -e .




🎮 How to Use Anki‑Slicer

   In a terminal run the following command: python -m anki_slicer

    Ensure Anki (with the AnkiConnect add-on) is running.
    Launch Anki‑Slicer:

    python main.py

    Select your:
        Audio file
        Original SRT
        Translation SRT
    Use the controls:
        ▶ Forward and Back buttons
        Mode toggle = Continuous vs. Auto‑Pause playback
        Use the slider to jump around
        🔍 Search subtitles (Original / Translation / Both)
        =/- buttons for precise editing of the selection length
        
    
    Click Create Anki Card → card is created in your AnkiSlicer deck. You can specify the name of the Anki deck. If a deck with that name doesn't exist it will be created. 

🖼 UI Preview

[<img width="938" height="789" alt="SCR-20250912-gpjp" src="https://github.com/user-attachments/assets/93ab84f6-2e16-44ae-a6b4-defb1b1a0a47" />](https://private-user-images.githubusercontent.com/1231548/488928663-c13ba5cb-5a14-4a84-bafa-4e545934db9f.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NTc2OTQyNzgsIm5iZiI6MTc1NzY5Mzk3OCwicGF0aCI6Ii8xMjMxNTQ4LzQ4ODkyODY2My1jMTNiYTVjYi01YTE0LTRhODQtYmFmYS00ZTU0NTkzNGRiOWYucG5nP1gtQW16LUFsZ29yaXRobT1BV1M0LUhNQUMtU0hBMjU2JlgtQW16LUNyZWRlbnRpYWw9QUtJQVZDT0RZTFNBNTNQUUs0WkElMkYyMDI1MDkxMiUyRnVzLWVhc3QtMSUyRnMzJTJGYXdzNF9yZXF1ZXN0JlgtQW16LURhdGU9MjAyNTA5MTJUMTYxOTM4WiZYLUFtei1FeHBpcmVzPTMwMCZYLUFtei1TaWduYXR1cmU9ZTI1MGI3NmY1ZTJiNjliMmI5OWE2MzY3YWYyMjQ5YWJmYzA3ZTMyYzkyMzgyM2M2NGI1ZGM0NDViMDQ5N2E1OSZYLUFtei1TaWduZWRIZWFkZXJzPWhvc3QifQ.1PmuEgIlNZRebS8Pg5l0ETVgHyCX1QtpbLeyH_8pneo)

Anki-Slicer Screenshot
🛠 Tip

    Before using Anki-Slicer you might want to edit your translation SRT before loading:
        For example you can use AI to add explanations, grammar notes, transliterations etc. 
        This text appears on the answer side of the Anki card. Note that Anki uses HTML for formatting. 
    

🤝 Contributing

Contributions are welcome!
Ideas, bug reports, feature requests → open an Issue.
Pull requests are encouraged — new features (UI tweaks, extra export formats, etc.) are fair game.

⚖️ License

This project is licensed under the MIT License — see LICENSE for details.

🧪 Status

Currently tested only on macOS. Windows/Linux should work but are not yet validated.
 Feedback and testing reports are welcome!
