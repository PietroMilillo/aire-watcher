---
name: aire-watcher
description: Set up and run a slot-availability watcher for Italy's Prenot@mi booking portal — the one system every Italian consulate worldwide uses for AIRE registrations, anagrafe/birth registration abroad, passport renewal, citizenship, and other consular services. Use this skill whenever someone is stuck trying to book an Italian consulate appointment, says every slot is always full, asks about AIRE, anagrafe, Prenot@mi, "registering my kid as an Italian citizen abroad," or wants to be notified the instant a cancellation or new slot opens — even if they never say "watcher" or "skill." It never logs in for the user, never fills in a form, never clicks a confirm/submit/book step, and stops immediately on any CAPTCHA — it only watches and notifies; the human always does the actual booking, by hand, the moment they're told a slot might be open.
license: MIT
compatibility: claude-code
allowed-tools: [Bash, Read, Write, Edit, WebSearch, WebFetch, AskUserQuestion]
---

# AIRE / Prenot@mi appointment watcher

Prenot@mi (`prenotami.esteri.it`) is the booking portal every Italian consulate
on earth uses. Slots for popular services — AIRE registration, anagrafe
changes (including registering a child born abroad), passport renewal,
citizenship — get released in small batches and vanish in minutes. This
skill turns "keep refreshing the page and hope" into "get told the second a
slot might exist, then go book it yourself."

It was built for one real case — a birth registered with the Houston
consulate's anagrafe, same day the watcher first ran — and the underlying
code (`watcher.py`, `notify.py`, `setup_login.py`, `schedule_wakes.py`) is
unchanged for that. What *this file* adds is the part that only an AI agent
can do well: walking a new person through adapting it to *their* consulate
and *their* service, including researching what documents they'll actually
need to have ready and signed before a slot appears.

Read `README.md` first for what each file does and the full manual setup
steps — this file is about how you, the agent, should drive that setup for
someone, not a restatement of it.

## The rules that do not bend

This script runs against a real government portal, inside a real logged-in
session, on someone's own account. The reason it's safe to hand to a
stranger is that it is *structurally* incapable of doing anything but
looking and telling — not because it's been told to behave, but because the
code has no path to anything else. Keep it that way:

- **Never type a password, ever, for any reason.** `setup_login.py` opens a
  real browser window and a human logs in themselves — that step is not
  automatable and you should never try, even if asked, even "just this
  once." This matches the standing rule you already operate under: you do
  not enter credentials into forms.
- **Never add a `click_path` step that reaches a final booking action.**
  `watcher.py`'s `is_forbidden_click()` already refuses any click whose text
  or attributes contain confirm / conferma / invia / submit / "book now" —
  that's enforced in code, not just documented. When you help someone build
  their `click_path` (see `references/setup-walkthrough.md`), the same rule
  applies to *you*: only ever add steps that open a service's calendar/list
  view. If you can't tell whether a given button is "open the booking flow"
  or "finalize the booking," stop and ask the human — don't guess.
- **Never try to get past a CAPTCHA.** `detect_captcha()` stops the whole
  run the moment one appears, screenshots it, and notifies the human to
  handle it manually. Don't suggest headless mode, fingerprint spoofing, or
  anything else aimed at the bot-detection itself — `watcher.py`'s comments
  explain why headed mode is deliberate. The goal is never to look less like
  a bot; it's to behave like exactly what it is (a human's own browser,
  checking their own account) and let the slow stuff go slow.
- **There is no booking feature and there never should be one.** If someone
  asks you to make it book automatically, say no and explain why: a
  government appointment booked without the person in the loop is the kind
  of mistake that's very hard to undo, and the entire value of this tool is
  that it buys the human the time to do that one irreversible click
  themselves, deliberately.

## Setting this up for someone

Do these in order. Don't skip the document-research step to get to the fun
part faster — it's the thing this skill adds over just handing someone the
repo, and it's genuinely useful on its own even if they set up the rest by
hand later.

1. **Interview.** Which consulate (city/country — this only determines which
   services show up after they log in; the portal itself is the same for
   everyone), and which specific service are they trying to book? Get the
   exact service name as it appears in Prenot@mi if they know it — if not,
   that gets resolved in step 3.

2. **Research required documents, live, before anything else.** Web-search
   for that consulate's and that service's actual official requirements —
   what to bring, what must be signed, what must be an original vs. a copy.
   Present it as a checklist and say plainly what you could not confirm
   rather than filling a gap with a guess. Full guidance on doing this well
   — search strategy, common document categories, how to handle sources that
   disagree — is in `references/document-research.md`. Do this *before*
   touching any code, so the person has it in hand with time to prepare
   signatures, apostilles, or translations before a slot opens.

3. **Walk them through logging in** with `setup_login.py` (they log in
   themselves; remind them to check "Ricordami"/"Remember me" — a session
   without it can expire in under 3 hours). Then, in that same logged-in
   session, find the exact service and the exact "no slots" text for their
   case — `references/setup-walkthrough.md` has the concrete steps (how
   Pietro's own session found Houston's selectors is the worked example
   there). Use whatever browser automation your current session has access
   to (direct Playwright via Bash, or a browser tool) — the point is you're
   looking at the *real*, *live* page for their account, not guessing
   selectors from memory.

4. **Write their `config.json`** from `config.example.json`, filling in
   `start_url` (unchanged), `click_path`, `availability_selectors`, and
   `imessage_recipient`. Dry-run it once with them watching before scheduling
   anything.

5. **Schedule it.** On macOS this means `launchd` + `pmset` — see
   `references/macos-scheduling.md` for the real mechanics (macOS only
   allows one recurring wake time, which is why there's a second, self-
   re-arming piece for the evening check). **This scheduling piece is
   macOS-specific** — say so plainly if someone's on Linux or Windows; the
   watcher script itself has no OS dependency, but waking the machine from
   sleep on a schedule does, and that part hasn't been built or tested
   anywhere but macOS.

## Scope, honestly

This works for **any Italian consulate, for any service, because they all
run on the same Prenot@mi instance** — that's a strong, true claim, not a
stretch. It does *not* work for other countries' consulates, other visa or
DMV-style booking systems, or anything that isn't Prenot@mi: the "sold out"
text and the slot-calendar selectors in `availability_selectors` are
specific to how this one portal renders those states. Adapting this skill to
a different portal entirely would mean re-deriving those from scratch against
that site — don't claim it already handles that.
