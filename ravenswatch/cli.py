"""
CLI for Ravenswatch game automation.
Designed for both human use and AI-driven automation.

Usage:
    python -m ravenswatch status          Check if game is running
    python -m ravenswatch launch          Launch via Steam
    python -m ravenswatch screenshot      Capture game window
    python -m ravenswatch click X Y       Click at window-relative coords
    python -m ravenswatch click-rel RX RY Click at relative coords (0.0-1.0)
    python -m ravenswatch key KEYNAME     Press a key (escape, enter, space)
    python -m ravenswatch melodies        Read current melodies from memory
    python -m ravenswatch serve           OBS browser-source overlay server (port 18904)
    python -m ravenswatch focus           Bring game window to front
    python -m ravenswatch size            Print window dimensions
    python -m ravenswatch start-run       Start a run from the lobby (click PRÊT)
    python -m ravenswatch restart         Restart: abandon current run -> back to lobby
"""

import argparse
import json
import sys

from .controller import GameController
from .flow import restart_run, start_run, restart_and_start
from .memory import MemoryReader
from . import process


def main():
    parser = argparse.ArgumentParser(description="Ravenswatch game automation")
    parser.add_argument("--screenshot-dir", default="screenshots", help="Directory for screenshots")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Check if the game is running")
    sub.add_parser("launch", help="Launch the game via Steam")
    sub.add_parser("focus", help="Bring the game window to the foreground")
    sub.add_parser("size", help="Print window dimensions")

    p_ss = sub.add_parser("screenshot", help="Capture the game window")
    p_ss.add_argument("name", nargs="?", help="Screenshot filename (without .png)")

    p_click = sub.add_parser("click", help="Click at window-relative coordinates")
    p_click.add_argument("x", type=int)
    p_click.add_argument("y", type=int)

    p_clickrel = sub.add_parser("click-rel", help="Click at relative coordinates (0.0-1.0)")
    p_clickrel.add_argument("rx", type=float)
    p_clickrel.add_argument("ry", type=float)

    p_key = sub.add_parser("key", help="Press a key")
    p_key.add_argument("keyname", help="Key name: escape, enter, space, or a single character")

    p_wait = sub.add_parser("wait", help="Wait for a duration")
    p_wait.add_argument("seconds", type=float)

    sub.add_parser("melodies", help="Read current melodies from memory")
    sub.add_parser("overlay", help="Launch the live melody overlay window")

    p_serve = sub.add_parser("serve", help="Serve the OBS browser-source overlay over HTTP")
    p_serve.add_argument("--port", type=int, default=18904, help="HTTP port (default 18904)")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="Bind address (use 0.0.0.0 to allow other machines)")

    p_start = sub.add_parser("start-run", help="Start a run from the lobby (click PRÊT)")
    p_start.add_argument("--screenshots", action="store_true", help="Save screenshots at each step")

    p_restart = sub.add_parser("restart", help="Abandon current run and return to lobby")
    p_restart.add_argument("--screenshots", action="store_true", help="Save screenshots at each step")
    p_restart.add_argument("--start", action="store_true", help="Also start a new run after restarting")

    args = parser.parse_args()
    gc = GameController(screenshot_dir=args.screenshot_dir)

    if args.command == "status":
        pid = process.find_pid()
        hwnd = process.find_window()
        info = {"running": pid is not None, "pid": pid, "window": hwnd is not None}
        if hwnd:
            rect = process.get_window_rect(hwnd)
            if rect:
                info["rect"] = {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}
                info["size"] = {"width": rect[2] - rect[0], "height": rect[3] - rect[1]}
        print(json.dumps(info, indent=2))

    elif args.command == "launch":
        ok = gc.launch_and_wait()
        print(json.dumps({"launched": ok}))

    elif args.command == "focus":
        ok = process.focus_window()
        print(json.dumps({"focused": ok}))

    elif args.command == "size":
        try:
            w, h = gc.window_size
            print(json.dumps({"width": w, "height": h}))
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}))

    elif args.command == "screenshot":
        try:
            path = gc.screenshot(args.name)
            print(json.dumps({"path": str(path)}))
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}))

    elif args.command == "click":
        gc.click(args.x, args.y)
        print(json.dumps({"clicked": [args.x, args.y]}))

    elif args.command == "click-rel":
        gc.click_relative(args.rx, args.ry)
        w, h = gc.window_size
        print(json.dumps({"clicked_rel": [args.rx, args.ry], "clicked_abs": [int(w * args.rx), int(h * args.ry)]}))

    elif args.command == "key":
        gc.press_key(args.keyname)
        print(json.dumps({"pressed": args.keyname}))

    elif args.command == "wait":
        gc.wait(args.seconds)
        print(json.dumps({"waited": args.seconds}))

    elif args.command == "melodies":
        reader = MemoryReader()
        if not reader.connect():
            print(json.dumps({"error": "Cannot connect to game process. Is it running? Run as admin?"}))
            sys.exit(1)
        info = reader.read_run_info()
        if info:
            melodies, states = info
            active = next((m for m, st in zip(melodies, states) if st == 1), None)
        else:
            active = reader.read_active_melody()  # legacy fallback
        reader.disconnect()

        out = {"melodies": None, "active_melody": None}
        if info:
            out["melodies"] = [
                {
                    "slot": i + 1,
                    "name": m.display_name,
                    "internal_name": m.internal_name,
                    "notes": m.notes,
                    "effect": m.effect,
                    "active": st == 1,
                    "completed": st >= 2,
                }
                for i, (m, st) in enumerate(zip(melodies, states))
            ]
        if active:
            out["active_melody"] = active.display_name
            out["internal_name"] = active.internal_name
            out["notes"] = active.notes
            out["effect"] = active.effect
        if not info and not active:
            out["error"] = "Not in a run or melodies not detected"
        print(json.dumps(out, indent=2))

    elif args.command == "overlay":
        from .overlay import MelodyOverlay
        MelodyOverlay().run()

    elif args.command == "serve":
        from .server import serve
        serve(port=args.port, host=args.host)

    elif args.command == "start-run":
        ok = start_run(gc, screenshots=args.screenshots)
        print(json.dumps({"started": ok}))

    elif args.command == "restart":
        if args.start:
            ok = restart_and_start(gc, screenshots=args.screenshots)
            print(json.dumps({"restarted_and_started": ok}))
        else:
            ok = restart_run(gc, screenshots=args.screenshots)
            print(json.dumps({"restarted": ok}))


if __name__ == "__main__":
    main()
