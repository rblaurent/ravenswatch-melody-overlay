"""All 12 Ravenswatch melodies with internal names, display names, note counts, and effects."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Melody:
    internal_name: str
    display_name: str
    notes: int
    effect: str


ALL_MELODIES = [
    Melody("Instant_Level_Up", "Fairy Godmother", 4, "Instant level up"),
    Melody("Increase_Move_Speed_At_Day", "Tortoise", 4, "Move speed boost"),
    Melody("Increase_Fountain_Effect", "Lady of the Lake", 4, "Fountain & Idol bonus"),
    Melody("Fully_Heal", "Galahad", 4, "Heal + feathers each day/night"),
    Melody("Remove_Key_Requirement", "Merry Men", 5, "No keys needed; keys give shards"),
    Melody("Deal_Damage_Around", "Goose Girl", 5, "Periodic area damage"),
    Melody("Grant_Damage_Overtime", "Hansel & Gretel", 5, "DMG over time on boss"),
    Melody("Power_Up_Level_Max", "Little Tailor", 5, "Consumables at level thresholds"),
    Melody("Reduce_MO_Per_Collection", "Lucky Hans", 6, "Collections need fewer items"),
    Melody("Slow_Hourglass_Flow", "Otohime", 6, "Hourglass empties slower"),
    Melody("Reveal_Map", "Long John Silver", 6, "Reveals all Raven Marks"),
    Melody("Refill_Sandman_Dreams", "Sheherazad", 6, "Sandman dreams restock"),
]

# Icon PNG filenames (in icons/) keyed by display name
ICON_FILENAMES = {
    "Fairy Godmother": "UI_Melody_Icon_Godfairy.png",
    "Tortoise": "UI_Melody_Icon_Turtle.png",
    "Lady of the Lake": "UI_Melody_Icon_LadyLake.png",
    "Galahad": "UI_Melody_Icon_Galahad.png",
    "Merry Men": "UI_Melody_Icon_MerryMen.png",
    "Goose Girl": "UI_Melody_Icon_Goose.png",
    "Hansel & Gretel": "UI_Melody_Icon_Hansel.png",
    "Little Tailor": "UI_Melody_Icon_Tailor.png",
    "Lucky Hans": "UI_Melody_Icon_LuckyHans.png",
    "Otohime": "UI_Melody_Icon_OtoHime.png",
    "Long John Silver": "UI_Melody_Icon_LongJohnSilver.png",
    "Sheherazad": "UI_Melody_Icon_Sherazade.png",
}

BY_INTERNAL_NAME = {m.internal_name.lower(): m for m in ALL_MELODIES}
BY_NOTE_COUNT = {}
for m in ALL_MELODIES:
    BY_NOTE_COUNT.setdefault(m.notes, []).append(m)


def identify(name: str) -> Melody | None:
    if not name:
        return None
    key = name.lower()
    for internal, melody in BY_INTERNAL_NAME.items():
        if internal in key:
            return melody
    return None
