🎧 Anki‑Slicer

Anki‑Slicer is a utility that lets you take an audio file (MP3, WAV, etc.) plus two SRT subtitles (original + translation), preview and flag sentences you want to learn, and then bulk‑export them into Anki flashcards — fully synchronized with the audio.

It’s designed for language learners who want to build rich, sentence‑level listening cards with audio + subtitles, all in just a few clicks.
✨ Features

    🎵 Load an audio file + a pair of SRT subtitles (original + translation).
    ⏯️ Continuous / Auto‑Pause playback modes for sentence‑by‑sentence listening.
    🕹 Slider & Time Display to seek anywhere in the audio.
    🚩 Flag individual sentences or bulk‑flag all search matches.
    🔎 Search subtitles (original, translation, or both) and jump through results.
    🗂 Flagged list with checkboxes (select/deselect before exporting).
    📤 Export flagged items into Anki via AnkiConnect — creates cards automatically.
    🃏 Output deck: AnkiSlicer (rename inside Anki if you want multiple decks).

📦 Prerequisites

    Anki with the AnkiConnect add‑on installed and running.
    An audio file and two SRT files:
        Original transcript (same language as the audio).
        Translation of the original text.

💡 Tip: I personally use McWhisper (paid app) to generate accurate SRTs and export audio from YouTube or audio files. Other workflows are possible — e.g. extracting captions from YouTube, generating with Whisper/AI, etc.

🚀 Installation

Clone the repo and install dependencies (Python 3.10+ recommended):

bash

Copy
git clone https://github.com/YOUR_USERNAME/anki-slicer.git
cd anki-slicer
pip install -r requirements.txt

🎮 How to Use Anki‑Slicer

    Ensure Anki + AnkiConnect are running.
    Launch Anki‑Slicer:

    bash

    Copy
    python main.py

    Select your:
        Audio file
        Original SRT
        Translation SRT
    Use the controls:
        ▶ Play / ⏸ Pause / ⏮ Previous / ⏭ Next
        Mode toggle = Continuous vs. Auto‑Pause playback
        Use the slider to jump around
        🔍 Search subtitles (Original / Translation / Both)
        🚩 Flag sentences (individually or bulk‑flag from Search)
    Review your flagged list, check/uncheck items.
    Click Export Selection to Anki → cards are created in your AnkiSlicer deck.

🖼 UI Preview

Anki-Slicer Screenshot
🛠 Advanced Use

    Enhance your translation SRT before loading:
        Add explanations, grammar notes, transliterations (e.g. pinyin for Chinese).
        These extras appear on the answer side of the Anki card.
    Organize by subject: rename or split cards into different decks once in Anki.

🤝 Contributing

Contributions are welcome!
Ideas, bug reports, feature requests → open an Issue.
Pull requests are encouraged — new features (UI tweaks, extra export formats, etc.) are fair game.

⚖️ License

This project is licensed under the MIT License — see LICENSE for details.

🧪 Status

Currently tested primarily on macOS. Windows/Linux should work but are not yet validated.
YMMV (Your Mileage May Vary). Feedback and testing reports are very welcome!
