# Finding your own selectors, live

`config.json`'s `click_path` and `availability_selectors` are the only
things that differ between one person's setup and another's. Everything
else — `start_url`, the overall flow, the safety checks — is already
generic. This is how to derive those four fields for a specific person,
using the worked example (Houston, "Registrazione Nascite per casi A1, A2,
o B") that's already annotated in `config.example.json`'s `_comment` fields
as the template for how to reason about a new one.

## 1. Log in together

Run `setup_login.py`. The human logs in themselves — remind them to check
"Ricordami"/"Remember me" if it's offered; without it, the session can
expire in under three hours, which is shorter than the gap between
scheduled checks. Once they can see their account, the session is saved to
`chrome_profile/` and you can reuse it for the next steps without asking
them to log in again mid-setup.

## 2. Find the real service name

From the logged-in session, navigate: click "Prenota" in the nav, which
lands on `/Services` — a table listing every service *that consulate*
offers. Find the row whose text matches the service the person described in
the interview step. Use the row's exact visible text (not a paraphrase) —
`click_path` selects by text, so it has to match character-for-character
what's actually on the page right now, not what you'd expect it to say.

```json
{ "action": "click", "selector": "tr:has-text('EXACT ROW TEXT') >> text=Prenota" }
```

Clicking that row's own "Prenota" button only opens *that service's*
booking/calendar flow — it is not a final booking confirmation, so it's
fine for `watcher.py`'s safety checks. (The literal word "prenota" is
deliberately *not* in the forbidden-click list for this reason — see
`watcher.py`'s `FORBIDDEN_CLICK_WORDS` and its comment.)

## 3. Capture the real "sold out" text, verbatim

Whatever the page shows for "no slots," copy it exactly — including
capitalization quirks — into `availability_selectors.no_slots_text`. Partial
matches are fine (the check is case-insensitive substring matching), but the
substring itself has to be real text you saw on the real page, not a
guess at what a sold-out message "probably" says.

## 4. Build the slot-candidate selector — conservatively

If you get to see what the calendar looks like when slots genuinely exist,
inspect its HTML and write a selector that matches an available day/slot
element. If you *don't* get to see that during setup (the common case —
popular services are sold out almost always, which is the whole reason this
tool exists), write your best-effort guess from how the calendar widget is
built, but don't worry about getting it perfect: the status logic is
deliberately asymmetric on purpose —

- sold-out text present → `no_slots` (logged quietly, no notification)
- sold-out text absent *and* the slot selector also finds nothing → `unknown`
  (always notifies, with a screenshot, for a human to check)

So a wrong or incomplete `slot_candidate_selector` can cause an extra,
unnecessary notification — never a missed real opening. Keep that asymmetry
when you adapt this; don't "fix" it by making `unknown` quieter.

## 5. Write the config and dry-run it

Copy `config.example.json` to `config.json`, fill in the fields above plus
`imessage_recipient`, then run `watcher.py config.json` once with the person
watching. Confirm in `logs/watcher.log` and the screenshot in `logs/` that
it actually reached the right page and classified the right status — don't
schedule anything until you've both seen one real, correct run.
