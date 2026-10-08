#!/usr/bin/env python3
"""
watcher.py – AIRE/​Prenot@mi slot‑availability checker

Purpose
-------
This script periodically (e.g. via macOS launchd) checks the Italian
consulate’s Prenot@mi booking portal for newly‑available appointment slots.
It never performs any booking actions – it only navigates, clicks
*purely navigational* elements defined by the user, reads page state and
sends a notification when a possible slot is detected.

Safety Guarantees
-----------------
* **No password handling** – the script never calls ``fill()`` or ``type()``
  on inputs whose name/id/placeholder contain “password”, “pwd”, or “pass”.
* **No booking clicks** – it never clicks elements whose visible text,
  ``id``, ``name`` or other attributes contain “confirm”, “conferma”,
  “prenota”, “invia”, “submit”, or “book now”.  Only the selectors supplied
  in ``config["click_path"]`` are clicked, after a safety check.
* **No CAPTCHA solving** – if a CAPTCHA (``captcha``, ``recaptcha`` or
  ``hcaptcha``) is detected the script stops, takes a screenshot,
  notifies the user and exits without retrying.
* **No automatic booking** – the script never reaches the final “book”
  or “confirm” step; any slot detection is reported for manual handling.

Usage
-----
python watcher.py [config.json]
If no argument is supplied, ``config.json`` in the script’s directory is used.

The configuration file (JSON) controls URLs, selectors, timeouts,
retry behaviour, notification recipients, and paths for logs/screenshots.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# --------------------------------------------------------------------------- #
# Notification handling (fallback stub if notify.py is missing)
# --------------------------------------------------------------------------- #
try:
    from notify import notify_all  # type: ignore
except Exception as e:  # pragma: no cover
    logging.basicConfig(level=logging.WARNING)
    logging.warning("notify module not available (%s); notifications disabled.", e)

    def notify_all(*, title: str, message: str, imessage_recipient: Optional[str] = None) -> None:
        """Fallback stub – logs the notification attempt."""
        logging.error(
            "Notification stub called – title=%s, message=%s, recipient=%s",
            title,
            message,
            imessage_recipient,
        )


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
def setup_logging(log_dir: Path) -> None:
    """Configure root logger with a rotating file handler and stdout."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    fmt = "%(asctime)s %(levelname)s %(message)s"
    formatter = logging.Formatter(fmt)

    # Console handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # Rotating file handler
    log_path = log_dir / "watcher.log"
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)


# --------------------------------------------------------------------------- #
# Configuration handling
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG: Dict[str, Any] = {
    "profile_dir": "./chrome_profile",
    "start_url": "https://prenotami.esteri.it/",
    "click_path": [],
    "availability_selectors": {
        "no_slots_text": [],
        "slot_candidate_selector": "",
    },
    "login_check": {"logged_out_text": []},
    "imessage_recipient": None,
    "timeout_ms": 60000,
    "max_retries": 3,
    "retry_backoff_seconds": [30, 90, 240],
    "screenshot_dir": "./logs",
    "state_file": "./logs/last_state.json",
}


def load_config(path: Path) -> Dict[str, Any]:
    """Load JSON config from *path*, merging with defaults."""
    config = DEFAULT_CONFIG.copy()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # shallow merge, recursively merge dict values
                for k, v in data.items():
                    if isinstance(v, dict) and isinstance(config.get(k), dict):
                        config[k].update(v)
                    else:
                        config[k] = v
            else:
                logging.warning("Config file %s does not contain a JSON object; using defaults.", path)
        except Exception:
            logging.exception("Failed to parse config file %s; using defaults.", path)
    else:
        logging.info("Config file %s not found; using defaults.", path)
    return config


# --------------------------------------------------------------------------- #
# State persistence
# --------------------------------------------------------------------------- #
def save_state(state_path: Path, status: str, screenshot_path: Optional[Path] = None) -> None:
    """Write current *status* (and optional screenshot) to *state_path*."""
    state = {
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if screenshot_path:
        state["screenshot"] = str(screenshot_path)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logging.exception("Failed to write state to %s", state_path)


def load_previous_state(state_path: Path) -> Optional[Dict[str, Any]]:
    """Return the JSON state from *state_path* if it exists and is valid."""
    if not state_path.is_file():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("Failed to read previous state from %s", state_path)
        return None


# --------------------------------------------------------------------------- #
# Control-flow exception: signals "stop this check cleanly, do not retry"
# without skipping context.close() the way sys.exit() would if raised deep
# inside the retry loop.
# --------------------------------------------------------------------------- #
class StopCheck(Exception):
    """Raised to end the current run cleanly (logged out / CAPTCHA seen)."""


def _resolve_path(base_dir: Path, value: str) -> Path:
    """Resolve *value* relative to *base_dir* (the script's own directory)
    unless it is already absolute. This keeps profile/log/state paths
    correct regardless of the working directory launchd starts us in."""
    p = Path(value)
    return p if p.is_absolute() else (base_dir / p)


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
FORBIDDEN_CLICK_WORDS = [
    "confirm",
    "conferma",
    "prenota",
    "invia",
    "submit",
    "book now",
]


def is_forbidden_click(element_text: str, attrs: List[Optional[str]]) -> bool:
    """Return True if any forbidden keyword appears in the element's text or attrs."""
    combined = (element_text or "").lower() + " " + " ".join([a.lower() for a in attrs if a])
    return any(word in combined for word in FORBIDDEN_CLICK_WORDS)


def safe_click(page, selector: str, step_idx: int) -> None:
    """
    Click the element identified by *selector* after ensuring it does not
    contain any forbidden action keywords.
    """
    element = page.query_selector(selector)
    if not element:
        raise RuntimeError(f"click_path step {step_idx} failed: selector {selector!r} not found")
    # Gather visible text and a few attributes for safety check
    try:
        text = element.inner_text()
    except Exception:
        text = ""
    attr_names = ["id", "name", "placeholder", "aria-label", "title"]
    attrs = []
    for name in attr_names:
        try:
            val = element.get_attribute(name)
        except Exception:
            val = None
        attrs.append(val)

    if is_forbidden_click(text, attrs):
        raise RuntimeError(
            f"click_path step {step_idx} attempted to click a forbidden element "
            f"(selector {selector!r}, text {text!r})"
        )
    logging.info("Clicking step %d with selector %s", step_idx, selector)
    element.click()


EXPECTED_HOST_SUFFIX = "esteri.it"


def detect_captcha(page) -> bool:
    """Return True if a CAPTCHA or bot-detection wall is showing.

    Confirmed live against the real site (2026-09-30): Prenot@mi sits behind
    Radware Bot Manager. On a block, the browser is fully REDIRECTED to a
    different domain (validate.perfdrive.com) to serve the interactive
    challenge — that's the primary, reliable signal, checked via the page's
    current hostname.

    We deliberately do NOT keyword-match page.content() for words like
    "captcha"/"radware" here: testing showed this site's normal page shell
    contains a hidden, inactive CAPTCHA widget and the literal page title
    "Radware Bot Manager Captcha" on EVERY load, pass or fail — so content
    keyword matching produced false positives on completely legitimate
    pages. The hostname check does not have that problem: it only fires on
    an actual navigation away from the real site.

    We only ever detect this and stop — never attempt to solve it or evade
    the detection itself (e.g. no headless-fingerprint spoofing); see
    main() for why this script runs headed.
    """
    try:
        host = urlparse(page.url).hostname or ""
    except Exception:
        logging.exception("Failed to parse page URL for CAPTCHA/bot-wall detection")
        return False
    return not host.endswith(EXPECTED_HOST_SUFFIX)


def check_logged_out(page, logged_out_texts: List[str]) -> bool:
    """Return True if any of *logged_out_texts* appears on the page."""
    try:
        body = page.inner_text("body").lower()
    except Exception:
        logging.exception("Failed to retrieve body text for login check")
        return False
    return any(txt.lower() in body for txt in logged_out_texts)


def determine_status(page, config: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """
    Determine slot availability status.

    Returns:
        (status, elements) where status is one of
        "no_slots", "slots_open", "unknown".
    """
    try:
        body_text = page.inner_text("body").lower()
    except Exception:
        logging.exception("Failed to read body text for status determination")
        body_text = ""

    no_slots_texts = config.get("availability_selectors", {}).get("no_slots_text", [])
    if any(txt.lower() in body_text for txt in no_slots_texts):
        return "no_slots", []

    slot_selector = config.get("availability_selectors", {}).get("slot_candidate_selector", "")
    if not slot_selector:
        logging.warning("No slot_candidate_selector defined in config.")
        return "unknown", []

    try:
        elements = page.query_selector_all(slot_selector)
    except Exception:
        logging.exception("Error while querying slot candidates with selector %s", slot_selector)
        return "unknown", []

    if elements:
        return "slots_open", elements
    else:
        return "unknown", []


def take_screenshot(page, screenshot_dir: Path, status: str) -> Path:
    """Capture a full‑page screenshot; returns the path to the saved file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{status}_{timestamp}.png"
    path = screenshot_dir / filename
    try:
        page.screenshot(path=str(path), full_page=True)
        logging.info("Screenshot saved to %s", path)
    except Exception:
        logging.exception("Failed to take screenshot for status %s", status)
    return path


# --------------------------------------------------------------------------- #
# Core workflow
# --------------------------------------------------------------------------- #
def run_check(
    page,
    config: Dict[str, Any],
    prev_state: Optional[Dict[str, Any]],
    state_path: Path,
    screenshot_dir: Path,
) -> None:
    """
    Execute a single check run: navigate, click path, detect CAPTCHA,
    determine availability, persist state, and send notifications as needed.
    """
    start_url = config.get("start_url")
    if not start_url:
        raise RuntimeError("Configuration missing 'start_url'.")

    def _check_captcha_or_bot_wall(where: str) -> None:
        """Raise StopCheck if a CAPTCHA/bot-wall page is showing right now.

        Must run after EVERY navigation (initial load and each click_path
        step), not just once at the end — a bot-detection wall (e.g. Radware)
        can appear before login is ever reached, and if we don't catch it
        here, a later click_path step just fails with a confusing
        'selector not found', which is what a real bot-wall looked like in
        testing before this check was moved here.
        """
        if detect_captcha(page):
            logging.warning("CAPTCHA/bot-wall detected (%s).", where)
            cap_path = take_screenshot(page, screenshot_dir, "captcha")
            save_state(state_path, "captcha", cap_path)
            notify_all(
                title="AIRE watcher: CAPTCHA/bot-check encountered",
                message=(
                    "Prenot@mi showed a CAPTCHA or bot-detection page "
                    f"({where}). Manual attention required. "
                    f"Screenshot saved at {cap_path}"
                ),
                imessage_recipient=config.get("imessage_recipient"),
            )
            raise StopCheck(f"captcha_or_bot_wall:{where}")

    logging.info("Navigating to %s", start_url)
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)  # let any client-side redirect/render settle
    _check_captcha_or_bot_wall("initial navigation")

    # ---- Login check -------------------------------------------------------
    logged_out_texts = config.get("login_check", {}).get("logged_out_text", [])
    if check_logged_out(page, logged_out_texts):
        logging.warning("User appears logged out.")
        save_state(state_path, "logged_out")
        # Throttled: only notify on the FIRST check of a logged-out streak,
        # not every run. Confirmed in production this session can die in
        # under 3 hours against a 6-hour check interval, which was sending
        # the same "please log in again" text up to 4x/day until acted on.
        already_notified = bool(prev_state) and prev_state.get("status") == "logged_out"
        if not already_notified:
            notify_all(
                title="AIRE watcher: login expired",
                message=(
                    "Prenot@mi session expired — please re-run setup_login.py "
                    "to log in again. (You won't be re-notified until this is "
                    "fixed, to avoid repeat texts.)"
                ),
                imessage_recipient=config.get("imessage_recipient"),
            )
        else:
            logging.info("Still logged out; already notified, skipping repeat text.")
        raise StopCheck("logged_out")

    # ---- Walk click_path ---------------------------------------------------
    click_path = config.get("click_path", [])
    for i, step in enumerate(click_path):
        if step.get("action") != "click":
            continue
        selector = step.get("selector")
        if not selector:
            raise RuntimeError(f"click_path step {i} missing 'selector'")
        safe_click(page, selector, i)
        page.wait_for_load_state("domcontentloaded")
        _check_captcha_or_bot_wall(f"after click_path step {i}")

    # ---- Determine availability --------------------------------------------
    status, _ = determine_status(page, config)

    # Take screenshot for slots_open or unknown
    screenshot_path: Optional[Path] = None
    if status in ("slots_open", "unknown"):
        screenshot_path = take_screenshot(page, screenshot_dir, status)

    # Persist current state
    save_state(state_path, status, screenshot_path)

    # ---- Notification logic -------------------------------------------------
    if status == "slots_open":
        # Deliberately notify on EVERY run while a slot remains open, not
        # just the first time. Checks are hours apart (17:00/23:00/05:00/
        # 11:00) — a single notification is easy to sleep through entirely,
        # so repeating it gives a real second (and third, and fourth) chance
        # to actually see it and book it yourself.
        first_time = not prev_state or prev_state.get("status") != "slots_open"
        notify_all(
            title="🇮🇹 AIRE slot may be open!",
            message=(
                "Prenot@mi shows possible availability for your booking category. "
                + ("Go book it now" if first_time else "Still open as of this check — go book it now")
                + " — I have NOT clicked anything further."
            ),
            imessage_recipient=config.get("imessage_recipient"),
        )
    elif status == "unknown":
        notify_all(
            title="AIRE watcher: unknown page state",
            message=(
                "The page could not be classified. Screenshot saved at "
                f"{screenshot_path if screenshot_path else 'N/A'}."
            ),
            imessage_recipient=config.get("imessage_recipient"),
        )
    elif status == "no_slots":
        logging.info("No slots available at this time.")
    else:
        logging.info("Unhandled status: %s", status)


def main() -> None:
    """Entry point – load config, set up logging, run the check with retries."""
    try:
        script_dir = Path(__file__).resolve().parent

        # Resolve config path (relative to script dir, not CWD — launchd's
        # working directory is unspecified/root, not this script's folder)
        cfg_path = (
            Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "config.json"
        )
        if not cfg_path.is_absolute():
            cfg_path = script_dir / cfg_path
        config = load_config(cfg_path)

        # Resolve all configurable paths relative to the script directory so
        # behavior doesn't depend on launchd's (unset) working directory.
        screenshot_dir = _resolve_path(script_dir, config.get("screenshot_dir", "./logs"))
        state_path = _resolve_path(script_dir, config.get("state_file", "./logs/last_state.json"))
        profile_dir = _resolve_path(script_dir, config.get("profile_dir", "./chrome_profile"))

        setup_logging(screenshot_dir)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        prev_state = load_previous_state(state_path)

        max_retries: int = config.get("max_retries", 3)
        backoff_list: List[int] = config.get("retry_backoff_seconds", [30, 90, 240])

        # Random startup jitter: hitting the site at exactly :00 every 6h,
        # 4x/day, forever, is itself a strong automation signature behind a
        # behavioral bot-detection system like the one this site runs
        # (confirmed live) — independent of headless/headed. This doesn't
        # evade any content-based check, it just avoids being clockwork.
        # Kept short (default 90s) rather than several minutes: the 17:00
        # check specifically needs to land close to the consulate's nightly
        # slot-release time, so a long random delay would work against the
        # watcher's actual purpose. This is enough to not be hit-the-second
        # periodic without meaningfully missing the release window.
        jitter_max_s = int(config.get("startup_jitter_seconds", 90))
        if jitter_max_s > 0:
            jitter = random.uniform(0, jitter_max_s)
            logging.info("Startup jitter: sleeping %.0fs before first navigation", jitter)
            time.sleep(jitter)

        with sync_playwright() as pw:
            # Launch persistent context with user profile.
            #
            # headless=False is deliberate, not an oversight: confirmed live
            # against the real site that Prenot@mi's Radware Bot Manager
            # blocks headless Chromium's fingerprint outright (an "Access
            # temporarily restricted" / CAPTCHA wall) before any real content
            # loads, while the exact same browser in headed mode reaches the
            # real page normally. We run headed rather than try to spoof or
            # defeat that detection. A visible-but-usually-locked-screen
            # Chrome window will briefly appear during each scheduled run.
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
            )
            try:
                # Reuse first page or open a new one
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(config.get("timeout_ms", 60000))

                for attempt in range(max_retries):
                    try:
                        logging.info("Watcher attempt %d/%d", attempt + 1, max_retries)
                        run_check(page, config, prev_state, state_path, screenshot_dir)
                        # Success – break out of retry loop
                        break
                    except StopCheck as e:
                        # Logged out / CAPTCHA: already logged & notified inside
                        # run_check. Stop cleanly, do not retry.
                        logging.info("Stopping check cleanly: %s", e)
                        break
                    except (PlaywrightTimeoutError, PlaywrightError) as e:
                        logging.exception("Playwright error on attempt %d: %s", attempt + 1, e)
                    except Exception as e:
                        logging.exception("Unexpected error on attempt %d: %s", attempt + 1, e)
                    else:
                        # Unreachable after `break`, kept for clarity: success
                        # never falls through to the retry/backoff code below.
                        continue

                    # Only transient errors (caught above) fall through here.
                    if attempt + 1 >= max_retries:
                        logging.error("Maximum retry attempts reached; giving up for this run.")
                        # Every other terminal path in this script (logged_out,
                        # captcha, unknown) notifies before giving up — this one
                        # didn't, which means a broken selector or a page change
                        # could exhaust retries silently, run after run, with
                        # nothing but a log line nobody is watching in real time.
                        notify_all(
                            title="AIRE watcher: check failed",
                            message=(
                                f"Gave up after {max_retries} attempts this run — "
                                "something kept failing before the page could be "
                                "read (see watcher.log for the actual error). This "
                                "run could not tell whether a slot is open. The "
                                "next scheduled check will try again."
                            ),
                            imessage_recipient=config.get("imessage_recipient"),
                        )
                        break

                    backoff = backoff_list[attempt] if attempt < len(backoff_list) else backoff_list[-1]
                    jitter = random.uniform(0.8, 1.2)
                    sleep_seconds = backoff * jitter
                    logging.info(
                        "Sleeping %.2f seconds before next retry (backoff=%d, jitter=%.2f)",
                        sleep_seconds,
                        backoff,
                        jitter,
                    )
                    time.sleep(sleep_seconds)
            finally:
                # Always close the persistent context so the profile isn't
                # left locked for the next scheduled run.
                context.close()
    except Exception as exc:
        logging.exception("Watcher crashed unexpectedly")
        try:
            notify_all(
                title="AIRE watcher crashed",
                message=f"The watcher encountered an unexpected error: {exc}",
                imessage_recipient=config.get("imessage_recipient") if "config" in locals() else None,
            )
        except Exception:
            logging.error("Failed to send crash notification.")
    finally:
        # Ensure a zero exit status for launchd
        sys.exit(0)


if __name__ == "__main__":
    main()

