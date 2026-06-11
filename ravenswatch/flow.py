"""
Game flow automation for Ravenswatch.
Handles menu navigation, run starting, and the full restart loop.
All coordinates are relative (0.0-1.0) so they work at any resolution.
"""

import time

from .controller import GameController
from . import process

BUTTONS = {
    "pret": (0.698, 0.795),
    "abandonner": (0.50, 0.524),
    "confirm_ok": (0.41, 0.63),
    "recompenses": (0.85, 0.96),
    "fin": (0.90, 0.96),
}


def _focused_click(gc: GameController, rx: float, ry: float):
    process.focus_window()
    time.sleep(0.15)
    gc.click_relative(rx, ry)


def _focused_key(gc: GameController, key: str):
    gc.press_key(key)


def start_run(gc: GameController | None = None, screenshots: bool = False) -> bool:
    """Click PRÊT from the lobby to start a new run. Waits for loading."""
    if gc is None:
        gc = GameController()

    if screenshots:
        gc.screenshot("start_lobby")

    _focused_click(gc, *BUTTONS["pret"])
    time.sleep(15.0)

    if screenshots:
        gc.screenshot("start_ingame")

    return True


def restart_run(gc: GameController | None = None, screenshots: bool = False) -> bool:
    """Full restart loop: ESC -> Abandonner -> Ok -> end screens -> back to lobby.

    Call start_run() after this to begin the next run.
    """
    if gc is None:
        gc = GameController()

    def _step(name: str, wait: float = 1.0):
        time.sleep(wait)
        if screenshots:
            gc.screenshot(f"restart_{name}")

    # Open pause menu
    _focused_key(gc, "escape")
    _step("pause", wait=2.0)

    # Click Abandonner
    _focused_click(gc, *BUTTONS["abandonner"])
    _step("confirm_dialog", wait=3.0)

    # Confirm abandon (Ok)
    _focused_click(gc, *BUTTONS["confirm_ok"])
    _step("defeat", wait=6.0)

    # Defeat screen -> Récompenses
    _focused_click(gc, *BUTTONS["recompenses"])
    _step("rewards", wait=3.0)

    # Rewards screen -> Fin
    _focused_click(gc, *BUTTONS["fin"])
    _step("lobby", wait=8.0)

    return True


def restart_and_start(gc: GameController | None = None, screenshots: bool = False) -> bool:
    """Restart the current run and immediately start a new one."""
    if gc is None:
        gc = GameController()

    if not restart_run(gc, screenshots=screenshots):
        return False
    # Extra settle time to ensure lobby is fully loaded before clicking PRÊT
    time.sleep(3.0)
    return start_run(gc, screenshots=screenshots)
