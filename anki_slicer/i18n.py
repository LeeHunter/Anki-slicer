"""Localization helpers for Anki-Slicer.

This module centralizes translation loading so the application can be made
translation-friendly without scattering Qt translation logic across the UI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QCoreApplication, QLocale, QTranslator

logger = logging.getLogger(__name__)

_translator: Optional[QTranslator] = None


def load_translator(app, language: Optional[str] = None) -> bool:
    """Attempt to install a Qt translator for ``language``.

    Args:
        app: The ``QApplication`` instance.
        language: Optional BCP47/Qt locale string (``"en_US"``, ``"de"``).

    Returns:
        ``True`` if a translation bundle was installed, otherwise ``False``.
    """

    global _translator

    locale_dir = Path(__file__).resolve().parent / "locale"
    if not locale_dir.exists():
        logger.debug("Locale directory %s does not exist yet.", locale_dir)
        return False

    desired_locale = QLocale(language) if language else QLocale.system()
    translator = QTranslator()

    base_name = "anki_slicer"
    loaded = False

    # Try locale-specific file first (e.g., anki_slicer_en_US.qm)
    if translator.load(desired_locale, base_name, "_", str(locale_dir)):
        loaded = True
    else:
        locale_name = desired_locale.name()
        # Fallback to language-only (e.g., anki_slicer_en.qm)
        if translator.load(f"{base_name}_{locale_name}", str(locale_dir)):
            loaded = True
        else:
            lang = locale_name.split("_")[0]
            if lang and translator.load(f"{base_name}_{lang}", str(locale_dir)):
                loaded = True

    if not loaded:
        logger.info("No translation found for locale %s", desired_locale.name())
        return False

    # Keep a reference to avoid the translator being garbage collected.
    _translator = translator
    app.installTranslator(translator)
    logger.info("Loaded translation for locale %s", desired_locale.name())
    return True


def tr(context: str, text: str) -> str:
    """Qt-style translation helper.

    Example::

        button.setText(tr("PlayerUI", "Create Anki Card"))
    """

    return QCoreApplication.translate(context, text)

