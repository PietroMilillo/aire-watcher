#!/usr/bin/env python3
"""
schedule_wakes.py — arms a one-shot macOS wake for today's (or tomorrow's)
17:00 Central check, on top of the permanent `pmset repeat` wake at 05:00.

Why this exists: `pmset repeat` only supports ONE recurring wake time total
(confirmed via `man pmset`: "may only have one pair of repeating events
scheduled"). The AIRE watcher needs coverage at 17:00 too — that's when the
consulate actually releases new appointment slots each night (00:00 Italy
time) — so we can't rely on `repeat` alone for both.

`pmset schedule wake "MM/dd/yy HH:mm:ss"` schedules a ONE-SHOT wake instead.
This script computes the next occurrence of each configured target time and
(re-)arms it. It's meant to be run once daily, as root, by its own
LaunchDaemon (com.pietro.airewatcher.wakeschedule.plist) — root because
`pmset` requires it. It does not touch AIRE watcher's own config or
credentials; it only calls `pmset schedule wake`.

Usage: sudo python3 schedule_wakes.py
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta

# Times (24h, local/Central) to guarantee a wake for, beyond the permanent
# `pmset repeat` wake already set at 05:00. Add more here if ever needed.
TARGET_TIMES = [(17, 0)]

OWNER_TAG = "airewatcher"


def next_occurrence(hour: int, minute: int, now: datetime) -> datetime:
    """Return the next datetime at hour:minute, today if not yet passed,
    otherwise tomorrow."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def schedule_wake(when: datetime) -> bool:
    """Call `pmset schedule wake` for the given datetime. Returns True on
    success."""
    timestamp = when.strftime("%m/%d/%y %H:%M:%S")
    cmd = ["pmset", "schedule", "wake", timestamp, OWNER_TAG]
    print(f"Arming wake for {timestamp} ...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
        return False
    print("  OK")
    return True


def main() -> int:
    if sys.platform != "darwin":
        print("This script only makes sense on macOS.", file=sys.stderr)
        return 1

    now = datetime.now()
    ok = True
    for hour, minute in TARGET_TIMES:
        when = next_occurrence(hour, minute, now)
        if not schedule_wake(when):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
