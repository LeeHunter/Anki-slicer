from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .i18n import load_translator
from .player import PlayerUI
from .ui import FileSelectorUI


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv or sys.argv)
    if not raw_argv:
        raw_argv = ["anki_slicer"]
    else:
        raw_argv[0] = "anki_slicer"

    parser = argparse.ArgumentParser(description="Anki-Slicer UI launcher")
    parser.add_argument(
        "--file-selector",
        action="store_true",
        help="Start with the legacy file selection window instead of the player",
    )
    args, qt_args = parser.parse_known_args(raw_argv[1:])
    qt_argv = [raw_argv[0]] + qt_args

    # Keep sys.argv consistent for Qt
    if not sys.argv:
        sys.argv.extend(qt_argv)
    else:
        sys.argv[:] = qt_argv

    app = QApplication(qt_argv)
    app.setApplicationName("Anki Slicer")
    app.setApplicationDisplayName("Anki Slicer")
    app.setDesktopFileName("anki-slicer.desktop")

    # Basic logging config with optional debug toggle via env var
    level = logging.DEBUG if os.getenv("ANKI_SLICER_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")

    load_translator(app, os.getenv("ANKI_SLICER_LOCALE"))

    # Set a custom application icon if available
    try:
        icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception as exc:  # pragma: no cover - icon loading best-effort
        logging.getLogger(__name__).warning("Failed to set app icon: %s", exc)

    if args.file_selector:
        window = FileSelectorUI()
    else:
        window = PlayerUI(
            mp3_path=None,
            orig_entries=[],
            trans_entries=[],
            allow_streaming=True,
        )

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
