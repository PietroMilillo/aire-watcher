"""notify.py
Notification helper for the AIRE appointment watcher.

Provides:
- macOS native notifications via `osascript`.
- Optional iMessage sending through the Messages app.
Only the Python standard library is used; no credentials are handled.
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Configure module logger
logger = logging.getLogger("notify")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _escape_applescript(s: str) -> str:
    """Escape double quotes and backslashes for safe embedding in AppleScript."""
    return s.replace("\\", r"\\").replace('"', r"\"")


def notify_macos(title: str, message: str, subtitle: Optional[str] = None) -> bool:
    """
    Send a native macOS notification.

    Returns True on success, False otherwise. All errors are logged.
    """
    try:
        title_esc = _escape_applescript(title)
        message_esc = _escape_applescript(message)
        parts = [f'display notification "{message_esc}" with title "{title_esc}"']
        if subtitle:
            subtitle_esc = _escape_applescript(subtitle)
            parts[0] += f' subtitle "{subtitle_esc}"'
        script = " ".join(parts)

        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                "notify_macos failed: %s", result.stderr.strip() or "unknown error"
            )
            return False
        return True
    except Exception as e:  # pragma: no cover
        logger.exception("notify_macos exception: %s", e)
        return False


def send_imessage(recipient: str, message: str) -> bool:
    """
    Send an iMessage via the Messages app.

    Returns True on success, False otherwise. Errors are logged.
    """
    try:
        recipient_esc = _escape_applescript(recipient)
        message_esc = _escape_applescript(message)

        script = (
            'tell application "Messages"\n'
            "    set targetService to 1st service whose service type = iMessage\n"
            f'    set targetBuddy to buddy "{recipient_esc}" of targetService\n'
            f'    send "{message_esc}" to targetBuddy\n'
            "end tell"
        )

        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                "send_imessage failed: %s", result.stderr.strip() or "unknown error"
            )
            return False
        return True
    except Exception as e:  # pragma: no cover
        logger.exception("send_imessage exception: %s", e)
        return False


def notify_all(title: str, message: str, imessage_recipient: Optional[str] = None) -> None:
    """
    Send a macOS notification and optionally an iMessage.

    Logs success/failure of each channel. Never raises.
    """
    try:
        macos_success = notify_macos(title, message)
        logger.info("macOS notification %s", "succeeded" if macos_success else "failed")
    except Exception:  # pragma: no cover
        logger.exception("Unexpected error in notify_macos")

    if imessage_recipient:
        try:
            im_success = send_imessage(imessage_recipient, message)
            logger.info(
                "iMessage to %s %s",
                imessage_recipient,
                "succeeded" if im_success else "failed",
            )
        except Exception:  # pragma: no cover
            logger.exception("Unexpected error in send_imessage")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send macOS notification and optional iMessage."
    )
    parser.add_argument("--title", required=True, help="Notification title")
    parser.add_argument("--message", required=True, help="Notification/message body")
    parser.add_argument(
        "--imessage",
        dest="imessage_recipient",
        help="Phone number or Apple ID to send iMessage to",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    # Perform notifications once each, printing results for manual testing.
    macos_ok = notify_macos(args.title, args.message)
    print(f"macOS notification: {'OK' if macos_ok else 'FAIL'}")
    if args.imessage_recipient:
        im_ok = send_imessage(args.imessage_recipient, args.message)
        print(f"iMessage to {args.imessage_recipient}: {'OK' if im_ok else 'FAIL'}")

