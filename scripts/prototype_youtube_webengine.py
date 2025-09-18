#!/usr/bin/env python3
"""Quick spike: embed a YouTube video using PyQt6 + QtWebEngine."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView

DEFAULT_VIDEO = "https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=0&modestbranding=1&rel=0"


def main() -> int:
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("YouTube WebEngine Prototype")
    window.resize(1280, 720)

    layout = QVBoxLayout(window)
    view = QWebEngineView(parent=window)
    layout.addWidget(view)

    target_url = DEFAULT_VIDEO
    if len(sys.argv) > 1:
        target_url = sys.argv[1]

    # If the provided URL looks like a standard watch link, convert to embed format.
    if "youtube.com/watch" in target_url and "embed" not in target_url:
        url_obj = QUrl(target_url)
        video_id = url_obj.query().split("v=")[-1].split("&")[0]
        target_url = f"https://www.youtube.com/embed/{video_id}?autoplay=0&modestbranding=1&rel=0"

    view.setUrl(QUrl(target_url))
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Prototype failed: {exc}", file=sys.stderr)
        sys.exit(1)
