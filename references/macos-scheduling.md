# Scheduling: macOS only, and why

The watcher script itself (Playwright + Python) has no OS dependency. This
part does — macOS's `pmset`/`launchd` is the only wake-from-sleep mechanism
this skill knows how to drive. On Linux or Windows, running on a schedule
is straightforward (`cron`, Task Scheduler), but *waking an otherwise-sleeping
machine* for that schedule is a different, OS-specific problem that hasn't
been built or tested here — say that plainly rather than implying this part
is portable.

For the exact commands (the `pmset repeat` call, the launchd `plist`
install, how to verify each one stuck), walk through the "Schedule the wake
times" and "Load the launchd job" sections of `README.md` together with the
person — they're already written as copy-pasteable steps and don't need
restating here.

## The one thing that's genuinely different for every person: the time

`pmset repeat wakeorpoweron` only supports **one recurring wake time total**
— calling it again replaces the previous one rather than adding to it. The
original setup works around this with two pieces: one permanent repeating
wake (05:00, the worst-case overnight gap) and one self-re-arming one-shot
wake (`schedule_wakes.py`, run daily by its own root LaunchDaemon) for the
evening check — because the evening check time is the one that actually
matters most, and it is **not the same clock time for everyone**.

Prenot@mi releases new slots at local midnight *in Italy*. For Houston
(Central time), that's 17:00 or 18:00 depending on whether Italy and the US
are both observing daylight saving at that moment — their DST calendars
don't flip on the same dates, so the offset itself shifts by an hour for a
few weeks each spring and fall. **Recompute this for the person's actual
time zone — don't copy 17:00 from the Houston example.** Work out their
UTC offset, Italy's current UTC offset (CET = UTC+1, CEST = UTC+2), and set
`TARGET_TIMES` in `schedule_wakes.py` accordingly. If they're somewhere the
offset makes Italian midnight land at an inconvenient hour (say, 2–4am
their time), tell them that plainly too — there's no way around the portal's
own release schedule, only around sleeping through it.
