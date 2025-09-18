#!/usr/bin/env bash
set -euo pipefail

# Regenerate Qt translation catalogs and compiled QM files.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCALE_DIR="$ROOT_DIR/anki_slicer/locale"

TS_SOURCE="$LOCALE_DIR/anki_slicer_en_US.ts"

if ! command -v pylupdate6 >/dev/null 2>&1; then
  echo "pylupdate6 is required but not found. Install Qt Linguist tools." >&2
  exit 1
fi

if ! command -v lrelease >/dev/null 2>&1; then
  echo "lrelease is required but not found. Install Qt Linguist tools." >&2
  exit 1
fi

echo "Updating TS catalogs..."
pylupdate6 \
  "$ROOT_DIR/anki_slicer"/*.py \
  -ts "$TS_SOURCE"

echo "Compiling QM files..."
lrelease "$TS_SOURCE" -qm "$LOCALE_DIR/anki_slicer_en_US.qm"

echo "Translation assets refreshed in $LOCALE_DIR"
