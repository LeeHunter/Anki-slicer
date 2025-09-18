#!/usr/bin/env python3
"""Kivy spike: minimal layout mimicking Anki-Slicer player controls."""

from __future__ import annotations

import sys

from kivy.app import App
from kivy.lang import Builder
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout


KV = """
<RootLayout>:
    orientation: "vertical"
    padding: "16dp"
    spacing: "12dp"

    Label:
        text: root.subtitle_original
        font_size: "18sp"
        bold: True
        color: 0.2, 0.4, 0.8, 1
        text_size: self.width, None
        size_hint_y: None
        height: self.texture_size[1]

    TextInput:
        hint_text: "Edit translation…"
        multiline: True
        size_hint_y: None
        height: dp(160)

    Slider:
        min: 0
        max: 100
        value: 25

    BoxLayout:
        size_hint_y: None
        height: dp(160)
        canvas.before:
            Color:
                rgba: 0.9, 0.94, 1, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: "Waveform placeholder"
            color: 0.3, 0.5, 0.9, 1
            bold: True
            font_size: "16sp"

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: "8dp"

        Button:
            text: "Back"
        Button:
            text: "Forward"
        ToggleButton:
            text: "Auto-Pause"

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: "8dp"

        Label:
            text: "Adjust Start:"
            size_hint_x: None
            width: dp(120)
        Button:
            text: "−"
            size_hint_x: None
            width: dp(48)
        Button:
            text: "+"
            size_hint_x: None
            width: dp(48)
        Widget:
            size_hint_x: None
            width: dp(16)
        Button:
            text: "Extend →→"
            size_hint_x: None
            width: dp(160)
        Widget:
            size_hint_x: 1

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: "8dp"

        Label:
            text: "Adjust End:"
            size_hint_x: None
            width: dp(120)
        Button:
            text: "−"
            size_hint_x: None
            width: dp(48)
        Button:
            text: "+"
            size_hint_x: None
            width: dp(48)

    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: "8dp"

        Button:
            text: "Create Anki Card"
            size_hint_x: None
            width: dp(180)
        Label:
            text: "Deck:"
            size_hint_x: None
            width: dp(80)
        TextInput:
            text: "AnkiSlicer"
        Label:
            text: "Source:"
            size_hint_x: None
            width: dp(80)
        TextInput:
            text: ""
"""


class RootLayout(BoxLayout):
    subtitle_original = StringProperty("Demo subtitle text from current selection.")


class PrototypeApp(App):
    def build(self):
        Builder.load_string(KV)
        return RootLayout()


def main() -> int:
    PrototypeApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
