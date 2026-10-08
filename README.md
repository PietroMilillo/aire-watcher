# AIRE / Prenot@mi appointment watcher

Checks a Prenot@mi booking portal 4x/day for open slots and notifies you the
moment one might be open. It never logs in for you, never solves a CAPTCHA,
and never books anything — it only watches and notifies. Prenot@mi is the
one booking system every Italian consulate worldwide uses, so the same code
works for any consulate and any service — this exact setup was first built
and run, start to finish, in one evening against the Houston consulate's
**"Registrazione Nascite per casi A1, A2, o B"** (registering a birth with
the anagrafe), which is why that's still the live example throughout this
README and in `config.example.json`.

## This is also a Claude Skill

Beyond running it yourself by hand, there's a `SKILL.md` in this repo: point
an AI coding agent (Claude Code or similar) at it and it can walk a *different*
person through adapting this to *their* consulate and service — including
researching, live, what documents that specific service requires and which
of them need to be signed, before any setup starts. See `SKILL.md` and
`references/` for how that works; everything below is still the plain,
do-it-yourself manual version.

## What's in here

| File | What it does |
|---|---|
| `setup_login.py` | Run **once, by hand**. Opens a real Chrome window you log into yourself. Saves the session to `chrome_profile/`. |
| `watcher.py` | The actual check. Reuses `chrome_profile/`, navigates to the service, detects sold-out vs. maybe-open vs. logged-out, notifies you. |
| `notify.py` | macOS notification + iMessage helper. Can be run standalone to test notifications. |
| `config.json` | Real config (the one `watcher.py` reads). **You must edit `imessage_recipient` before first use.** |
| `config.example.json` | Documented template with comments explaining every field. |
| `com.pietro.airewatcher.plist` | launchd job that runs `watcher.py` at 17:00 / 23:00 / 05:00 / 11:00 Central every day. |
| `schedule_wakes.py` | Run daily as root. Arms a one-shot wake for that day's 17:00 check (on top of the permanent 05:00 `pmset repeat` wake). |
| `com.pietro.airewatcher.wakeschedule.plist` | Root LaunchDaemon that runs `schedule_wakes.py` daily at 05:10. |
| `logs/` | `watcher.log` (rotating), `last_state.json` (last observed status), screenshots. |

## Safety guarantees (enforced in code, not just promised)

- **Never types a password.** `watcher.py` never calls `.fill()`/`.type()` on
  anything — it only clicks the two navigation steps in `config.json`'s
  `click_path`. Logging in is a separate, human-only step (`setup_login.py`).
- **Never clicks confirm/submit/book.** Any click whose visible text or
  attributes contain confirm / conferma / prenota's booking-final variants /
  invia / submit / "book now" is refused in code — see `is_forbidden_click()`
  in `watcher.py`. (Note: the *service list's* "Prenota" button is fine to
  click — it only opens that service's booking flow, it isn't the final
  booking confirmation.)
- **Never touches a CAPTCHA.** If one is detected, the run stops immediately,
  screenshots, and notifies you that it needs manual attention.
- **Never books.** There is no code path that reaches a final
  confirm/submit — the most it ever does is notify you to go book it
  yourself.

## One-time setup

### 1. Fill in `config.json`

Open `config.json` and set `imessage_recipient` to your Apple ID email or
phone number (whatever your Mac's Messages app uses for iMessage). Everything
else is already filled in from the real portal — see the `_comment` fields in
`config.example.json` if you want the details.

```bash
open -e /Users/pmilillo/Documents/sw/aire_watcher/config.json
```

### 2. Log in once, by hand

```bash
cd /Users/pmilillo/Documents/sw/aire_watcher
.venv/bin/python setup_login.py
```

A real Chrome window opens to Prenot@mi. **Log in yourself** — this script
never touches the login form. Once you see your account (top-right shows
"Pietro Milillo"), come back to the terminal and press Enter. That saves the
session into `chrome_profile/` so future runs don't need you present.

This session can expire after some weeks — if it does, `watcher.py` will
detect it, notify you, and skip retrying. Just re-run this step.

### 3. Dry run

```bash
.venv/bin/python watcher.py config.json
```

Watch the output. It should navigate, click through to the A1/A2/B service,
and either:
- log "No slots available" (the current real state, confirmed live today), or
- notify you if something changed.

Check `logs/watcher.log` and look at any screenshot in `logs/` to confirm it
actually reached the right page.

### 4. Schedule the wake times — real constraint, read this

I checked `man pmset` against the actual request (wake for all 4 check
times): **macOS's `pmset repeat` only supports one recurring wake time total**
(`pmset repeat wakeorpoweron <weekdays> <time>` — calling it again *replaces*
the previous one, it doesn't add to it). There's no single command that gives
you 4 daily recurring wakes.

We're using both pieces together, since 05:00 and 17:00 matter for different
reasons (05:00 is the worst-case overnight gap; 17:00/midnight-Italy is when
the consulate actually releases new slots each night):

**05:00 — permanent repeating wake.** One command, needs your admin password
once (already done):

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 05:00:00
```

Verify it stuck:
```bash
pmset -g sched
```

**17:00 — self-re-arming one-shot wake.** Since `pmset repeat` can't hold a
second time, `schedule_wakes.py` uses `pmset schedule wake "MM/dd/yy
HH:mm:ss"` (a one-shot wake) to queue that day's 17:00, and a small root
`LaunchDaemon` (`com.pietro.airewatcher.wakeschedule.plist`) re-runs it daily
at 05:10 — right after the 05:00 repeat wake, so the Mac is reliably already
awake when it fires. This needs root because `pmset` does; install it with:

```bash
sudo cp com.pietro.airewatcher.wakeschedule.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.pietro.airewatcher.wakeschedule.plist
sudo chmod 644 /Library/LaunchDaemons/com.pietro.airewatcher.wakeschedule.plist
sudo launchctl load /Library/LaunchDaemons/com.pietro.airewatcher.wakeschedule.plist
```

`RunAtLoad` is set, so this also arms **today's** (or tomorrow's, if past
17:00 already) wake immediately on install — no need to wait for tomorrow's
05:10 cycle.

Verify a one-shot wake got queued:
```bash
pmset -g sched
```
You should see both the permanent 05:00 repeating entry and a one-time
"wake at <date> 17:00:00" entry (owner `airewatcher`).

11:00 and 23:00 aren't separately covered — your Mac is realistically awake
for those in normal use, and if it's asleep for a given check anyway, that
run is simply skipped (no crash, no partial state) and the next scheduled
run picks it back up.

### 5. Load the launchd job

```bash
cp com.pietro.airewatcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.pietro.airewatcher.plist
```

Confirm it's loaded:
```bash
launchctl list | grep airewatcher
```

It will now run automatically at 17:00, 23:00, 05:00, and 11:00 Central every
day — no need to keep a terminal open.

## Checking on it

```bash
tail -f logs/watcher.log            # live log
cat logs/last_state.json            # last observed status + timestamp
open logs/                          # browse screenshots
```

## Stopping it

```bash
launchctl unload ~/Library/LaunchAgents/com.pietro.airewatcher.plist
rm ~/Library/LaunchAgents/com.pietro.airewatcher.plist
```

To also stop the wake scheduling:
```bash
sudo pmset repeat cancel
sudo launchctl unload /Library/LaunchDaemons/com.pietro.airewatcher.wakeschedule.plist
sudo rm /Library/LaunchDaemons/com.pietro.airewatcher.wakeschedule.plist
sudo pmset schedule cancelall
```

## When it notifies you

You'll get a macOS banner and an iMessage. **Go to Prenot@mi and book it
yourself** — the watcher does not book, and it does not click anything past
opening the service's booking flow. Slots go fast (we watched it sell out
live during setup), so don't wait once notified.
