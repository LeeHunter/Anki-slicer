import os
import logging
from .player import PlayerUI
from .i18n import load_translator


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from pathlib import Path
    from .ui import FileSelectorUI

    # Basic logging config with optional debug toggle via env var
    level = logging.DEBUG if os.getenv("ANKI_SLICER_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")

    app = QApplication([])

    # Allow overriding locale via env, otherwise use system default.
    load_translator(app, os.getenv("ANKI_SLICER_LOCALE"))

    # Set a custom app/window icon if available
    try:
        icon_path = Path(__file__).resolve().parent.parent / "images" / "app_icon.png"
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        else:
            logging.getLogger(__name__).info(
                "App icon not found at %s — using default platform icon.", icon_path
            )
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to set app icon: %s", e)
    window = FileSelectorUI()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
