#!/usr/bin/env python3
"""Append Codex conversation snippets to a local log file."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG = Path(__file__).resolve().parent.parent / "conversation_logs" / "codex_session.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append a Codex conversation entry to the local log")
    parser.add_argument(
        "message",
        nargs="?",
        help="The text to append. Omit to read from stdin (useful for multi-line content).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read message content from standard input instead of the CLI argument.",
    )
    parser.add_argument(
        "--speaker",
        default="user",
        help="Label describing who sent the message (e.g. 'user', 'assistant').",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG,
        help="Optional custom log file location (default: conversation_logs/codex_session.log).",
    )
    return parser.parse_args()


def read_message(args: argparse.Namespace) -> str:
    if args.stdin:
        content = sys.stdin.read().strip()
        if not content:
            raise ValueError("No content received on stdin. Aborting log append.")
        return content

    if args.message:
        return args.message

    raise ValueError("Provide a message argument or pass --stdin with piped content.")


def ensure_log_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)


def append_entry(path: Path, speaker: str, message: str) -> None:
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    entry_header = f"[{timestamp}] {speaker}:"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry_header + "\n")
        handle.write(message.rstrip() + "\n\n")


def main() -> None:
    args = parse_args()

    try:
        message = read_message(args)
    except ValueError as exc:
        raise SystemExit(str(exc))

    ensure_log_file(args.log_path)
    append_entry(args.log_path, args.speaker, message)


if __name__ == "__main__":
    main()
