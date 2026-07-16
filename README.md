# Ravenswatch Melody Overlay

See **all three Melodies of your run** the moment it starts — including the ones
you haven't unlocked yet.

![overlay close-up](screenshot.png)

## Why you'd want this

Each Ravenswatch run rolls **3 of the game's 12 Melodies**, but the game only
reveals them one at a time: you collect Notes (Magical Harps in Thieves' Stashes,
Reverie chests, killing Stingy Jack) to unlock the first Melody, then more Notes
for the second, then the third — never knowing what's coming next.

This overlay shows the full trio from the first second of the run.

### Hunting *Symphony of Reverie* (owned by 0.1% of players)

*Discover all the Melodies* is the **rarest achievement in the game** — 0.1%
global unlock rate on Steam. With 12 Melodies and only 3 per run, you can grind
Notes deep into a run just to discover it never contained a Melody you were
missing. With the overlay, you know instantly:

> Run starts → trio contains a Melody you're missing → **play it out.**
> Nothing new → **abandon and reroll.** Ten seconds per check instead of an hour.

### The real bottleneck: The Little Tailor

Eleven of the twelve Melodies move freely between the three slots. **The Little
Tailor** (5 notes — keeps consumables coming past max level) does not: it
**only ever appears as the third Melody**, the one you don't collect until
Chapter 3 (community reports and our own run sampling agree). That makes it the
melody most *Symphony of Reverie* hunts die on:

- A melody that can roll in any slot is in a given run ~3/12 = **25%** of the
  time. The Little Tailor competes for a single slot: ~1/12 ≈ **8%** of runs
  (assuming roughly uniform slot rolls).
- Expect **~12 runs on average** (median 8) before it shows up at all — and
  after 20 runs there's still a (11/12)²⁰ ≈ **17% chance you've never seen it**.
- Without the overlay, the only way to check a run is to fight all the way to
  the third Melody in Chapter 3. Every check costs you most of a run.
- It's also removed from the pool entirely in Single Chapter mode, so you
  can't shortcut the grind with short custom runs.

With the overlay, the same check costs ten seconds in Chapter 1: start the run,
glance at slot 3, reroll until the Tailor is there — then commit and play it out.

### Seed hunting & tool-assisted runs

The Melody trio is part of the run seed. If you're hunting a specific setup —
say **Fairy Godmother first** (4 notes, instant level up) for a speedrun route —
the overlay turns seed hunting into *restart → glance → keep or reroll*, a few
seconds per attempt. Same for verifying a known seed before a tool-assisted or
showcase run: the trio confirms you're on the right roll before you've taken a
single step.

## Reading the overlay

In the screenshot above, the run rolled (left to right = unlock order):

1. **Lady of the Lake** — green = 4 notes
2. **Otohime** — red = 6 notes
3. **Hansel & Gretel** — orange = 5 notes

Color is the note cost: **green = 4, orange = 5, red = 6**. As you unlock
melodies, the game's own HUD starts showing them on the staff — the overlay
hides those slots and only ever draws what the game still hides.

The overlay fades in over the melody staff at the bottom-right of the HUD, only
while you're in a run:

![where it appears on the HUD](hud-location.png)

## Download

Grab `RavenswatchOverlay.exe` from the **[latest release](../../releases/latest)**.

## How to use

1. Double-click `RavenswatchOverlay.exe` — no install, no admin prompt.
2. A **tray icon** (Fairy Godmother) appears in your system tray. That's your
   control center.
3. Start Ravenswatch whenever — once you're in a run, the melodies fade in over
   the HUD staff. The overlay hides in the lobby and closes itself when you quit
   the game.

**Right-click the tray icon** to:
- See the current run's three melodies at a glance
- Toggle the in-game overlay on/off
- Toggle song name labels on/off
- Exit the overlay

Only one instance can run at a time — double-clicking the exe again does nothing
if it's already running.

## Good to know

- **Windows only.** Tested at 1080p/1440p/2160p borderless fullscreen; sizes and
  labels scale with the game window. Long melody names wrap automatically.
- **Survives game patches.** Melody detection resolves addresses at runtime via
  RTTI, so it auto-adapts to new Ravenswatch builds. No need to wait for an
  updated release after a patch.
- **SmartScreen warning:** the exe is unsigned, so Windows may show
  "Windows protected your PC" — click *More info* → *Run anyway*. Some antivirus
  tools flag packed exes as suspicious; that's a false positive.
- **Display-only.** The window is click-through and never takes focus — it can't
  interfere with your inputs. It only *reads* process memory (like an
  autosplitter) and touches no game files. Reading a same-user process needs no
  admin rights, so the overlay never asks for elevation.
- **Unless Steam itself runs as administrator** (rare): then Windows blocks the
  read and the overlay tells you — right-click the exe → *Run as administrator*
  in that case.
- **Fair-play note:** this reveals information the game intentionally hides.
  Fine for achievement grinding, seed hunting, and tool-assisted/showcase
  content — your call whether it belongs in unassisted runs.

---

## Source & building it yourself

This repo is the full source ([MIT](LICENSE)). The overlay is part of a small
seed-hunting toolkit:

| Path | What it is |
|------|------------|
| `ravenswatch/overlay.py` | The overlay: native layered click-through win32 window (per-pixel alpha, no GUI toolkit) |
| `ravenswatch/rtti.py` | RTTI-based vtable discovery — auto-finds addresses across game builds |
| `ravenswatch/memory.py` | Reads the run's 3 melody GUIDs from game memory — how it works is documented in [CLAUDE.md](CLAUDE.md) |
| `ravenswatch/server.py` | Same overlay as an OBS Browser Source (`python -m ravenswatch serve`, port 18904) — for streams |
| `ravenswatch/flow.py`, `cli.py` | Run-cycling automation (start/abandon runs) for hands-free seed hunting |
| `tpi_decode.py`, `tpi_batch.py` | Decoder for the game's `.tpi` texture format — how `icons/` was extracted |

### Build the exe

```bash
pip install -r requirements.txt -r requirements-dev.txt
python build.py        # → dist/RavenswatchOverlay.exe
```

### Run from source

```bash
python -m ravenswatch overlay     # the overlay, no exe needed
python -m ravenswatch melodies    # print the run's melody trio as JSON
python -m ravenswatch serve       # OBS browser source at http://localhost:18904
```

Requires Python 3.11+ on Windows. Memory detection auto-resolves addresses via
RTTI at runtime (`rtti.py`), so it adapts to game patches. Field offsets within
objects are still hardcoded — those are stable across minor patches but would
need updating if class layouts change (documented in CLAUDE.md).

The melody icons in `icons/` are decoded from game assets and remain Passtech
Games' property — included only so the overlay can show in-game iconography.
