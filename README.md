# Ravenswatch Melody Overlay

Shows **all three melodies of your current run** directly over the in-game HUD —
including the two you haven't unlocked yet. Made for seed hunting.

![overlay screenshot](screenshot.png)

The names appear above the melody staff (bottom-right of the HUD), color-coded by
note count — green = 4 notes, orange = 5, red = 6 — with the currently active
melody underlined.

## Download

Grab `RavenswatchOverlay.exe` from the **[latest release](../../releases/latest)**.

## How to use

1. Double-click `RavenswatchOverlay.exe`
2. Accept the admin prompt (the overlay reads melody data from the game's memory,
   which requires admin rights)
3. That's it. Start Ravenswatch whenever — once you're in a run, the three run
   melodies fade in over the HUD staff. The overlay hides in the lobby and closes
   itself when you quit the game.

## Good to know

- **Windows only.** Tested at 1440p/2160p borderless fullscreen; sizes scale with
  the game window.
- **Game updates can break it.** Melody detection depends on the current Steam
  build of Ravenswatch. If a patch breaks it, the overlay simply shows nothing —
  check back here for an updated release.
- **SmartScreen warning:** the exe is unsigned, so Windows may show
  "Windows protected your PC" — click *More info* → *Run anyway*. Some antivirus
  tools flag packed exes as suspicious; that's a false positive.
- **Display-only.** The window is click-through and never takes focus — it can't
  interfere with your inputs. It only *reads* process memory (like an
  autosplitter) and touches no game files.
