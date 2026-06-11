# Ravenswatch GDQ Tools

## What this is
Automation tools for Ravenswatch speedrun seed hunting. Built for GDQ overlay + seed watcher.
AI agents can use these tools to control the game, take screenshots, read memory, and cycle through runs.

## Game location
The game lives at `G:\SteamLibrary\steamapps\common\Ravenswatch\` (Steam app 2071280).
This project contains only tools and scripts, not the game itself.

## Architecture
- `ravenswatch/process.py` — Find/launch game, window management (ctypes win32)
- `ravenswatch/controller.py` — Screenshot, click, keyboard input relative to game window
- `ravenswatch/flow.py` — Game flow automation: start runs, abandon runs, navigate menus
- `ravenswatch/memory.py` — Read melody data from game process memory (reverse-engineered offsets)
- `ravenswatch/melody_data.py` — All 12 melody definitions with note counts, effects, icon filenames
- `ravenswatch/overlay.py` — In-game melody overlay: native layered click-through win32 window
  (UpdateLayeredWindow, per-pixel alpha, frames composed with Pillow — no GUI toolkit)
- `ravenswatch/server.py` — OBS browser-source HTTP server (stdlib http.server, port 18904)
- `ravenswatch/resources.py` — Icon path resolution, works in dev and PyInstaller-frozen mode
- `ravenswatch/cli.py` — CLI interface for all operations

## Usage
```bash
python -m ravenswatch status          # Is the game running?
python -m ravenswatch launch          # Launch via Steam
python -m ravenswatch screenshot      # Capture game window → screenshots/
python -m ravenswatch screenshot name # Capture with a specific filename
python -m ravenswatch click 500 300   # Click at window coords
python -m ravenswatch click-rel 0.5 0.5  # Click at relative position
python -m ravenswatch key escape      # Press ESC
python -m ravenswatch melodies        # Read all 3 run melodies (+ active) from memory
python -m ravenswatch overlay         # Live overlay: 3 melody icons over the HUD staff dots
python -m ravenswatch serve           # OBS browser source at http://localhost:18904
python -m ravenswatch start-run       # From lobby: click PRÊT, wait for loading
python -m ravenswatch restart         # From in-game: abandon run, return to lobby
python -m ravenswatch restart --start # Abandon + immediately start a new run
```

Add `--screenshots` to `start-run` or `restart` to save a screenshot at each step.

All commands output JSON for easy parsing by AI tools.

## Melody detection (game version dependent!) — SOLVED, all 3 melodies

`python -m ravenswatch melodies` returns ALL THREE run melodies in unlock order
(slot 1 = first/active at run start) plus which one is currently active. Returns
`melodies: null` when in the lobby / not in a run.

### How all-3 detection works (`MemoryReader.read_run_info()`)
The hero controller's scene context stores the run's predetermined melody asset
GUIDs in three consecutive 16-byte slots:

```
hero    = vtable scan for RVA 0xf2b930 (2 pooled instances; one per player)
context = *(*(hero+0x08) + 0x30)        # null when that hero isn't in a run
guids   = context+0x760 .. +0x78f       # 3 x 16-byte melody asset GUIDs, unlock order
```

GUIDs resolve to melodies via the static registry of the 12 base MelodyEntityCpnt
instances at module RVA 0x14388c8 (`{cpnt** buffer, u32 count}` — no scan needed).
Each base cpnt → entity (+0x08) → B object (+0x28); B carries the asset GUID at
B+0x1c8 and the name chain `B+0x70 → C+0x48 → D+0x18 → path string` (e.g.
`...\Grant_Damage_Overtime.entity.ot`).

Per-slot STATE comes from the spawned MelodyEntityCpnt lifecycle field at
cpnt+0x68 (1 = being collected, 2 = completed), reached through the
linked-melody array at hero+0x13a0 (`{cpnt** buffer}`, u32 count at +0x13a8)
of EVERY hero — max state per melody across heroes, because in multiplayer a
single hero's array can lag (observed: HUD showed melody 1 active ~20 s
before any hero's array linked it). `read_run_info()` returns
`(melodies, states)` with states[i] in {0 = not started, 1 = active,
2 = completed}. Lobby detection: context is null or its +0x760 slots don't
match any known melody GUID.

### Active-only detection (legacy, still works)
`read_active_melody()` uses the MelodyUiViewerEntityCpnt (vtable RVA 0xf295a0),
finds which MelodyEntityCpnt it references, then follows the name chain
`cpnt+0x08 → entity+0x28 → B+0x70 → C+0x48 → D+0x18 → name string`.

### Completion detection (SOLVED 2026-06-11, shipped v1.0.2)
The pre-v1.0.2 approach (ACTIVE = last element of the linked array) had two
bugs: melody 3 read "active" forever after completion (nothing links after
it), and multiplayer mistracked (per-hero arrays lag). Both fixed by the
per-melody lifecycle field at cpnt+0x68.

Evidence (`scratch/watch_completion.py` log, MP session 2026-06-11): Galahad's
cpnt +0x68 went 1→2 at the exact poll where Long John Silver linked, and LJS
went 1→2 exactly when Little Tailor linked. Caveat: melody-3 completion itself
has not been directly observed (the run was stopped before) — the fix
extrapolates the same lifecycle to slot 3; the watcher script remains in
scratch/ if it ever needs re-verification.

The overlay hides state-2 slots (the game HUD draws them itself) with a
two-reads debounce against transient misreads, underlines the state-1 slot,
and hides the whole window once all three are completed.

Other findings from the investigation, for the record:
- HeroMelodyPersistentData records (vtable 0xf0dc20) are created when a melody
  LINKS (run start, 0 notes) and are destroyed on run end — run-scoped link
  records, not completion or compendium data.
- MelodyUiViewerEntityCpnt holds the active cpnt pointer at +0x68; clears on
  run end. Not used by the fix.
- The HUD "0/N" current-note counter was never located (nothing in the dumped
  cpnt ranges changed while notes were collected).

### Dead ends (kept for the record)
- MelodyEntityCpntSettings slot reading (names don't resolve reliably)
- MelodyDefinition 3-vs-9 split scanning (no clean split found)
- "Live trio" via spawned cpnt +0x64/+0x6c fields: FALSE LEAD — spawned cpnt
  instances are pooled per melody and those fields linger after a run ends.
  Spawned entities are also created lazily (melody 2/3 may not exist early on).
- Hero+0x13a0 array never holds all 3: melodies are linked one at a time.
- Scene data melody list (sceneData+0xc8/+0xd0, vtable RVA 0xf05958) and
  HeroMelodyPersistentData records (vtable RVA 0xf0dc20): only contain melodies
  already linked, not the full predetermined trio.

### Key RVAs (Ravenswatch.exe, current Steam build)
- Hero controller vtable: 0xf2b930 (melody array +0x13a0, count +0x13a8)
- Base MelodyEntityCpnt registry (static data): 0x14388c8
- MelodyUiViewerEntityCpnt vtable: 0xf295a0
- MelodyEntityCpnt vtable: 0xed2320 (spawned-instance lifecycle state at
  +0x68: 1 = being collected, 2 = completed)
- MelodyEntityCpntSettings vtable: 0xf1d048
- HeroMelodyPersistentData vtable: 0xf0dc20 (0x20-byte inline records:
  {vtable, guid_lo, guid_hi, P}; P+0x18 → B)

### All 12 melodies
- 4 notes: Fairy Godmother, Tortoise, Lady of the Lake, Galahad
- 5 notes: Merry Men, Goose Girl, Hansel & Gretel, Little Tailor
- 6 notes: Lucky Hans, Otohime, Long John Silver, Sheherazad

## Melody selection rules (investigated 2026-06-11)

Question: does Little Tailor get special treatment in run-melody selection?
Answer: YES, three independent confirmations.

### 1. Blocking game modifiers (read from MelodyDefinition data, verified live)
Each MelodyDefinition carries a custom-flag filter listing the custom-mode
modifiers that REMOVE it from the selection pool (so its effect can't be
obsolete under that mode):

| Melody | Blocked by modifier | Reason |
|---|---|---|
| Little Tailor | **OneChapter** (Single Chapter mode) | consumables-past-level-10 needs a long run |
| Long John Silver | NoMinimap | reveals the map |
| Lady of the Lake | NoFountains | fountain bonus |
| Galahad | NightOnly (+2 more entries) | heals on day/night transitions |
| Otohime | NoBossTimer (+1 more) | slows hourglass |
| Hansel & Gretel | NoBossTimer | boss DoT tied to timer |
| other 6 | none | — |

In default GDQ settings (no custom modifiers) none of these blocks apply.

### 2. Slot restriction (community + our observations, not found in def data)
Steam community reports: Little Tailor only ever appears as the THIRD melody;
Fairy Godmother only 2nd or 3rd; both are rare. Our 9 sampled trios agree:
LT appeared once — in slot 3 (run trio Merry Men / Hansel & Gretel / Little
Tailor); FG appeared once — in slot 3. Every other melody moved freely between
slots (e.g. Galahad seen in slots 1, 2 and 3). The slot gating is NOT encoded
in MelodyDefinition fields (full diff found nothing) — it most likely lives in
per-chapter melody pools in the quest/scene assets. No meta-unlock is needed:
LT rolled on a fresh profile.

### 3. Extra effect entities (definition data)
Only two defs have entries in the extra-entity-resources list (def+0x310 ptr,
count at +0x318): Little Tailor → {Hero_Drop_Bag, Minimap_Reveal_Ping}
(consumables drop in a bag + map ping), Merry Men → {Remove_Key_Requirement_
Host_Effect}. Effect plumbing, not selection — but it confirms these two are
the "special-cased" melodies in the data.

### Reverse-engineering notes (for the next session)
- TRUE MelodyDefinition base = *(base_cpnt + 0x168). PITFALL: the vtable scan
  for RVA 0xf25888 hits the SECONDARY vtable at def+0x288 — all offsets in a
  scan-based dump are shifted by +0x288.
- Useful def fields (from true base): +0x310/+0x318 extra-resources list,
  +0x320 note count (4/5/6 — good identity check), +0x328 oCCustomFlagFilter
  {+0x330 list1 buf/cnt +0x338/0x340, +0x348 list2 buf/cnt +0x350/0x358};
  list entries are 16 bytes {hash, char* modifier_name}. List2 = blocking
  modifiers.
- RTTI works on this binary: *(vtable-8) → COL, u32 at COL+0xc = TypeDescriptor
  RVA, name string at TD+0x10 (".?AV<name>@@"). Fastest way to identify any
  object: read its vtable, resolve the class name.
- `cycle_runs.py N` (repo root) cycles N runs and logs each trio as JSON
  lines — used for the slot statistics; reads are flaky during loading
  screens (~30% null), just take more samples.

## .tpi texture format (SOLVED)

DarkTales `.tpi` files are serialized `oCTexture` objects. The melody icon set lives in
`G:\SteamLibrary\steamapps\common\Ravenswatch\DarkTalesResources\_Cooking\Jd\Hqlrtdqv\`.
Decoder: `tpi_decode.py` (single file) / `tpi_batch.py` (whole directory → `icons/`).
Decoded melody icon PNGs are already in `icons/`.

Layout:
- 193-byte header: width uint32 @137, height uint32 @141, format enum uint32 @149
  (5 = BC3/DXT5), pixel-data byte size uint32 @153 (duplicated @157)
- pixel data: **standard BC3 (DXT5)** blocks, row-major — nothing custom
- 7-byte serialization footer at end of file

Gotcha: the obvious split (filesize − datasize = offset 200) is WRONG — data starts at
193, and a 7-byte misalignment yields shape-correct but color-scrambled decodes.
Safest is anchoring from the end: `data[-(7+size):-7]`.

Cooked file/dir names use a fixed monoalphabetic substitution cipher (see
`DECODE_LOWER`/`DECODE_UPPER` maps in `tpi_batch.py`). Examples:
`Hqlrtdqv` = Melodies, `JX_Hqlrts_Xbrz_Kglgngt.jzy.Qqpiwuq.tpi` =
UI_Melody_Icon_Galahad.png.Texture.tpi. Icon names ↔ melodies: Godfairy=Fairy
Godmother, Turtle=Tortoise, LadyLake, Galahad, MerryMen, Goose=Goose Girl,
Hansel=Hansel & Gretel, Tailor=Little Tailor, LuckyHans, OtoHime, LongJohnSilver,
Sherazade=Sheherazad (plus UI extras: Hover, bg, Locked, Locked_bg).

## Distribution

### Standalone overlay exe (for runners — no Python needed)
```bash
pip install -r requirements.txt -r requirements-dev.txt
python build.py            # → dist/RavenswatchOverlay.exe (~17 MB, onefile)
python build.py --debug    # also builds a console debug exe for testing
```
Double-click the exe → it waits for the game, shows melodies during runs,
hides in the lobby, and exits when the game closes. A toast at startup confirms
it's running. No UAC: same-user PROCESS_VM_READ needs no elevation (since
v1.0.3; if Steam itself runs elevated, the overlay shows a run-as-admin hint
toast after ~12 s). Build config: `RavenswatchOverlay.spec` (bundles `icons/`,
exe icon generated from the Fairy Godmother PNG by `build.py`).

The overlay window is a native layered click-through topmost window — it never
steals focus or mouse input and works over borderless fullscreen. Text/icons
scale with the game window height (tuned at 2160p).

### Publishing to players
Public repo: https://github.com/rblaurent/ravenswatch-melody-overlay — full
source (this repo pushes there as `origin`) + player README + exe release
assets. To ship a new version:
```bash
python build.py
gh release create vX.Y.Z dist/RavenswatchOverlay.exe --repo rblaurent/ravenswatch-melody-overlay --title vX.Y.Z --notes "..."
```
Stable download link for Discord etc.:
https://github.com/rblaurent/ravenswatch-melody-overlay/releases/latest

### OBS browser source (for streams)
```bash
python -m ravenswatch serve [--port 18904] [--host 127.0.0.1]
```
Add `http://localhost:18904` as an OBS Browser Source (suggested 900x320).
Transparent background; icons, note-count color coding (green=4, orange=5,
red=6), active melody pulses. Page polls `/data` every 2 s; a background
thread reads memory every 3 s so HTTP requests never trigger memory scans.
Endpoints: `/` (page), `/data` (JSON), `/icons/<png>` (whitelisted).

## Dependencies
- Python 3.11+
- `mss` for screenshots, `Pillow` for icons/overlay rendering (requirements.txt)
- `pyinstaller` for building the exe (requirements-dev.txt)
- Windows only (ctypes win32 APIs)
- No admin needed for memory reading (same-user PROCESS_VM_READ) — unless the
  game itself runs elevated (Steam as admin), then run the tools elevated too

## Game flow (for AI agents)

The game UI is in FRENCH. There are 4 game states with distinct screens:

### 1. Lobby (character select)
- Shows an open book with character on the left, settings on the right
- **PRÊT** button bottom-right = start the run
- You land here after launching the game or finishing/abandoning a run

### 2. In-game
- Isometric gameplay view with HUD (health bar, abilities, minimap)
- This is where you stay while playing / checking seeds
- Press **ESC** to open the pause menu

### 3. Pause menu (overlay on in-game)
- Three stacked buttons center-screen: **Continuer** / **Paramètres** / **Abandonner**
- Click **Abandonner** to quit the current run

### 4. End screens (after abandoning)
- **Confirmation dialog**: "Voulez-vous vraiment quitter?" → click **Ok**
- **Defeat screen** ("Défaite"): score summary → click **Récompenses** (bottom-right)
- **Rewards screen** ("Récompenses"): character + rewards → click **Fin** (bottom-right)
- After Fin you're back at the **Lobby**

### Typical AI workflow
```
# 1. Launch game (if not running) and wait for lobby
python -m ravenswatch launch

# 2. Start a run from the lobby
python -m ravenswatch start-run

# 3. You're now in-game. Take screenshots, read melodies, do your thing.
python -m ravenswatch screenshot
python -m ravenswatch melodies

# 4. When done with this seed, abandon and go back to lobby
python -m ravenswatch restart

# 5. Start next run when ready
python -m ravenswatch start-run

# Or combine steps 4+5 in one command:
python -m ravenswatch restart --start
```

### Button positions (relative coords, resolution-independent)
These are the click targets used by `flow.py`. All coords are (rx, ry) where 0.0 = top-left, 1.0 = bottom-right.

| Screen | Button | Coords | Notes |
|--------|--------|--------|-------|
| Lobby | PRÊT | (0.698, 0.795) | Starts the run |
| Pause menu | Abandonner | (0.50, 0.524) | Bottom of 3 stacked buttons |
| Confirmation | Ok | (0.41, 0.63) | Left button; Retour is right |
| Defeat screen | Récompenses | (0.85, 0.96) | Bottom-right tab |
| Rewards screen | Fin | (0.90, 0.96) | Bottom-right, returns to lobby |

### Important notes for AI sessions
- **Always activate the venv first**: `.\.venv\Scripts\Activate.ps1`
- **Take a screenshot after every action** to verify the game state. Don't assume a click worked.
- **Window focus**: the game must have focus for clicks to register. The flow functions handle this automatically, but if using raw `click-rel` commands, run `python -m ravenswatch focus` first.
- **Loading times**: after clicking PRÊT, the game takes ~12-15 seconds to load into gameplay. After clicking Ok on the confirmation dialog, the unloading transition takes ~5 seconds.
- **The game is fullscreen** at whatever the monitor resolution is (e.g. 3840x2160). Relative coordinates work regardless.
