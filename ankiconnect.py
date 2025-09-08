import requests
import json
import base64
import os

ANKI_CONNECT_URL = "http://localhost:8765"

class AnkiConnect:
    def __init__(self, deck_name="AnkiSlicer", note_type="Basic"):
        self.deck_name = deck_name
        self.note_type = note_type

    def request(self, action, **params):
        payload = {"action": action, "params": params, "version": 6}
        response = requests.post(ANKI_CONNECT_URL, json=payload).json()
        if "error" in response and response["error"]:
            raise Exception(response["error"])
        return response.get("result")

    def ensure_deck(self):
        self.request("createDeck", deck=self.deck_name)

    def add_note(self, front, back, audio_path):
        # Read MP3 as bytes for upload
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        
        b64 = base64.b64encode(audio_data).decode("utf-8")
        filename = os.path.basename(audio_path)

        return self.request(
            "addNote",
            note={
                "deckName": self.deck_name,
                "modelName": self.note_type,
                "fields": {
                    "Front": front,
                    "Back": back
                },
                "options": {
                    "allowDuplicate": False
                },
                "tags": ["anki-slicer"],
                "audio": [{
                    "data": b64,
                    "filename": filename,
                    "fields": ["Front"]
                }]
            }
        )
