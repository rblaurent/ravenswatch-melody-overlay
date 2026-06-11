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
- `ravenswatch/melody_data.py` — All 12 melody definitions with note counts and effects
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
python -m ravenswatch melodies        # Read melodies from memory
python -m ravenswatch start-run       # From lobby: click PRÊT, wait for loading
python -m ravenswatch restart         # From in-game: abandon run, return to lobby
python -m ravenswatch restart --start # Abandon + immediately start a new run
```

Add `--screenshots` to `start-run` or `restart` to save a screenshot at each step.

All commands output JSON for easy parsing by AI tools.

## Melody detection (game version dependent!)

### What works: active melody detection
`python -m ravenswatch melodies` identifies the melody currently being unlocked (the one
shown in the HUD with a "0/N" counter). It uses the MelodyUiViewerEntityCpnt (vtable RVA
0xf295a0), finds which MelodyEntityCpnt it references, then follows a pointer chain to
extract the internal resource name.

Pointer chain: `cpnt+0x08 → entity+0x28 → B+0x70 → C+0x48 → D+0x18 → name string`

This gives us ONE melody per run. We cannot yet read all three run melodies from memory.

### What doesn't work (yet)
- MelodyEntityCpntSettings slot reading (names don't resolve reliably)
- MelodyDefinition 3-vs-9 split scanning (no clean split found)
- Reference counting across definitions (all show equal refs)

### Key vtable RVAs
- MelodyUiViewerEntityCpnt: 0xf295a0 (the one that works)
- MelodyEntityCpnt: 0xed2320
- MelodyEntityCpntSettings: 0xf1d048

### All 12 melodies
- 4 notes: Fairy Godmother, Tortoise, Lady of the Lake, Galahad
- 5 notes: Merry Men, Goose Girl, Hansel & Gretel, Little Tailor
- 6 notes: Lucky Hans, Otohime, Long John Silver, Sheherazad

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

## Dependencies
- Python 3.12+
- `mss` for screenshots
- Windows only (ctypes win32 APIs)
- Admin required for memory reading

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
