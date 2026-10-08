#!/usr/bin/env python3
"""
setup_login.py

A one‑time helper that launches a headed Chromium instance using a
persistent profile directory, navigates to the Prenot@mi login page, and
lets a human log in manually. The script never reads, stores, or
automatically fills any credentials – it simply opens the browser,
waits for the user to complete the login, then saves the session
cookies to the provided profile directory.
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page, Error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One‑time login setup for Prenot@mi.")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path("./chrome_profile"),
        help="Directory for the persistent Chromium profile (default: ./chrome_profile).",
    )
    parser.add_argument(
        "--url",
        default="https://prenotami.esteri.it/",
        help="URL to open for login (default: https://prenotami.esteri.it/).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="Maximum wait time in seconds before the script exits automatically "
             "(default: 600).",
    )
    return parser.parse_args()


def print_banner() -> None:
    banner = """
============================================================
ONE-TIME LOGIN SETUP
A Chrome window will open. Log into Prenot@mi YOURSELF —
this script will never touch the login form.

IMPORTANT: if you see a "Ricordami" / "Remember me" checkbox
on the login form, CHECK IT before logging in. Confirmed in
production: without it, this site's session can expire in
under 3 hours, which is shorter than the 6-hour gap between
scheduled checks — so the watcher ends up "logged out" almost
every single run. A remember-me / persistent-auth cookie is
the most likely way to make the session actually survive the
gap between checks.

Once you are logged in and can see your account/dashboard,
come back to this terminal and press Enter to save the
session and close the browser.
============================================================
"""
    print(banner.strip())


def main() -> None:
    args = parse_args()
    print_banner()

    try:
        with sync_playwright() as pw:  # type: Playwright
            profile_dir = str(args.profile_dir.resolve())
            context: BrowserContext = pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                viewport={"width": 1280, "height": 900},
            )
            page: Page = context.new_page()
            page.goto(args.url)

            # Simple blocking wait for user confirmation.
            try:
                input("Press Enter here once you are fully logged in... ")
            except KeyboardInterrupt:
                print("\nInterrupted by user. Exiting without saving.")
                context.close()
                sys.exit(1)

            print(f"✅ Session saved to profile directory: {profile_dir}")
            context.close()
    except (Error, Exception) as exc:
        print(f"❌ Failed to complete login setup: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
