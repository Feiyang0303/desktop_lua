# Luca — Desktop Dog Pet

A small floating, draggable desktop pet of Luca the dog. Built with PyQt6.

## Features

- Frameless transparent window that floats on top of your desktop
- Smooth, continuous animation:
  - Sin-wave breathing bob while idle/sitting
  - Parabolic jump arcs with squash-and-stretch during excitement
  - Step-bounce with a slight body tilt while walking
  - Gentle belly-breathing scale while sleeping
- Interactive behaviors:
  - **Single click (tap)** — put Luca to sleep, or wake him up if he's asleep
  - **Left-click + drag** — pick him up; he gets excited while held and
    settles back to idle when released
  - **Double-click** — happy celebration jump
- Particle overlays:
  - Floating animated **Zzz** rise above his head while sleeping
  - Floating **hearts** drift up while he's excited
- Animated sprites for several movements:
  - Idle, Walking around (wanders the screen and bounces off edges),
    Sitting, Sleeping (curled up), Excited / jumping
- Auto-behavior brain: Luca decides what to do every few seconds (right-click
  menu to toggle off if you want full control)
- Right-click menu to pick a movement, switch art style, flip direction,
  toggle auto-behavior, toggle always-on-top, or quit

## Quick start

```bash
./run.sh
```

The first run will create a virtualenv and install dependencies. Subsequent
runs just launch the app.

## Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python luca.py                # default style (chibi)
python luca.py --style chibi
python luca.py --style realistic
```

You can also switch styles live from the right-click menu under
"Art style".

## Project layout

```
luca.py                       # Main app: window, animations, behavior
assets/
  chibi/                      # Chibi/kawaii sticker style of real Luca
    luca_idle.png luca_walk1.png luca_walk2.png
    luca_sit.png  luca_sleep.png luca_happy.png
    luca_*_raw.png            # original chroma-keyed sources
  realistic/                  # Semi-realistic painted style of real Luca
    luca_idle.png luca_walk1.png ...
  refs/                       # Reference photos of real Luca
tools/process_sprites.py      # Strip green background + crop tight
requirements.txt
run.sh                        # Convenience launcher
```

## Replacing the artwork

Each style is just a folder under `assets/` that contains the six required
sprite files. To add a new style (e.g. `pixel`):

1. Create `assets/pixel/`
2. Drop transparent PNGs named `luca_idle.png`, `luca_walk1.png`,
   `luca_walk2.png`, `luca_sit.png`, `luca_sleep.png`, `luca_happy.png`
   into it
3. Restart the app — the new style will appear in the right-click menu

If you start from chroma-keyed `*_raw.png` files (solid-green background),
run:

```bash
python tools/process_sprites.py assets/pixel
```

to clean them and produce the final transparent files.

## Adding more movements

1. Add new sprite frames to `assets/`.
2. Add a new entry to the `State` enum and the `ANIMATIONS` dict in `luca.py`.
3. Wire it into the right-click menu (the `actions` list inside
   `contextMenuEvent`) and, optionally, into the auto-behavior weights in
   `_think`.
