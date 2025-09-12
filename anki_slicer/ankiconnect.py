import requests
import json
import os


class AnkiConnect:
    def __init__(self, url="http://localhost:8765"):
        self.url = url

    def is_available(self) -> bool:
        """Return True if AnkiConnect is reachable, else False."""
        try:
            # 'version' is a cheap, reliable ping
            self._invoke("version")
            return True
        except Exception:
            return False

    def _invoke(self, action, **params):
        """Send a request to AnkiConnect."""
        request_data = {"action": action, "version": 6, "params": params}

        try:
            response = requests.post(self.url, json=request_data)
            response.raise_for_status()
            result = response.json()

            if result.get("error"):
                raise Exception(f"AnkiConnect error: {result['error']}")

            return result.get("result")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to AnkiConnect: {e}")

    def ensure_deck(self, deck_name: str = "AnkiSlicer"):
        """Ensure a deck exists in Anki (creates if missing)."""
        try:
            self._invoke("createDeck", deck=deck_name)
        except Exception as e:
            # Ignore if deck already exists
            if "already exists" not in str(e).lower():
                raise Exception(f"Failed to ensure deck '{deck_name}': {e}")

    def add_note(
        self, front: str, back: str, audio_path: str, deck_name: str = "AnkiSlicer"
    ):
        """Add a note to Anki with audio attachment."""
        note = {
            "deckName": deck_name,
            "modelName": "Basic",
            "fields": {
                "Front": front,
                "Back": back,
            },
            "audio": [
                {
                    "path": audio_path,
                    "filename": os.path.basename(audio_path),
                    "fields": ["Front"],
                }
            ],
        }

        try:
            result = self._invoke("addNote", note=note)
            return result
        except Exception as e:
            raise Exception(f"Failed to add note: {e}")

    def create_deck(self, deck_name: str):
        """Create a new deck if it doesn't exist."""
        try:
            self._invoke("createDeck", deck=deck_name)
        except Exception as e:
            # Deck might already exist, which is fine
            if "already exists" not in str(e).lower():
                raise Exception(f"Failed to create deck '{deck_name}': {e}")
