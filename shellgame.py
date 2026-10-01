#!/usr/bin/env python3
"""
SHELL GAME: a terminal duel of nerve, odds and one very loud gun.

  python3 shellgame.py             play
  python3 shellgame.py --offline   ignore AI settings; dealers use built-in strategies

AI dealers (optional): open Settings from the main menu, pick a provider
(Google Gemini or SleepyAI), paste an API key (stored in the macOS Keychain)
and choose a model. Environment variables also work:
GEMINI_API_KEY / GOOGLE_API_KEY, SLEEPYAI_API_KEY.

Python 3.8+, standard library only. Terminal must be at least 100x30.
Settings: ~/.shellgame_config.json    High scores: ~/.shellgame_scores.json
"""
import curses
import getpass
import json
import locale
import math
import os
import random
import shutil
import socket
import ssl
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from datetime import date

os.environ.setdefault("ESCDELAY", "25")

# ═════════════════════════════ constants ═════════════════════════════
W, H = 100, 30
LEFT_W = 64
RIGHT_X, RIGHT_W = 64, 36
MAX_ITEMS = 8
API_TIMEOUT = 25
CONFIG_FILE = os.path.expanduser("~/.shellgame_config.json")
SCORE_FILE = os.path.expanduser("~/.shellgame_scores.json")
KEYCHAIN_SERVICE = "shellgame"
USER_AGENT = "ShellGame/3.2 (+terminal game)"
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SOUND_DIR = "/System/Library/Sounds"
SOUNDS = {"bang": "Basso", "click": "Tink", "load": "Pop", "item": "Morse", "win": "Hero",
          "lose": "Sosumi", "dice": "Bottle", "trap": "Funk", "reveal": "Glass", "event": "Purr",
          "sudden": "Submarine"}
SPEEDS = {"normal": 1.0, "fast": 0.55, "turbo": 0.25}
CLOCK_OPTIONS = ["off", "20", "15", "10"]
DEFAULT_PREFS = {"theme": "casino", "sound": True, "speed": "normal", "mouse": True,
                 "events": True, "misfires": True, "clock": "off"}
MISFIRE_CHANCE = 0.05
EVENT_CHANCE = 0.55
RUSH_SECONDS = 10
TELL_CHANCE = 0.45
HIGH_ROLLER_CHANCE = 0.35
BLUFF_BONUS = 250

ROLES = ["live", "blank", "item", "hp", "dealer", "flash", "title"]
THEMES = {
    "casino": {"label": "Casino", "live": ("RED", None), "blank": ("CYAN", None), "item": ("YELLOW", None),
               "hp": ("GREEN", None), "dealer": ("MAGENTA", None), "flash": ("WHITE", "RED"),
               "title": ("BLACK", "YELLOW")},
    "neon": {"label": "Neon", "live": ("MAGENTA", None), "blank": ("CYAN", None), "item": ("YELLOW", None),
             "hp": ("GREEN", None), "dealer": ("BLUE", None), "flash": ("BLACK", "CYAN"),
             "title": ("BLACK", "MAGENTA")},
    "noir": {"label": "Noir", "live": ("RED", None), "blank": ("WHITE", None), "item": ("WHITE", None),
             "hp": ("WHITE", None), "dealer": ("WHITE", None), "flash": ("BLACK", "WHITE"),
             "title": ("BLACK", "WHITE")},
}
THEME_ORDER = ["casino", "neon", "noir"]

EVENTS = {
    "blackout": {"label": "Blackout", "icon": "●",
                 "desc": "The LEFT counter goes dark for this load. Count the SPENT row yourself."},
    "stakes": {"label": "Double Stakes", "icon": "²",
               "desc": "Every live shell deals 1 extra damage this load. A sawed-off hit deals 3."},
    "generous": {"label": "Generous House", "icon": "+",
                 "desc": "The house is feeling kind: everyone drew 2 extra items this load."},
    "dry": {"label": "Dry Table", "icon": "∅",
            "desc": "No items can be used until the next reload. Just you, the gun and the odds."},
    "hot": {"label": "Hot Barrel", "icon": "▲",
            "desc": "The last shell in the gun is guaranteed live, and everyone knows it (unless someone shuffles)."},
    "rush": {"label": "Rush Hour", "icon": "◷",
             "desc": f"A {RUSH_SECONDS}-second shot clock runs on every human decision this load. "
                     f"Dither and the gun fires itself."},
    "blood": {"label": "Blood Moon", "icon": "☾",
              "desc": "Every hit on your opponent heals you 1 charge this load."},
}
EVENT_KEYS = list(EVENTS)


def _item(label, icon, cat, short, weight, desc, tip):
    return {"label": label, "icon": icon, "cat": cat, "short": short, "weight": weight, "desc": desc, "tip": tip}


ITEMS = {
    # ── classic
    "loupe": _item("Loupe", "◎", "Information", "peek at the chambered shell", 3,
                   "Peer at the shell sitting in the chamber. Only you learn if it's live or blank; your "
                   "opponent just sees you peek.",
                   "Use it before deciding who to shoot. A Loupe followed by a Saw on a live shell is the classic combo."),
    "rack": _item("Rack", "⇥", "Gun", "eject the chambered shell", 3,
                  "Pump the action and eject the chambered shell without firing it. Everyone sees what it "
                  "was, and your turn goes on.",
                  "Dump a shell you're afraid of, or thin out the gun when the odds are a coin flip."),
    "saw": _item("Saw", "‡", "Gun", "next shot deals 2 damage", 2,
                 "Saw off the barrel. Your next shot deals 2 damage instead of 1, whoever you aim at. "
                 "Spent on that shot, live or blank.",
                 "Best right after a Loupe shows a live shell. Never saw the barrel and then shoot yourself on a hunch."),
    "shackles": _item("Shackles", "∞", "Control", "opponent skips next turn", 2,
                      "Chain your opponent to the table. They skip their next turn, so you act again. No "
                      "effect on someone already chained.",
                      "Use it when you know the next two shells are live, or to buy time while you're low."),
    "tonic": _item("Tonic", "♥", "Defense", "+1 charge", 3,
                   "A bitter drink that restores 1 charge, up to your maximum. It can't be used at full "
                   "charge or in sudden death.",
                   "Drink it early. A charge saved now is a live shell survived later."),
    "flipper": _item("Flipper", "⇅", "Gun", "invert the chambered shell", 2,
                     "Invert the chambered shell: live becomes blank, blank becomes live. The new value is "
                     "announced to both players.",
                     "Turn a known blank into a live shell before shooting your opponent, or defuse one you'd face."),
    "radio": _item("Radio", "♪", "Information", "learn a random future shell", 2,
                   "A crackling voice tells you about one random shell further down the gun. Only you hear "
                   "it; the chamber row marks it.",
                   "Plan two moves ahead: if you know the second shell is live, a Rack or a blank to yourself sets it up."),
    "hook": _item("Hook", "↩", "Control", "steal an item, use it now", 1,
                  "Steal one of your opponent's items and use it immediately. Can't take a Hook or a Charm. "
                  "Items that need a choice pick at random.",
                  "Steal their Loupe when you're blind, their Saw when you know it's live, or their Tonic when hurt."),
    "pills": _item("Pills", "◐", "Chaos", "50%: +2 charges, 50%: -1", 2,
                   "Expired pills of unknown origin. Coin flip: restore 2 charges, or lose 1, which can knock "
                   "you out cold.",
                   "Only worth it when you're two or more charges down. Never swallow them on your last charge."),
    # ── information & deception
    "snapshot": _item("Snapshot", "▣", "Information", "see the whole chamber for 2s", 1,
                      "A flash photo of the gun's insides. Every remaining shell is shown for two seconds, "
                      "then the picture fades. Memorise it.",
                      "Use it on a long load, then say the order out loud before it disappears."),
    "tarot": _item("Tarot", "♠", "Information", "how many live in the next 3", 2,
                   "Turn a card to learn how many of the next three shells are live, but not which ones. "
                   "The TABLE memo keeps count as they're fired.",
                   "\"2 of 3 live\" plus a Loupe on the first shell often tells you the whole story."),
    "shuffle": _item("Shuffle", "⇄", "Gun", "reshuffle the remaining shells", 2,
                     "Spin the remaining shells into a new random order. Everyone's Loupe, Radio and Tarot "
                     "knowledge becomes worthless.",
                     "Use it right after your opponent peeks. It's the best answer to the Accountant."),
    "slip": _item("Slip", "↧", "Gun", "secretly insert a shell", 1,
                  "Slide a live or blank shell into the gun at a position you choose. Everyone sees which "
                  "kind was added, but only you know where.",
                  "Slip a live shell into the chamber, then shoot your opponent. Or hide a blank for yourself."),
    "decoy": _item("Decoy", "¤", "Deception", "gift a rigged item", 1,
                   "Give your opponent a gift that looks like a normal item. When they use it, it backfires "
                   "for 1 damage.",
                   "Disguise it as something they'd use soon, like a Tonic when they're hurt."),
    # ── gun manipulation
    "double": _item("Double", "‖", "Gun", "next shot fires two shells", 1,
                    "Your next shot fires the next two shells at the same target, one after the other. "
                    "A Saw only boosts the first shell.",
                    "Brutal when you know the next two are live. Terrifying when you're wrong."),
    "jammer": _item("Jammer", "⊘", "Defense", "next live shell misfires", 2,
                    "Wedge the firing pin. If the next shell fired is live, it misfires harmlessly and is "
                    "ejected. Works on whoever fires next.",
                    "Insurance before shooting yourself on bad odds. The turn still passes if it jams."),
    "ricochet": _item("Ricochet", "↻", "Defense", "next shot at you bounces back", 2,
                      "Bolt a steel plate to your chair. The next shot your opponent aims at you bounces back "
                      "at them. Everyone can see it's armed.",
                      "Arm it when you expect a live shell. It forces your opponent to shoot themselves."),
    "leech": _item("Leech", "♦", "Chaos", "a hit on your next shot heals you", 2,
                   "Prime a leech on the barrel. If your next shot hits your opponent, you gain 1 charge.",
                   "Pair it with a Loupe that shows live, or a Saw for a four-charge swing."),
    # ── defense
    "vest": _item("Vest", "▦", "Defense", "absorb the next 1 damage", 2,
                  "Strap on a vest that absorbs the next point of damage you take, from any source. You "
                  "can only wear one at a time.",
                  "Against a sawed-off shot it turns 2 damage into 1."),
    "charm": _item("Charm", "♣", "Defense", "passive: survive one lethal hit", 1,
                   "A lucky charm that works on its own. The first time a hit would knock you out, you "
                   "survive on 1 charge and the Charm shatters.",
                   "Keep it. It takes up a slot, but a Crowbar is the only way to lose it."),
    "muzzle": _item("Muzzle", "×", "Control", "opponent can't use items next turn", 2,
                    "Strap a muzzle on your opponent. On their next turn they can't use any items and "
                    "have to shoot bare.",
                    "Use it when they're sitting on a Loupe or Tonic they badly need."),
    # ── chaos
    "pact": _item("Pact", "†", "Chaos", "swap charges with your opponent", 1,
                  "Sign a pact with something that isn't the house. Your charges and your opponent's "
                  "charges swap.",
                  "The ultimate comeback. Worthless when you're ahead."),
    "dice": _item("Dice", "⚄", "Chaos", "roll for a random effect", 2,
                  "Roll a die. 1: lose a charge. 2: lose a random item. 3: nothing. 4: see the chambered "
                  "shell. 5: +1 charge. 6: shackle your opponent.",
                  "Two good faces, one neutral, one great, two bad. Only roll when you can afford a charge."),
    "crowbar": _item("Crowbar", "⌐", "Control", "destroy one opponent item", 2,
                     "Smash one of your opponent's items. It's gone for good, and if it was a rigged "
                     "Decoy, everyone finds out.",
                     "The only answer to a Charm. Also great against a hoarded Saw or Loupe."),
    "rewind": _item("Rewind", "↺", "Gun", "put the last fired shell back", 1,
                    "Crank the gun backwards: the last shell fired or racked this load goes back into the "
                    "chamber. Everyone knows what it is.",
                    "Rewind a live shell you just survived, then point it at your opponent."),
}
ITEM_KEYS = list(ITEMS)
DECOY_FORMS = ["tonic", "loupe", "saw", "vest", "rack"]
STANDARD_POOL = {k: v["weight"] for k, v in ITEMS.items()}
STANDARD_RULES = {"hp": [2, 4, 5], "you_items": [2, 2, 3], "dealer_items": [2, 2, 3],
                  "counter": True, "mult": 1.0, "think": "low"}


def base(entry):
    """Inventory entries are item keys, or 'trap:<key>' for a rigged Decoy."""
    return entry[5:] if entry.startswith("trap:") else entry


GENERIC_EYES = {"idle": "(o) (o)", "hurt": "(x) (x)", "grin": "(^) (^)", "think": "(-) (o)", "dead": "(+) (+)",
                "sweat": "(O) (O)", "smug": "(¬) (¬)", "angry": "(>) (<)"}
GENERIC_MOUTH = {"idle": "   ===   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ---   ",
                 "dead": "   ___   ", "sweat": "  ~~o~~  ", "smug": "     _/  ", "angry": "   ###   "}
PLAYER2_HEAD = ["     ,,,,,,,", "    .-------."]

DEALERS = {
    "accountant": {
        "name": "The Accountant", "tier": "EASY", "color": "hp",
        "tagline": "Cautious. Audits every shell before he shoots.",
        "bio": "A pale man in a green visor who logs every shell in a ledger. He won't act on a hunch "
               "while a Loupe is in reach, and he patches up the moment he's hurt.",
        "style": ["Always peeks (Loupe, Tarot, Snapshot) before he shoots",
                  "Shoots you only when the numbers favor live",
                  "Wears a Vest, heals at once, never touches Pills"],
        "house_rule": "AUDIT: use 3 items in one turn and he confiscates one of yours.",
        "tell_desc": "Honest. His pen taps faster over live shells.",
        "tells": {"acc": 0.75, "sweat": "*he taps his pen, faster and faster*",
                  "smug": "*he closes the ledger, satisfied*"},
        "tilt": {"line": "He hurls the ledger across the room. Numbers be damned!",
                 "prompt": "You are TILTED after taking two hits in a row: throw caution away and play like a "
                           "reckless gambler (saw, double, pills, shoot yourself on coin flips)."},
        "pool": {"loupe": 5, "tonic": 4, "radio": 3, "rack": 3, "tarot": 3, "vest": 3, "snapshot": 2,
                 "jammer": 2, "shackles": 1, "saw": 1},
        "rules": {"hp": [3, 4, 5], "you_items": [2, 3, 3], "dealer_items": [2, 2, 3],
                  "counter": True, "mult": 1.0, "think": "low"},
        "head": ["     _______", "    /_______\\"],
        "eyes": {"idle": "[o]-[o]", "hurt": "[x]-[x]", "grin": "[^]-[^]", "think": "[-]-[o]", "dead": "[+]-[+]",
                 "sweat": "[O]-[O]", "smug": "[-]-[-]", "angry": "[>]-[<]"},
        "mouth": {"idle": "   ---   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ...   ",
                  "dead": "   ___   "},
        "prompt": "You are THE ACCOUNTANT: meticulous, risk-averse and dry. Strategy: if the chambered shell "
                  "is unknown, ALWAYS gather information first (loupe, snapshot, tarot, radio). Wear a vest "
                  "and heal with tonic as soon as you are below max. Use a jammer before shooting yourself "
                  "unless you know it's blank. Never take pills or dice. Shoot your opponent only when the "
                  "shell is known live or the chance of live is 50% or more; shoot yourself only when it is "
                  "known blank or the chance of live is 30% or less. "
                  "Taunts: dry accounting jargon (ledgers, audits, margins, write-offs).",
        "lines": ["Let me check the figures.", "The numbers don't lie.", "Margins are thin today.",
                  "Filed under: your mistake.", "An audit is in order."],
    },
    "gambler": {
        "name": "The Gambler", "tier": "EASY", "color": "item",
        "tagline": "Reckless. Shoots himself on a coin flip, for the thrill.",
        "bio": "A loud high-roller with a gold tooth. He treats a coin flip as an invitation, saws "
               "the barrel on a hunch and rolls the Dice just to hear them rattle.",
        "style": ["Shoots himself on 50/50s to chase the extra turn",
                  "Loves the Saw, Double, Dice and Pills",
                  "Signs a Pact the moment he falls behind"],
        "house_rule": "HIGH ROLLER: once a stage he forces two blind shots, with no items and no counter.",
        "tell_desc": "Honest. He goes quiet over live shells and winks at blanks.",
        "tells": {"acc": 0.8, "sweat": "*his gold tooth stops glinting*",
                  "smug": "*he winks and rolls his lucky coin*"},
        "tilt": {"line": "The grin is gone. He's playing it safe now.",
                 "prompt": "You are TILTED and rattled after two hits in a row: play it painfully safe: peek "
                           "before every shot, heal, and never shoot yourself unless you know it's blank."},
        "pool": {"saw": 4, "pills": 4, "dice": 4, "double": 3, "flipper": 3, "pact": 2, "leech": 2,
                 "charm": 2, "loupe": 1, "tonic": 1},
        "rules": {"hp": [3, 4, 5], "you_items": [2, 3, 3], "dealer_items": [2, 3, 3],
                  "counter": True, "mult": 1.0, "think": "low"},
        "head": ["      ,---.", "  ___/_____\\___"],
        "eyes": {"idle": "($) ($)", "hurt": "(x) (x)", "grin": "(*) (*)", "think": "(o) (-)", "dead": "(x) (x)"},
        "mouth": {"idle": "   \\_/   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   -o-   ",
                  "dead": "   ___   "},
        "prompt": "You are THE GAMBLER: a reckless, flashy high-roller. Strategy: when the chance of live is "
                  "50% or less, shoot YOURSELF for the thrill of the extra turn; otherwise shoot your "
                  "opponent. Use the saw and double on hunches whenever the odds look even remotely good, "
                  "roll dice and take pills whenever you're hurt, sign a pact the moment you're behind, and "
                  "rarely bother with the loupe. Taunts: casino slang (jackpots, hot streaks, let it ride).",
        "lines": ["Let it ride!", "Feeling lucky? I always am.", "Double or nothing, baby!",
                  "Hot streak incoming!", "House money, pal."],
    },
    "liar": {
        "name": "The Liar", "tier": "MEDIUM", "color": "dealer",
        "tagline": "A con artist. Tips you off about the next shell. Usually lies.",
        "bio": "Silver-tongued and smiling, he always has a tip about the next shell, and he's right "
               "just often enough to keep you listening. Mind his gifts.",
        "style": ["Whispers a 'tip' about the next shell each turn",
                  "Usually lies. Sometimes, cruelly, tells the truth",
                  "Slips shells, gives rigged gifts, arms Ricochets"],
        "house_rule": "TIPS: after his turn he tips you about the chambered shell. Press C to call his bluff.",
        "tell_desc": "Faked. His nerves usually mean the opposite.",
        "tells": {"acc": 0.3, "sweat": "*he dabs his brow, a touch theatrically*",
                  "smug": "*he smiles like he's already won*"},
        "tilt": {"line": "His smile cracks. His tips and tells turn honest.",
                 "prompt": "You are TILTED and rattled after two hits in a row: your composure slips and you "
                           "stop bluffing."},
        "pool": {"flipper": 3, "hook": 3, "shackles": 3, "decoy": 3, "slip": 3, "shuffle": 2,
                 "ricochet": 2, "muzzle": 2, "loupe": 2, "radio": 1},
        "rules": {"hp": [2, 4, 5], "you_items": [2, 2, 3], "dealer_items": [2, 3, 4],
                  "counter": True, "mult": 1.5, "think": "low"},
        "head": ["     ~~~~~~~", "    .-------."],
        "eyes": {"idle": "(o) (-)", "hurt": "(x) (x)", "grin": "(^) (-)", "think": "(-) (-)", "dead": "(+) (+)"},
        "mouth": {"idle": "  \\___/~ ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ~~~   ",
                  "dead": "   ___   "},
        "prompt": "You are THE LIAR: a smooth, smiling con artist. Strategy: play solidly and dirty: give "
                  "rigged decoys, slip live shells into the chamber before shooting your opponent, shuffle "
                  "the gun right after your opponent peeks, arm ricochets, muzzle and shackle your opponent, "
                  "and hook their best items. Taunts are your weapon: claim to know shells you don't, and "
                  "usually state the OPPOSITE of the truth about the chambered or next shell. Tell the truth "
                  "just often enough to stay unpredictable. Never admit to lying.",
        "lines": ["Would I lie to you?", "Trust me. Everyone does.", "I never bluff. Well. Rarely.",
                  "Such an honest face, isn't it?", "You look nervous. Good."],
    },
    "croupier": {
        "name": "The Croupier", "tier": "HARD · BOSS", "color": "live", "locked": True,
        "tagline": "The house itself. Cold, precise, almost never wrong.",
        "bio": "He deals every game in this room and has never been seen to lose. He wastes nothing, "
               "and at his table the shell counter goes dark.",
        "style": ["Plays the odds almost perfectly",
                  "Chains items: Loupe, then Saw or Double on live",
                  "Shell counter is switched off at his table"],
        "house_rule": "HOUSE EDGE: he sees the first shell of every load. He never tilts.",
        "tell_desc": "None. The house has no tells.",
        "tells": None,
        "tilt": None,
        "pool": dict(STANDARD_POOL),
        "rules": {"hp": [2, 3, 4], "you_items": [1, 2, 3], "dealer_items": [2, 3, 4],
                  "counter": False, "mult": 2.5, "think": "medium"},
        "head": ["      _____", "    _|_____|_"],
        "eyes": GENERIC_EYES,
        "mouth": GENERIC_MOUTH,
        "prompt": "You are THE CROUPIER: the house itself. Cold, courteous and nearly flawless. Strategy: "
                  "play the odds precisely, gather information before committing, chain items (loupe then "
                  "saw or double on live; flipper on a known blank; rewind a live shell), protect yourself "
                  "with vests and jammers, and never waste an item or a turn. House edge: you always see the "
                  "first shell of each load (it appears in your known shells). Taunts: quiet, polite menace.",
        "lines": ["The house always wins.", "Place your bets.", "Tick, tock.",
                  "Nothing personal. Just odds.", "The table is yours. Briefly."],
    },
}
DEALER_ORDER = ["accountant", "gambler", "liar", "croupier"]

LIAR_SAYS_LIVE = ["Psst. That next shell? Live. Point it at me... if you dare.",
                  "Between us: it's a live one. Careful where you aim.",
                  "Hot round in the chamber. I'd never lie to you."]
LIAR_SAYS_BLANK = ["Relax, it's a blank. Go on, treat yourself to an extra turn.",
                   "Nothing in that one but air. Honest.",
                   "Blank. I'd put it to your own head: free turn."]

PROVIDERS = {
    "off": {"label": "Off (built-in dealers)", "short": "built-in", "kind": None},
    "gemini": {"label": "Google Gemini", "short": "Gemini", "kind": "gemini",
               "base": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-3.8-flash",
               "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "needs_key": True, "edit_base": False},
    "sleepyai": {"label": "SleepyAI", "short": "SleepyAI", "kind": "openai",
                 "base": "https://www.sleepyai.org/api/v1", "model": "",
                 "env": ["SLEEPYAI_API_KEY"], "needs_key": True, "edit_base": True,
                 "json_mode": False},  # response_format isn't documented by SleepyAI
}
PROVIDER_ORDER = ["off", "gemini", "sleepyai"]

FRIENDLY_HTTP = {401: "invalid or missing API key", 403: "model disabled or access denied",
                 429: "rate or spending limit exceeded", 502: "upstream provider error",
                 503: "model temporarily unavailable"}

# ═════════════════════════════ art ═════════════════════════════
_LETTERS = {
    "S": [" ___ ", "/ __|", "\\__ \\", "|___/"],
    "H": [" _  _ ", "| || |", "| __ |", "|_||_|"],
    "E": [" ___ ", "| __|", "| _| ", "|___|"],
    "L": [" _    ", "| |   ", "| |__ ", "|____|"],
    "G": ["  ___ ", " / __|", "| (_ |", " \\___|"],
    "A": ["   _   ", "  /_\\  ", " / _ \\ ", "/_/ \\_\\"],
    "M": [" __  __ ", "|  \\/  |", "| |\\/| |", "|_|  |_|"],
    " ": ["  "] * 4,
}
TITLE_ART = ["".join(_LETTERS[c][r] for c in "SHELL GAME") for r in range(4)]

_BIG = {
    "B": ["█████ ", "█    █", "█████ ", "█    █", "█████ "],
    "A": [" ███ ", "█   █", "█████", "█   █", "█   █"],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "G": [" ████", "█    ", "█  ██", "█   █", " ████"],
    "!": ["█", "█", "█", " ", "█"],
}


def big(word):
    return ["  ".join(_BIG[c][r] for c in word) for r in range(5)]


GUN = [
    "  ________________________.________",
    " (________________________|__[==]__)=====.",
    "                           \\ \\__/ /  \\____)",
    "                            '----'",
]


def gun_art(sawed):
    if not sawed:
        return GUN
    return [" " * 14 + GUN[0][14:], " " * 13 + "(" + GUN[1][14:], GUN[2], GUN[3]]


def portrait(dealer, face="idle", locked=False):
    head = dealer["head"] if dealer else PLAYER2_HEAD
    if locked:
        eyes, mouth = "(?) (?)", "   ???   "
    else:
        e = (dealer or {}).get("eyes", GENERIC_EYES)
        m = (dealer or {}).get("mouth", GENERIC_MOUTH)
        eyes = e.get(face) or GENERIC_EYES.get(face) or e["idle"]
        mouth = m.get(face) or GENERIC_MOUTH.get(face) or m["idle"]
    return head + ["   /  _   _  \\", "  |  " + eyes + "  |", "   \\" + mouth + "/", "    '-------'"]


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def wrap(text, width):
    return textwrap.wrap(text, width) or [""]


def short_err(e):
    return (str(e) or e.__class__.__name__)[:90]


def mask_key(key):
    if len(key) <= 8:
        return "•" * len(key)
    return "•" * min(16, len(key) - 4) + key[-4:]


def item_line(entry):
    info = ITEMS[base(entry)]
    return f"{info['icon']} {info['label']:<9}{info['short']}"


# ═════════════════════════════ game model ═════════════════════════════
class Player:
    def __init__(self, name, is_ai=False):
        self.name = name
        self.is_ai = is_ai
        self.hp = self.max_hp = 0
        self.items = []
        self.wins = 0
        self.reset_status()
        self.known = {}  # absolute shell index -> True (live) / False (blank)
        self.hints = []  # Tarot readings: [start_index, end_index, live_count]
        self.peeked = False

    def reset_status(self):
        self.shackled = False
        self.muzzled = False
        self.vest = 0
        self.ricochet = False
        self.leech = False


class Game:
    def __init__(self, mode, names, vs_ai, dealer_key=None, opts=None):
        self.mode, self.vs_ai, self.dealer_key = mode, vs_ai, dealer_key
        self.opts = {"events": True, "misfires": True}
        self.opts.update(opts or {})
        self.players = [Player(names[0]), Player(names[1], is_ai=vs_ai)]
        self.stage = 0
        self.shells, self.pos, self.spent = [], 0, []
        self.loaded = (0, 0)
        self.loads = 0
        self.event = None
        self.sudden = False
        self.turn = 0
        self.sawed = False
        self.double = False
        self.jammed = False
        self.log = []
        self.score = 0
        self.stage_winner = None
        self.needs_reload = False
        self.double_pending = False
        self.pending_tip = False
        self.fx = []
        self._reset_mind()

    def _reset_mind(self):
        """Per-stage dealer psychology: tells, tilt, bluffs and house rules."""
        self.tip = None
        self.tell = None
        self.tell_key = None
        self.tilted = False
        self.dealer_hits = 0
        self.uses = 0
        self.blind = 0
        self.coin_used = False

    @property
    def dealer(self):
        return DEALERS.get(self.dealer_key) if self.dealer_key else None

    @property
    def rules(self):
        d = self.dealer
        return d["rules"] if d else STANDARD_RULES

    def counter_on(self):
        return self.rules["counter"] and self.event != "blackout" and not self.blind

    def live_damage(self, first=True):
        return (2 if (self.sawed and first) else 1) + (1 if self.event == "stakes" else 0)

    # ── language helpers
    def v(self, p, verb):
        you = p.name == "You"
        if verb == "be":
            return "are" if you else "is"
        if you:
            return verb
        if verb.endswith(("s", "sh", "ch", "x", "o")):
            return verb + "es"
        return verb + "s"

    @staticmethod
    def _mid(name):
        return "the" + name[3:] if name.startswith("The ") else name

    def obj(self, p):
        return "you" if p.name == "You" else self._mid(p.name)

    def poss(self, p):
        return "your" if p.name == "You" else self._mid(p.name) + "'s"

    def refl(self, p):
        if p.name == "You":
            return "yourself"
        return "himself" if p.is_ai else "themselves"

    # ── basics
    def cur(self):
        return self.players[self.turn]

    def add_log(self, text, kind="info"):
        self.log.append((text, kind))
        del self.log[:-200]

    def award(self, pts):
        pts = int(pts * self.rules["mult"])
        self.score += pts
        return pts

    def left(self):
        return len(self.shells) - self.pos

    def remaining(self):
        rem = self.shells[self.pos:]
        live = sum(rem)
        return live, len(rem) - live

    def _scaled(self, key, cap):
        rules = self.rules[key]
        idx = min(self.stage, 3) - 1
        extra = (self.stage - 2) // 2 if self.stage > 3 else 0
        return min(cap, rules[idx] + extra)

    def _drain(self):
        ev, self.fx = self.fx, []
        return ev

    def effective_current(self, i):
        """What player i knows or can deduce about the chambered shell."""
        p = self.players[i]
        if self.pos in p.known:
            return p.known[self.pos]
        rem = self.shells[self.pos:]
        kn = [v for k, v in p.known.items() if k > self.pos]
        unk = len(rem) - len(kn)
        lv = sum(rem) - sum(kn)
        if unk <= 0:
            return None
        if lv == 0:
            return False
        if lv == unk:
            return True
        return None

    def chance_live(self, i):
        cur = self.effective_current(i)
        if cur is not None:
            return 1.0 if cur else 0.0
        p = self.players[i]
        rem = self.shells[self.pos:]
        kn = [v for k, v in p.known.items() if k > self.pos]
        unk = len(rem) - len(kn)
        return (sum(rem) - sum(kn)) / unk if unk > 0 else 0.5

    # ── stage / reload
    def start_stage(self):
        self.stage += 1
        if self.mode == "gauntlet":
            self.dealer_key = DEALER_ORDER[(self.stage - 1) % len(DEALER_ORDER)]
            self.players[1].name = self.dealer["name"]
        hp = self._scaled("hp", 6)
        for p in self.players:
            p.hp = p.max_hp = hp
            p.items = []
            p.reset_status()
        self.sawed = self.double = self.jammed = False
        self.sudden = False
        self.loads = 0
        self.stage_winner = None
        self.pending_tip = False
        self.fx = []
        self._reset_mind()
        self.turn = 0 if self.vs_ai else (self.stage - 1) % 2
        intro = f" · {self.players[1].name} sits down" if self.mode == "gauntlet" else ""
        self.add_log(f"── STAGE {self.stage}{intro} · {hp} charges ──", "title")
        return self.reload()

    def reload(self):
        self.needs_reload = False
        self.loads += 1
        self.event = None
        first_ever = self.stage == 1 and self.loads == 1
        if self.opts["events"] and not first_ever and random.random() < EVENT_CHANCE:
            self.event = random.choice(EVENT_KEYS)
        lo, hi = {1: (2, 4), 2: (3, 6)}.get(self.stage, (4, 8))
        n = random.randint(lo, hi)
        live = random.randint(max(1, n // 2 - 1), min(n - 1, (n + 1) // 2 + 1))
        self.shells = [True] * live + [False] * (n - live)
        random.shuffle(self.shells)
        if self.event == "hot" and not self.shells[-1]:
            j = random.choice([k for k, v in enumerate(self.shells) if v])
            self.shells[j], self.shells[-1] = self.shells[-1], self.shells[j]
        self.pos, self.spent, self.loaded = 0, [], (live, n - live)
        self.sawed = False
        for p in self.players:
            p.known, p.hints, p.peeked = {}, [], False
            if self.event == "hot":
                p.known[len(self.shells) - 1] = True
        self.add_log(f"The gun is loaded: {live} live, {n - live} blank.", "info")
        if self.event:
            e = EVENTS[self.event]
            self.add_log(f"TABLE EVENT {e['icon']} {e['label']}: {e['desc']}", "title")
        if self.vs_ai and self.dealer_key == "croupier":
            self.players[1].known[0] = self.shells[0]
            self.add_log("House edge: the Croupier glances at the first shell.", "dealer")
        bonus = 2 if self.event == "generous" else 0
        for idx, p in enumerate(self.players):
            dealer_side = self.vs_ai and idx == 1
            pool = self.dealer["pool"] if dealer_side else STANDARD_POOL
            k = self._scaled("dealer_items" if dealer_side else "you_items", 6) + bonus
            keys = list(pool)
            weights = [pool[x] for x in keys]
            got = []
            for _ in range(k):
                if len(p.items) >= MAX_ITEMS:
                    break
                it = random.choices(keys, weights=weights)[0]
                p.items.append(it)
                got.append(ITEMS[it]["label"])
            if got:
                self.add_log(f"{p.name} {self.v(p, 'draw')}: {', '.join(got)}.", "item")
        ev = [("load", live, n - live)]
        if self.event:
            ev.append(("event", self.event))
        return ev

    def check_sudden(self):
        if not self.sudden and self.stage_winner is None and all(p.hp == 1 for p in self.players):
            self.sudden = True
            self.add_log("SUDDEN DEATH: both on 1 charge. Healing is off.", "live")
            return [("sudden",)]
        return []

    # ── dealer psychology
    def update_tell(self):
        """Roll a new tell whenever the chambered shell changes. Returns True if a new tell appeared."""
        d = self.dealer
        if not (self.vs_ai and d and d.get("tells")) or self.left() <= 0 or self.blind:
            self.tell = None
            return False
        key = (self.loads, self.pos, self.shells[self.pos])
        if key == self.tell_key:
            return False
        self.tell_key = key
        self.tell = None
        if random.random() >= TELL_CHANCE:
            return False
        acc = d["tells"]["acc"]
        if self.tilted and self.dealer_key == "liar":
            acc = 0.75
        truth = self.shells[self.pos]
        looks_live = truth if random.random() < acc else not truth
        self.tell = "sweat" if looks_live else "smug"
        self.add_log(f"{self.players[1].name}: {d['tells'][self.tell]}", "dealer")
        return True

    def make_tip(self):
        truth = self.shells[self.pos]
        know = self.effective_current(1)
        if self.tilted:
            claim = truth if random.random() < 0.7 else not truth
        elif know is None:
            claim = random.random() < 0.5
        else:
            claim = (not know) if random.random() < 0.7 else know
        self.tip = {"claim": claim, "truth": truth, "pos": self.pos, "load": self.loads, "called": False}
        return random.choice(LIAR_SAYS_LIVE if claim else LIAR_SAYS_BLANK)

    def can_call(self):
        t = self.tip
        return (bool(t) and not t["called"] and self.vs_ai and self.turn == 0 and self.stage_winner is None
                and self.left() > 0 and self.pos == t["pos"] and self.loads == t["load"])

    def call_bluff(self):
        t = self.tip
        t["called"] = True
        lied = t["claim"] != t["truth"]
        now = self.shells[self.pos]
        for pl in self.players:
            pl.known[self.pos] = now
        claim = "LIVE" if t["claim"] else "BLANK"
        if lied:
            self.add_log(f"You call the bluff. He said {claim}, and he LIED. He pays 1.", "hp")
            self.award(BLUFF_BONUS)
            self.damage(1, 1)
        else:
            self.add_log(f"You call the bluff. He said {claim}, and it was TRUE. You pay 1.", "live")
            self.damage(0, 1)
        return [("bluff", lied, t["claim"], now)] + self._drain() + self.check_sudden()

    def try_high_roller(self):
        if self.dealer_key != "gambler" or self.coin_used or self.blind or self.left() < 2:
            return []
        if random.random() >= HIGH_ROLLER_CHANCE:
            return []
        self.coin_used = True
        self.blind = 2
        self.add_log("HIGH ROLLER! The Gambler flips a coin: the next 2 shots are blind. "
                     "No items, no counter.", "dealer")
        return [("highroller",)]

    # ── shell bookkeeping
    def _advance(self):
        """Take the chambered shell out of the gun (fired or racked)."""
        k = self.pos
        val = self.shells[k]
        self.pos += 1
        self.spent.append(val)
        for pl in self.players:
            for h in pl.hints:
                if h[0] == k:
                    h[0] += 1
                    h[2] -= val
            pl.hints = [h for h in pl.hints if h[0] < h[1]]
        return val

    def damage(self, ti, dmg):
        """Deal damage through vests and charms. Returns (damage dealt, notes)."""
        t = self.players[ti]
        notes = []
        if dmg > 0 and t.vest:
            absorbed = min(t.vest, dmg)
            t.vest -= absorbed
            dmg -= absorbed
            notes.append(f"{self.poss(t)} vest absorbs {absorbed}")
        before = t.hp
        if dmg > 0 and t.hp - dmg <= 0 and "charm" in t.items:
            t.items.remove("charm")
            t.hp = 1
            notes.append(f"{self.poss(t)} Charm shatters: 1 charge left")
        else:
            t.hp = max(0, t.hp - dmg)
        if t.hp <= 0 and self.stage_winner is None:
            self.stage_winner = 1 - ti
            self.add_log(f"{t.name} {self.v(t, 'go')} down.", "live")
        for n in notes:
            self.add_log(n[0].upper() + n[1:] + ".", "item")
        dealt = before - t.hp
        tilt = (self.dealer or {}).get("tilt")
        if self.vs_ai and ti == 1 and dealt > 0 and self.stage_winner is None:
            self.dealer_hits += 1
            if self.dealer_hits >= 2 and tilt and not self.tilted:
                self.tilted = True
                self.add_log(f"{t.name} {self.v(t, 'be')} TILTED. {tilt['line']}", "dealer")
                self.fx.append(("tilt",))
        return dealt, notes

    def heal(self, i, amount):
        if self.sudden:
            return 0
        p = self.players[i]
        before = p.hp
        p.hp = min(p.max_hp, p.hp + amount)
        return p.hp - before

    # ── items
    def _can_apply(self, i, item, via_hook=False):
        p, o = self.players[i], self.players[1 - i]
        n = self.left()
        if item == "loupe" and self.pos in p.known:
            return False, "You already know the chambered shell."
        if item == "saw" and self.sawed:
            return False, "The barrel is already sawed off."
        if item == "shackles" and o.shackled:
            return False, f"{o.name} is already shackled."
        if item == "tonic":
            if self.sudden:
                return False, "Sudden death: no healing."
            if p.hp >= p.max_hp:
                return False, "Already at full charge."
        if item == "radio" and n < 2:
            return False, "No future shells to listen for."
        if item == "hook":
            if via_hook:
                return False, "You can't hook a Hook."
            if not self.stealable(i):
                return False, "Nothing worth stealing."
        if item == "charm":
            return False, "The Charm works on its own when a hit would knock you out."
        if item == "tarot" and n < 2:
            return False, "Too few shells left for a reading."
        if item == "shuffle" and n < 2:
            return False, "Nothing to shuffle."
        if item == "slip" and n >= 8:
            return False, "The gun is full."
        if item == "decoy" and len(o.items) >= MAX_ITEMS:
            return False, f"{o.name} has no room for a gift."
        if item == "double":
            if self.double:
                return False, "The Double is already loaded."
            if n < 2:
                return False, "Needs at least two shells in the gun."
        if item == "jammer" and self.jammed:
            return False, "The gun is already jammed."
        if item == "ricochet" and p.ricochet:
            return False, "Your Ricochet plate is already armed."
        if item == "leech" and p.leech:
            return False, "A Leech is already primed."
        if item == "vest" and p.vest:
            return False, "You're already wearing a Vest."
        if item == "muzzle" and o.muzzled:
            return False, f"{o.name} is already muzzled."
        if item == "pact" and p.hp == o.hp:
            return False, "Your charges are already equal."
        if item == "crowbar" and not o.items:
            return False, "Nothing to break."
        if item == "rewind" and not self.spent:
            return False, "No shell has left the gun this load."
        return True, ""

    def items_blocked(self, i):
        if self.event == "dry":
            return "Dry table: no items until the next reload."
        if self.blind:
            return "High-roller round: no items until the blind shots are fired."
        if self.players[i].muzzled:
            return "You're muzzled: no items this turn."
        return None

    def can_use(self, i, entry):
        p = self.players[i]
        if entry not in p.items:
            return False, "You don't have that item."
        why = self.items_blocked(i)
        if why:
            return False, why
        return self._can_apply(i, base(entry))

    def stealable(self, i):
        out = []
        for x in self.players[1 - i].items:
            if base(x) not in ("hook", "charm") and x not in out and self._can_apply(i, base(x), True)[0]:
                out.append(x)
        return out

    def legal_items(self, i):
        if self.items_blocked(i):
            return []
        out = []
        for x in self.players[i].items:
            b = base(x)
            if b not in out and self._can_apply(i, b)[0]:
                out.append(b)
        return out

    def _match(self, entries, want):
        """Resolve an item name to an inventory entry (exact first, else a random same-looking one)."""
        if want in entries:
            return want
        cands = [x for x in entries if base(x) == want]
        return random.choice(cands) if cands else None

    def _auto_arg(self, i, item):
        o = self.players[1 - i]
        if item == "crowbar":
            return random.choice(o.items) if o.items else None
        if item == "decoy":
            return random.choice(DECOY_FORMS)
        if item == "slip":
            return {"live": True, "pos": 1}
        if item == "hook":
            opts = self.stealable(i)
            return random.choice(opts) if opts else None
        return None

    def use_item(self, i, item, arg=None):
        """item may be an exact inventory entry (human) or a plain item name (AI)."""
        p, o = self.players[i], self.players[1 - i]
        entry = self._match(p.items, item)
        if entry is None:
            return False, "You don't have that item.", []
        ok, msg = self.can_use(i, entry)
        if not ok:
            return False, msg, []
        b = base(entry)
        if b == "hook":
            arg = self._match(self.stealable(i), arg) if arg else None
            if arg is None:
                return False, "Pick something to steal.", []
        if b == "crowbar":
            arg = self._match(o.items, arg) if arg else None
            if arg is None:
                return False, "Pick something to break.", []
        p.items.remove(entry)
        if entry.startswith("trap:"):
            ev = self._backfire(i, b)
        else:
            ev = self._apply(i, b, arg)
        if i == 0 and self.vs_ai and self.dealer_key == "accountant" and self.stage_winner is None:
            self.uses += 1
            if self.uses == 3 and p.items:
                gone = random.choice(p.items)
                p.items.remove(gone)
                label = ITEMS[base(gone)]["label"]
                self.add_log(f"AUDIT! The Accountant confiscates your {label}.", "dealer")
                self.fx.append(("audit", label))
        return True, "", ev + self._drain() + self.check_sudden()

    def _backfire(self, i, item):
        p = self.players[i]
        label = ITEMS[item]["label"]
        self.add_log(f"{p.name} {self.v(p, 'reach')} for the {label}... it was rigged! -1.", "live")
        ev = [("trap", i, label)]
        self.damage(i, 1)
        return ev

    def _apply(self, i, item, arg=None):
        p, o = self.players[i], self.players[1 - i]
        P = p.name
        ev = []
        if item == "loupe":
            live = self.shells[self.pos]
            p.known[self.pos] = live
            p.peeked = True
            self.add_log(f"{P} {self.v(p, 'peek')} into the chamber with a Loupe.", "item")
            ev.append(("private", i, f"The chambered shell is {'LIVE' if live else 'BLANK'}.", live))
        elif item == "rack":
            live = self._advance()
            self.add_log(f"{P} {self.v(p, 'rack')} the gun: a {'LIVE' if live else 'BLANK'} shell drops out.",
                         "live" if live else "blank")
            ev.append(("eject", live))
            if self.left() <= 0:
                self.needs_reload = True
                self.add_log("The gun is empty.", "info")
        elif item == "saw":
            self.sawed = True
            self.add_log(f"{P} {self.v(p, 'saw')} off the barrel. Next shot deals 2.", "item")
            ev.append(("minor",))
        elif item == "shackles":
            o.shackled = True
            self.add_log(f"{P} {self.v(p, 'shackle')} {self.obj(o)}.", "item")
            ev.append(("minor",))
        elif item == "tonic":
            self.heal(i, 1)
            self.add_log(f"{P} {self.v(p, 'drink')} a Tonic: +1 charge.", "item")
            ev.append(("minor",))
        elif item == "flipper":
            self.shells[self.pos] = not self.shells[self.pos]
            now = self.shells[self.pos]
            for pl in self.players:
                pl.known[self.pos] = now
                for h in pl.hints:
                    if h[0] <= self.pos < h[1]:
                        h[2] += 1 if now else -1
            self.add_log(f"{P} {self.v(p, 'flip')} the chambered shell. It's now {'LIVE' if now else 'BLANK'}.",
                         "live" if now else "blank")
            ev.append(("minor",))
        elif item == "radio":
            k = random.randrange(self.pos + 1, len(self.shells))
            live = self.shells[k]
            p.known[k] = live
            p.peeked = True
            self.add_log(f"{P} {self.v(p, 'tune')} the Radio. A voice whispers...", "item")
            ev.append(("private", i,
                       f"The {ordinal(k - self.pos + 1)} shell is {'LIVE' if live else 'BLANK'} "
                       f"(the chambered one is 1st).", live))
        elif item == "hook":
            o.items.remove(arg)
            label = ITEMS[base(arg)]["label"]
            self.add_log(f"{P} {self.v(p, 'hook')} {self.poss(o)} {label}!", "item")
            if arg.startswith("trap:"):
                ev += self._backfire(i, base(arg))
            else:
                b = base(arg)
                ev += self._apply(i, b, self._auto_arg(i, b))
        elif item == "pills":
            if random.random() < 0.5:
                got = self.heal(i, 2)
                if got:
                    self.add_log(f"{P} {self.v(p, 'swallow')} the Pills: +{got} charge{'s' if got > 1 else ''}.", "item")
                else:
                    self.add_log(f"{P} {self.v(p, 'swallow')} the Pills. Nothing happens.", "item")
                ev.append(("minor",))
            else:
                self.add_log(f"{P} {self.v(p, 'swallow')} the Pills. Bad batch: -1 charge.", "live")
                ev.append(("hurt", i))
                self.damage(i, 1)
        elif item == "snapshot":
            p.peeked = True
            vals = self.shells[self.pos:]
            if p.is_ai:  # dealers memorise the photo perfectly
                for k in range(self.pos, len(self.shells)):
                    p.known[k] = self.shells[k]
            self.add_log(f"{P} {self.v(p, 'snap')} a Snapshot of the chamber.", "item")
            ev.append(("snapshot", i, list(vals)))
        elif item == "tarot":
            p.peeked = True
            end = min(len(self.shells), self.pos + 3)
            cnt = sum(self.shells[self.pos:end])
            k = end - self.pos
            p.hints.append([self.pos, end, cnt])
            self.add_log(f"{P} {self.v(p, 'turn')} a Tarot card.", "item")
            ev.append(("private", i, f"{cnt} of the next {k} shells {'is' if cnt == 1 else 'are'} live.",
                       cnt > 0))
        elif item == "shuffle":
            rem = self.shells[self.pos:]
            random.shuffle(rem)
            self.shells[self.pos:] = rem
            for pl in self.players:
                pl.known = {k: v for k, v in pl.known.items() if k < self.pos}
                pl.hints = []
            self.add_log(f"{P} {self.v(p, 'shuffle')} the remaining shells. Everyone's notes are worthless.",
                         "item")
            ev.append(("minor",))
        elif item == "slip":
            arg = arg or {}
            live = bool(arg.get("live", True))
            rel = max(1, min(int(arg.get("pos", 1)), self.left() + 1))
            ins = self.pos + rel - 1
            self.shells.insert(ins, live)
            for pl in self.players:
                pl.known = {(k + 1 if k >= ins else k): v for k, v in pl.known.items()}
                pl.hints = []
            p.known[ins] = live
            lv, bl = self.loaded
            self.loaded = (lv + int(live), bl + int(not live))
            whom = "you know" if P == "You" else ("he knows" if p.is_ai else f"{P} knows")
            self.add_log(f"{P} {self.v(p, 'slip')} a {'LIVE' if live else 'BLANK'} shell into the gun. "
                         f"Only {whom} where.", "live" if live else "blank")
            ev.append(("minor",))
        elif item == "decoy":
            form = arg if arg in DECOY_FORMS else random.choice(DECOY_FORMS)
            o.items.insert(random.randint(0, len(o.items)), "trap:" + form)
            self.add_log(f"{P} {self.v(p, 'slide')} a gift across the table: a {ITEMS[form]['label']}. "
                         f"How generous.", "item")
            ev.append(("minor",))
        elif item == "double":
            self.double = True
            self.add_log(f"{P} {self.v(p, 'load')} the Double: the next shot fires two shells.", "item")
            ev.append(("minor",))
        elif item == "jammer":
            self.jammed = True
            self.add_log(f"{P} {self.v(p, 'fit')} a Jammer: if the next shell is live, it misfires.", "item")
            ev.append(("minor",))
        elif item == "ricochet":
            p.ricochet = True
            self.add_log(f"{P} {self.v(p, 'arm')} a Ricochet plate. The next shot at {self.obj(p)} bounces back.",
                         "item")
            ev.append(("minor",))
        elif item == "leech":
            p.leech = True
            self.add_log(f"{P} {self.v(p, 'prime')} a Leech: a hit on the next shot heals 1.", "item")
            ev.append(("minor",))
        elif item == "vest":
            p.vest = 1
            self.add_log(f"{P} {self.v(p, 'strap')} on a Vest.", "item")
            ev.append(("minor",))
        elif item == "muzzle":
            o.muzzled = True
            self.add_log(f"{P} {self.v(p, 'muzzle')} {self.obj(o)}: no items next turn.", "item")
            ev.append(("minor",))
        elif item == "pact":
            a, b = p.hp, o.hp
            p.hp, o.hp = min(p.max_hp, b), min(o.max_hp, a)
            self.add_log(f"{P} {self.v(p, 'sign')} a Pact. Charges swapped: {a} ⇄ {b}.", "dealer")
            ev.append(("minor",))
        elif item == "dice":
            roll = random.randint(1, 6)
            text = "Nothing happens."
            if roll == 1:
                text = "Snake eyes: -1 charge."
            elif roll == 2:
                if p.items:
                    lost = random.choice(p.items)
                    p.items.remove(lost)
                    text = f"Butterfingers: {ITEMS[base(lost)]['label']} dropped."
                else:
                    text = "Butterfingers, but there's nothing to drop."
            elif roll == 4:
                text = "A glimpse of the chamber."
            elif roll == 5:
                if self.heal(i, 1):
                    text = "+1 charge."
                else:
                    text = "+1 charge... but sudden death allows no healing." if self.sudden else \
                        "+1 charge, but already full."
            elif roll == 6:
                if o.shackled:
                    text = f"Shackles, but {self.obj(o)} {self.v(o, 'be')} already chained."
                else:
                    o.shackled = True
                    text = f"{self.obj(o)[0].upper() + self.obj(o)[1:]} {self.v(o, 'be')} shackled."
            self.add_log(f"{P} {self.v(p, 'roll')} the Dice: {roll}. {text}", "item")
            ev.append(("dice", i, roll, text))
            if roll == 1:
                self.damage(i, 1)
            elif roll == 4:
                live = self.shells[self.pos]
                p.known[self.pos] = live
                p.peeked = True
                ev.append(("private", i, f"The chambered shell is {'LIVE' if live else 'BLANK'}.", live))
        elif item == "crowbar":
            if arg in o.items:
                o.items.remove(arg)
                rigged = " It was rigged!" if arg.startswith("trap:") else ""
                self.add_log(f"{P} {self.v(p, 'smash')} {self.poss(o)} {ITEMS[base(arg)]['label']}.{rigged}",
                             "item")
            else:
                self.add_log(f"{P} {self.v(p, 'swing')} a Crowbar at nothing.", "item")
            ev.append(("minor",))
        elif item == "rewind":
            self.pos -= 1
            self.spent.pop()
            val = self.shells[self.pos]
            for pl in self.players:
                pl.known[self.pos] = val
            self.add_log(f"{P} {self.v(p, 'rewind')} the gun: a {'LIVE' if val else 'BLANK'} shell is back "
                         f"in the chamber.", "live" if val else "blank")
            ev.append(("minor",))
        return ev

    # ── shooting
    def shoot(self, i, at_self):
        p = self.players[i]
        ov = {"hp": {0: self.players[0].hp, 1: self.players[1].hp}, "pos": self.pos, "sawed": self.sawed,
              "spent": len(self.spent), "double": self.double, "jammed": self.jammed}
        aimed = i if at_self else 1 - i
        ti, rico = aimed, False
        if not at_self and self.players[aimed].ricochet:
            self.players[aimed].ricochet = False
            ti, rico = i, True
        t = self.players[ti]
        who = self.refl(p) if at_self else self.obj(self.players[aimed])
        self.add_log(f"{p.name} {self.v(p, 'shoot')} {who}.", "info")
        if rico:
            self.add_log(f"It bounces off the Ricochet plate, back at {self.obj(p)}!", "item")
        shots = 2 if self.double else 1
        self.double = False
        jam = self.jammed
        self.jammed = False
        results, fired_live = [], False
        for n in range(shots):
            if self.left() <= 0 or self.stage_winner is not None:
                break
            live = self._advance()
            r = {"live": live, "dmg": 0, "jam": None, "notes": []}
            if live:
                fired_live = True
                if jam and n == 0:
                    r["jam"] = "jammer"
                    self.add_log("Live shell... but the Jammer holds. It misfires!", "blank")
                elif self.opts["misfires"] and random.random() < MISFIRE_CHANCE:
                    r["jam"] = "misfire"
                    self.add_log("Live shell... and it MISFIRES! A dud.", "blank")
                else:
                    dealt, notes = self.damage(ti, self.live_damage(first=(n == 0)))
                    r["dmg"], r["notes"] = dealt, notes
                    self.add_log(f"BANG! {t.name} {self.v(t, 'lose')} {dealt}.", "live")
                    gain = (1 if p.leech else 0) + (1 if self.event == "blood" else 0)
                    if ti != i and dealt > 0 and gain:
                        got = self.heal(i, gain)
                        if got:
                            r["notes"].append(f"{p.name} {self.v(p, 'drain')} {got} charge back")
                            self.add_log(f"{p.name} {self.v(p, 'drain')} {got} charge back.", "hp")
                    if self.vs_ai and i == 0 and ti == 1:
                        self.award(100 * dealt)
                    if self.vs_ai and i == 1 and ti == 0 and dealt > 0:
                        self.dealer_hits = 0
                        if self.tilted:
                            self.tilted = False
                            self.add_log(f"{p.name} {self.v(p, 'regain')} his composure.", "dealer")
                            self.fx.append(("calm",))
            else:
                self.add_log("Click. Blank." + (" Extra turn." if at_self and shots == 1 else ""), "blank")
                if self.vs_ai and i == 0 and at_self:
                    self.award(150)
            results.append(r)
        self.sawed = False
        p.leech = False
        if self.blind:
            self.blind -= 1
            if not self.blind:
                self.add_log("The high-roller round is over. Items are back on the table.", "dealer")
        ev = [("shot", i, ti, results, ov, rico)] + self._drain()
        if self.stage_winner is not None:
            return ev
        ev += self.check_sudden()
        if not (at_self and not fired_live):
            self.pass_turn()
        if self.left() <= 0:
            self.needs_reload = True
            self.add_log("The gun is empty.", "info")
        return ev

    def pass_turn(self):
        self.uses = 0
        self.players[self.turn].muzzled = False
        nxt = self.players[1 - self.turn]
        if nxt.shackled:
            nxt.shackled = False
            self.add_log(f"{nxt.name} {self.v(nxt, 'be')} shackled and {self.v(nxt, 'lose')} a turn.", "item")
        else:
            self.turn = 1 - self.turn


# ═════════════════════════════ built-in dealer strategies ═════════════════════════════
def _use(item, arg=None):
    return {"action": "use_item", "item": item, "arg": arg}


def _opp():
    return {"action": "shoot_opponent"}


def _me():
    return {"action": "shoot_self"}


CROWBAR_PRIORITY = ["charm", "saw", "loupe", "double", "tonic", "vest", "snapshot", "shackles", "jammer",
                    "ricochet", "leech", "hook"]


def extras(g, i, c, reckless):
    """Opportunistic uses of the newer items. Returns an action or None."""
    L, p, o, cur = c["L"], c["p"], c["o"], c["cur"]
    if "decoy" in L:
        return _use("decoy", random.choice(DECOY_FORMS))
    if "vest" in L:
        return _use("vest")
    if "ricochet" in L:
        return _use("ricochet")
    if "pact" in L and o.hp - p.hp >= 2:
        return _use("pact")
    if "muzzle" in L and len(o.items) >= 2:
        return _use("muzzle")
    if "crowbar" in L:
        names = [base(x) for x in o.items]
        for want in CROWBAR_PRIORITY:
            if want in names:
                return _use("crowbar", want)
    if "rewind" in L and g.spent and g.spent[-1] and cur is not True:
        return _use("rewind")
    if cur is None:
        if "snapshot" in L:
            return _use("snapshot")
        if "shuffle" in L and o.peeked:
            return _use("shuffle")
        if "slip" in L:
            return _use("slip", {"live": True, "pos": 1})
        if "tarot" in L and "loupe" not in L:
            return _use("tarot")
    if "dice" in L and p.hp >= 2 and (reckless or (p.hp == p.max_hp and random.random() < 0.3)):
        return _use("dice")
    return None


def pre_shot(g, i, c, d, reckless):
    """Last-second boosters before a shot."""
    L, p, cur, pl = c["L"], c["p"], c["cur"], c["pl"]
    if d["action"] == "shoot_self":
        if "jammer" in L and cur is not False:
            return _use("jammer")
    elif d["action"] == "shoot_opponent":
        if "leech" in L and (cur is True or pl >= 0.6):
            return _use("leech")
        nxt = p.known.get(g.pos + 1)
        if "double" in L and cur is True and (nxt is True or (reckless and nxt is None)):
            return _use("double")
    return d


def strat_croupier(g, i, c):
    L, st, cur, pl, p, o, n = c["L"], c["st"], c["cur"], c["pl"], c["p"], c["o"], c["n"]
    if "tonic" in L:
        return _use("tonic")
    if "pills" in L and p.hp >= 2 and p.max_hp - p.hp >= 2:
        return _use("pills")
    if cur is None:
        if "loupe" in L:
            return _use("loupe")
        if "loupe" in st:
            return _use("hook", "loupe")
        if "radio" in L and n > 2 and random.random() < 0.4:
            return _use("radio")
        if "rack" in L and 0.4 <= pl <= 0.6:
            return _use("rack")
        if pl >= 0.5:
            if "saw" in L and pl >= 0.65 and o.hp > 1:
                return _use("saw")
            return _opp()
        if "flipper" in L and pl <= 0.25:
            return _use("flipper")
        return _me()
    if cur:
        if "shackles" in L and n > 1:
            return _use("shackles")
        if "saw" in L and o.hp > 1:
            return _use("saw")
        if "saw" in st and o.hp > 1:
            return _use("hook", "saw")
        return _opp()
    if "flipper" in L:
        return _use("flipper")
    return _me()


def strat_accountant(g, i, c):
    L, st, cur, pl, o, n = c["L"], c["st"], c["cur"], c["pl"], c["o"], c["n"]
    if "tonic" in L:
        return _use("tonic")
    if cur is None:
        if "loupe" in L:
            return _use("loupe")
        if "loupe" in st:
            return _use("hook", "loupe")
        if "radio" in L:
            return _use("radio")
        if "rack" in L and 0.3 <= pl <= 0.7:
            return _use("rack")
        return _me() if pl <= 0.3 else _opp()
    if cur:
        if "shackles" in L and n > 1:
            return _use("shackles")
        if "saw" in L and o.hp > 1:
            return _use("saw")
        return _opp()
    return _me()


def strat_gambler(g, i, c):
    L, cur, pl, p = c["L"], c["cur"], c["pl"], c["p"]
    if random.random() < 0.2:
        if L and random.random() < 0.5:
            it = random.choice(L)
            return _use(it, g._auto_arg(i, it))
        return random.choice([_opp, _me])()
    if "pills" in L and p.hp < p.max_hp:
        return _use("pills")
    if "tonic" in L and p.hp <= 1:
        return _use("tonic")
    if "saw" in L and (cur is True or (cur is None and pl >= 0.5)):
        return _use("saw")
    if cur is None:
        if "loupe" in L and random.random() < 0.25:
            return _use("loupe")
        if "flipper" in L and random.random() < 0.35:
            return _use("flipper")
        return _me() if pl <= 0.5 else _opp()
    return _opp() if cur else _me()


def strat_liar(g, i, c):
    L, st, cur, pl, o, n = c["L"], c["st"], c["cur"], c["pl"], c["o"], c["n"]
    if "tonic" in L:
        return _use("tonic")
    if cur is None:
        if "loupe" in L:
            return _use("loupe")
        if "loupe" in st:
            return _use("hook", "loupe")
        if "radio" in L and random.random() < 0.5:
            return _use("radio")
        if "flipper" in L and pl <= 0.35:
            return _use("flipper")
        if pl >= 0.5:
            if "saw" in L and pl >= 0.65 and o.hp > 1:
                return _use("saw")
            return _opp()
        return _me()
    if cur:
        if "shackles" in L and n > 1:
            return _use("shackles")
        if "saw" in L and o.hp > 1:
            return _use("saw")
        if "saw" in st and o.hp > 1:
            return _use("hook", "saw")
        return _opp()
    if "flipper" in L:
        return _use("flipper")
    return _me()


STRATEGIES = {"accountant": strat_accountant, "gambler": strat_gambler,
              "liar": strat_liar, "croupier": strat_croupier}


def dealer_decision(g, i, allow_items=True):
    legal = g.legal_items(i) if allow_items else []
    c = {"L": legal, "st": [base(x) for x in g.stealable(i)] if "hook" in legal else [],
         "cur": g.effective_current(i), "pl": g.chance_live(i),
         "p": g.players[i], "o": g.players[1 - i], "n": g.left()}
    key = g.dealer_key
    reckless = key == "gambler"
    if g.tilted:  # tilt flips the cautious and the reckless
        if key == "accountant":
            key, reckless = "gambler", True
        elif key == "gambler":
            key, reckless = "accountant", False
    d = extras(g, i, c, reckless) if legal else None
    if d is None:
        d = STRATEGIES.get(key, strat_croupier)(g, i, c)
        if d["action"] != "use_item" and legal:
            d = pre_shot(g, i, c, d, reckless)
    d.setdefault("arg", None)
    return d


# ═════════════════════════════ AI prompts ═════════════════════════════
SYSTEM_RULES = """You are {name}, an opponent in SHELL GAME, a turn-based terminal duel.
A shotgun is loaded with a publicly known number of LIVE and BLANK shells in a hidden random order.

Rules:
- On your turn you may use items one at a time, then you must shoot: yourself or your opponent.
- A live shell removes 1 charge from the target (2 if the saw is active). A blank does nothing.
- Shooting YOURSELF with a BLANK lets you keep your turn. Every other shot ends your turn.
- A player at 0 charges loses the stage. When the gun is empty it is reloaded and both players draw new items.
- Misfires: when "misfire_chance" is above 0, any live shell may fizzle harmlessly.
- Sudden death: once both players are on 1 charge, all healing stops for the rest of the stage.
- Table events: "table_event" in the state changes the rules until the next reload:
  blackout (no remaining-shell counter), stakes (+1 damage per live shell), generous (extra items),
  dry (no items can be used), hot (the last shell is live), rush (a clock on the human; ignore it),
  blood (every hit on the opponent heals the shooter 1).
- A high-roller round ("blind_shots_remaining" above 0) means nobody can use items until those shots are fired.

Items (use the lowercase key):
- loupe: privately see the chambered shell.
- rack: eject the chambered shell without firing; everyone sees it.
- saw: your next shot deals 2 damage (first shell only if doubled).
- shackles: your opponent skips their next turn.
- tonic: +1 charge (not above max).
- flipper: invert the chambered shell; the new value is announced to everyone.
- radio: privately learn one random future shell (position 1 = chambered).
- hook: steal one opponent item (not hook/charm) and use it immediately. Set "target" to its name.
- pills: 50% chance +2 charges, 50% chance -1 charge.
- snapshot: you see and remember every remaining shell.
- tarot: privately learn how many of the next 3 shells are live.
- shuffle: reshuffle the remaining shells; everyone's knowledge of them is wiped.
- slip: insert a shell. Set "slip_live" (true/false) and "slip_position" (1 = chamber). The opponent sees the kind, not the position.
- decoy: give your opponent a rigged item that costs them 1 charge when used. Set "disguise" to tonic, loupe, saw, vest or rack.
- double: your next shot fires the next two shells at the same target.
- jammer: if the next shell fired (by anyone) is live, it misfires harmlessly.
- ricochet: the next shot your opponent aims at you bounces back at them.
- leech: if your next shot hits your opponent, you gain 1 charge.
- vest: absorbs the next 1 damage you take.
- charm: passive, cannot be used; saves you once from a lethal hit, leaving 1 charge.
- muzzle: your opponent can't use items on their next turn.
- pact: swap charge totals with your opponent.
- dice: 1 lose a charge, 2 lose an item, 3 nothing, 4 see the chambered shell, 5 +1 charge, 6 shackle opponent.
- crowbar: destroy one opponent item. Set "target" to its name.
- rewind: put the last shell that left the gun (value known to all) back in the chamber.
Beware: items your opponent gave you may be rigged decoys.

You receive the game state as JSON. Choose exactly ONE next action; you will be asked again after each item.
Only use items listed in "usable_items". Stay in character: your personality below decides your strategy.

Reply with a single JSON object only, no prose and no code fences:
{"action": "use_item" | "shoot_self" | "shoot_opponent", "item": "<item or null>", "target": "<item or null>", "disguise": "<item or null>", "slip_live": true, "slip_position": 1, "taunt": "<one short in-character line, max 60 characters>"}"""


def build_system_prompt(g):
    d = g.dealer
    text = SYSTEM_RULES.replace("{name}", d["name"].upper()) + "\n\nPersonality:\n" + d["prompt"]
    if g.tilted and d.get("tilt"):
        text += "\n\nRIGHT NOW: " + d["tilt"]["prompt"]
    return text


def ai_state(g, i, step):
    p, o = g.players[i], g.players[1 - i]
    live, blank = g.remaining()
    cur = g.effective_current(i)
    future = {str(k - g.pos + 1): ("live" if v else "blank")
              for k, v in sorted(p.known.items()) if k > g.pos}
    hints = [{"from_position": h[0] - g.pos + 1, "to_position": h[1] - g.pos, "live_count": h[2]}
             for h in p.hints if h[0] >= g.pos]
    return {
        "you_are": p.name, "opponent": o.name, "stage": g.stage,
        "your_charges": p.hp, "max_charges": p.max_hp, "opponent_charges": o.hp,
        "shells_remaining": live + blank, "live_remaining": live, "blank_remaining": blank,
        "chambered_shell": "unknown" if cur is None else ("live" if cur else "blank"),
        "chance_chambered_is_live": round(g.chance_live(i), 2),
        "known_future_shells": future, "tarot_readings": hints,
        "last_shell_out": None if not g.spent else ("live" if g.spent[-1] else "blank"),
        "table_event": g.event, "sudden_death": g.sudden,
        "misfire_chance": MISFIRE_CHANCE if g.opts["misfires"] else 0,
        "live_shell_damage": g.live_damage(), "you_are_tilted": g.tilted,
        "blind_shots_remaining": g.blind,
        "saw_active": g.sawed, "double_loaded": g.double, "jammer_set": g.jammed,
        "you": {"vest": p.vest, "ricochet_armed": p.ricochet, "leech_primed": p.leech,
                "muzzled": p.muzzled, "has_charm": "charm" in p.items},
        "opponent_status": {"shackled": o.shackled, "muzzled": o.muzzled, "vest": o.vest,
                            "ricochet_armed": o.ricochet, "has_charm": "charm" in o.items,
                            "peeked_this_load": o.peeked},
        "your_items": [base(x) for x in p.items], "opponent_items": [base(x) for x in o.items],
        "usable_items": g.legal_items(i),
        "stealable_with_hook": [base(x) for x in g.stealable(i)] if "hook" in [base(x) for x in p.items] else [],
        "items_used_this_turn": step,
        "recent_events": [t for t, _ in g.log[-8:]],
    }


def parse_json_obj(text):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except ValueError:
            return None
    return None


def clean_taunt(t):
    if not isinstance(t, str):
        return ""
    t = " ".join(t.split())
    t = "".join(ch for ch in t if ch.isprintable() and ord(ch) < 0x2E80)
    return t[:60]


def validate_decision(g, i, d):
    if isinstance(d, list) and d:
        d = d[0]
    if not isinstance(d, dict):
        return None
    act = str(d.get("action", "")).strip().lower()
    taunt = clean_taunt(d.get("taunt"))
    if act in ("shoot_self", "shoot_opponent"):
        return {"action": act, "taunt": taunt}
    if act != "use_item":
        return None
    item = str(d.get("item") or "").strip().lower()
    if item not in g.legal_items(i):
        return None
    arg = None
    if item in ("hook", "crowbar"):
        t = str(d.get("target") or d.get("steal") or "").strip().lower()
        pool = g.stealable(i) if item == "hook" else g.players[1 - i].items
        opts = [base(x) for x in pool]
        arg = t if t in opts else random.choice(opts)
    elif item == "decoy":
        t = str(d.get("disguise") or "").strip().lower()
        arg = t if t in DECOY_FORMS else random.choice(DECOY_FORMS)
    elif item == "slip":
        raw = d.get("slip_live")
        live = raw if isinstance(raw, bool) else (True if raw is None else str(raw).lower() in ("true", "live", "1", "yes"))
        try:
            pos = int(d.get("slip_position") or 1)
        except (TypeError, ValueError):
            pos = 1
        arg = {"live": live, "pos": pos}
    return {"action": "use_item", "item": item, "arg": arg, "taunt": taunt}


# ═════════════════════════════ networking ═════════════════════════════
class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg

    def __str__(self):
        return f"HTTP {self.code}: {self.msg}" if self.code else self.msg


def _parse_sse(raw):
    """Collapse an OpenAI-style SSE stream into one chat.completion response."""
    text = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue
        for ch in chunk.get("choices") or []:
            part = ch.get("delta") or ch.get("message") or {}
            if isinstance(part.get("content"), str):
                text.append(part["content"])
    return {"choices": [{"message": {"content": "".join(text)}}]}


def http_json(url, body=None, headers=None, timeout=API_TIMEOUT):
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=hdrs, method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        msg = detail.strip()
        try:
            j = json.loads(detail)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code") or msg
            elif isinstance(err, str):
                msg = err
            elif isinstance(j, dict) and j.get("message"):
                msg = j["message"]
        except ValueError:
            pass
        msg = " ".join(str(msg).split())[:140]
        if e.code in FRIENDLY_HTTP:
            msg = f"{FRIENDLY_HTTP[e.code]} ({msg})" if msg else FRIENDLY_HTTP[e.code]
        raise ApiError(e.code, msg)
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise ApiError(0, "SSL certificates missing: run 'Install Certificates.command' for your Python")
        raise ApiError(0, f"can't connect ({e.reason})")
    except (socket.timeout, TimeoutError):
        raise ApiError(0, "request timed out")
    except OSError as e:
        raise ApiError(0, f"connection error ({e})")
    except ValueError as e:
        raise ApiError(0, f"bad URL ({e})")
    try:
        return json.loads(raw)
    except ValueError:
        if "data:" in raw:
            return _parse_sse(raw)
        raise ApiError(0, "the server didn't return JSON")


# ═════════════════════════════ keychain & config ═════════════════════════════
def keychain_ok():
    return sys.platform == "darwin" and shutil.which("security") is not None


def _security(args):
    try:
        return subprocess.run(["security"] + args, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None


def keychain_get(account):
    r = _security(["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"])
    if r and r.returncode == 0:
        return r.stdout.rstrip("\n") or None
    return None


def keychain_set(account, secret):
    r = _security(["add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", account,
                   "-l", f"Shell Game ({account})", "-w", secret])
    return bool(r and r.returncode == 0)


def keychain_delete(account):
    r = _security(["delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account])
    return bool(r and r.returncode == 0)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass


def detect_provider():
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("SLEEPYAI_API_KEY"):
        return "sleepyai"
    return "off"


class Config:
    def __init__(self):
        d = load_json(CONFIG_FILE)
        for k, t in (("models", dict), ("base_urls", dict), ("unlocked", list), ("prefs", dict)):
            if not isinstance(d.get(k), t):
                d[k] = t()
        if d.get("provider") not in PROVIDERS:
            d["provider"] = detect_provider()
        prefs = d["prefs"]
        for k, v in DEFAULT_PREFS.items():
            prefs.setdefault(k, v)
        if prefs["theme"] not in THEMES:
            prefs["theme"] = "casino"
        if prefs["speed"] not in SPEEDS:
            prefs["speed"] = "normal"
        if prefs["clock"] not in CLOCK_OPTIONS:
            prefs["clock"] = "off"
        self.data = d

    @property
    def prefs(self):
        return self.data["prefs"]

    def save(self):
        save_json(CONFIG_FILE, self.data)

    def unlocked(self, key):
        return not DEALERS[key].get("locked") or key in self.data["unlocked"]

    def unlock(self, key):
        if key in self.data["unlocked"]:
            return False
        self.data["unlocked"].append(key)
        self.save()
        return True


# ═════════════════════════════ AI brain ═════════════════════════════
class Brain:
    SKIP_MODELS = ("embed", "tts", "whisper", "dall-e", "image", "audio", "realtime", "transcri",
                   "moderation", "sora")

    def __init__(self, config, offline=False):
        self.config, self.offline = config, offline
        self.session_keys, self._key_cache = {}, {}
        self.reset()

    @property
    def provider(self):
        p = self.config.data.get("provider", "off")
        return "off" if self.offline or p not in PROVIDERS else p

    def model(self, p=None):
        p = p or self.provider
        return self.config.data["models"].get(p) or PROVIDERS[p].get("model", "")

    def base_url(self, p=None):
        p = p or self.provider
        return (self.config.data["base_urls"].get(p) or PROVIDERS[p].get("base", "")).rstrip("/")

    def needs_key(self, p=None):
        return PROVIDERS[p or self.provider].get("needs_key", True)

    def key(self, p=None):
        """Returns (key or None, where it came from)."""
        p = p or self.provider
        if p == "off":
            return None, "-"
        if p in self.session_keys:
            return self.session_keys[p], "this session only"
        if p not in self._key_cache:
            self._key_cache[p] = keychain_get(p) if keychain_ok() else None
        if self._key_cache[p]:
            return self._key_cache[p], "macOS Keychain"
        for env in PROVIDERS[p].get("env", []):
            if os.environ.get(env):
                return os.environ[env], f"${env}"
        return None, "not needed" if not self.needs_key(p) else "not set"

    def set_key(self, secret):
        p = self.provider
        self._key_cache.pop(p, None)
        if keychain_ok() and keychain_set(p, secret):
            self.session_keys.pop(p, None)
            self._key_cache[p] = secret
            return "Key saved to the macOS Keychain."
        self.session_keys[p] = secret
        return "Couldn't reach the Keychain, so the key is kept for this session only."

    def delete_key(self):
        p = self.provider
        self.session_keys.pop(p, None)
        self._key_cache.pop(p, None)
        if keychain_ok() and keychain_delete(p):
            return "Key removed from the Keychain."
        return "Session key cleared."

    def missing(self):
        p = self.provider
        out = []
        if p == "off":
            return out
        if self.needs_key() and not self.key()[0]:
            out.append("an API key")
        if not self.base_url():
            out.append("a base URL")
        if not self.model():
            out.append("a model")
        return out

    def ready(self):
        return self.provider != "off" and not self.missing()

    def reset(self):
        self.enabled = self.ready()
        self.failures = 0
        self.gem_thinking = True
        self.json_mode = PROVIDERS[self.provider].get("json_mode", True)

    def short_label(self):
        return PROVIDERS[self.provider]["short"] if self.enabled else "built-in"

    def status_line(self):
        if self.offline:
            return "AI: off (--offline). Dealers use their built-in strategies.", "dim"
        p = self.provider
        if p == "off":
            return "AI: off. Dealers use built-in strategies. Open Settings to connect Gemini or SleepyAI.", "dim"
        label = PROVIDERS[p]["label"]
        miss = self.missing()
        if miss:
            return f"AI: {label} needs {' and '.join(miss)}. Open Settings.", "item"
        return f"AI: {label} · {self.model()} · key: {self.key()[1]}", "hp"

    def complete(self, system, user, think="low"):
        p = self.provider
        kind = PROVIDERS[p]["kind"]
        key = self.key(p)[0]
        if kind == "gemini":
            return self._gemini(system, user, think, key)
        if kind == "openai":
            return self._chat(system, user, key)
        raise ApiError(0, "no AI provider selected")

    def _gemini(self, system, user, think, key):
        gen = {"responseMimeType": "application/json"}
        if self.gem_thinking:
            gen["thinkingConfig"] = {"thinkingLevel": think}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": gen}
        url = f"{self.base_url()}/models/{self.model()}:generateContent"
        try:
            resp = http_json(url, body, {"Content-Type": "application/json", "x-goog-api-key": key or ""})
        except ApiError as e:
            if e.code == 400 and self.gem_thinking and "think" in e.msg.lower():
                self.gem_thinking = False
                return self._gemini(system, user, think, key)
            raise
        cands = resp.get("candidates") or []
        if not cands:
            raise ApiError(0, "empty reply")
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts if not part.get("thought"))

    def _chat(self, system, user, key):
        """OpenAI Chat Completions format, as used by SleepyAI."""
        body = {"model": self.model(), "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = http_json(f"{self.base_url()}/chat/completions", body, headers)
        except ApiError as e:
            low = e.msg.lower()
            if e.code in (400, 422) and self.json_mode and ("response_format" in low or "json" in low):
                self.json_mode = False
                return self._chat(system, user, key)
            raise
        choices = resp.get("choices") or []
        if not choices:
            raise ApiError(0, "empty reply")
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return content or ""

    def list_models(self):
        p = self.provider
        key = self.key(p)[0]
        if PROVIDERS[p]["kind"] == "gemini":
            resp = http_json(f"{self.base_url()}/models?pageSize=1000", None, {"x-goog-api-key": key or ""})
            out = []
            for m in resp.get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    name = m.get("name", "")
                    out.append(name.split("/", 1)[1] if name.startswith("models/") else name)
            return sorted(set(out))
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        resp = http_json(f"{self.base_url()}/models", None, headers)
        items = (resp.get("data") or resp.get("models") or []) if isinstance(resp, dict) else resp
        ids = []
        for m in items if isinstance(items, list) else []:
            if isinstance(m, str):
                ids.append(m)
            elif isinstance(m, dict) and m.get("active", True) is not False:
                mid = m.get("id") or m.get("model") or m.get("name") or m.get("slug")
                if mid:
                    ids.append(str(mid))
        out = [x for x in ids if not any(s in x.lower() for s in self.SKIP_MODELS)] or ids
        return sorted(set(out))

    def test(self):
        if self.provider == "off":
            raise ApiError(0, "pick a provider first")
        miss = self.missing()
        if miss:
            raise ApiError(0, f"add {' and '.join(miss)} first")
        t0 = time.time()
        text = self.complete('Reply with the JSON object {"ok": true} and nothing else.', "ping", "low")
        if not isinstance(parse_json_obj(text), (dict, list)):
            raise ApiError(0, f"unexpected reply: {text[:60]!r}")
        return time.time() - t0

    def note_failure(self, err):
        self.failures += 1
        if self.failures >= 3:
            self.enabled = False
            return f"AI unavailable ({err}). Built-in strategy takes over."
        return f"AI hiccup ({err}). The dealer improvised."


class Worker(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.result, self.error = fn, None, None

    def run(self):
        try:
            self.result = self.fn()
        except Exception as e:  # noqa: BLE001 - surfaced to the player
            self.error = e


# ═════════════════════════════ scores ═════════════════════════════
def user_name():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "player"


def load_scores():
    return load_json(SCORE_FILE)


def best_score(key):
    lst = load_scores().get(key, [])
    return max((e.get("score", 0) for e in lst if isinstance(e, dict)), default=0)


def record_score(key, score, result):
    if score <= 0:
        return False
    data = load_scores()
    lst = [e for e in data.get(key, []) if isinstance(e, dict)]
    best = score > max((e.get("score", 0) for e in lst), default=0)
    lst.append({"name": user_name(), "score": int(score), "result": result, "date": date.today().isoformat()})
    lst.sort(key=lambda e: -e.get("score", 0))
    data[key] = lst[:10]
    save_json(SCORE_FILE, data)
    return best


MENU = [
    ("duel", "Duel a dealer", "Pick one of four opponents and survive three stages."),
    ("gauntlet", "Gauntlet (endless)", "Face every dealer in turn. Double or nothing between stages."),
    ("hotseat", "Hot-seat", "Two players, one keyboard, best of three stages."),
    ("items", "Item guide", "All 25 items: what they do and when to use them."),
    ("scores", "High scores", "Your best runs against each dealer."),
    ("settings", "Settings", "AI, theme, sound, speed, mouse, table events, misfires and shot clock."),
    ("help", "How to play", "The rules on one screen."),
    ("quit", "Quit", "Leave the table."),
]

HELP_TEXT = [
    ("THE GUN", True),
    ("Each load holds a known mix of LIVE and BLANK shells in a hidden order. Use items, then", False),
    ("shoot your opponent or yourself. Live: the target loses 1 (2 sawed off). A blank at", False),
    ("yourself keeps your turn. 0 charges loses the stage. An empty gun reloads with new items.", False),
    ("THE TABLE", True),
    ("Reloads may flip an event: Blackout, Double Stakes, Generous House, Dry Table, Hot Barrel,", False),
    ("Rush Hour or Blood Moon. Live shells misfire 5% of the time. Both on 1 = SUDDEN DEATH.", False),
    ("READING THE DEALER", True),
    ("Tells: watch his face and the line under his items. The Accountant and the Gambler give", False),
    ("honest tells about live shells, the Liar fakes his, and the Croupier has none.", False),
    ("Tilt: hit a dealer twice in a row and he tilts. The Accountant turns reckless, the", False),
    ("Gambler turns timid and the Liar turns honest. Landing a hit on you calms him down.", False),
    ("Bluffs: after his turn the Liar tips you off. Press C to call it: if he lied he loses", False),
    ("1 charge (and you score a bonus); if he told the truth, you lose 1.", False),
    ("HOUSE RULES", True),
    ("Accountant: 3 items in one turn and he confiscates one. Gambler: once a stage, two blind", False),
    ("shots with no items and no counter. Croupier: sees the first shell of every load.", False),
    ("MODES", True),
    ("Duel one dealer for 3 stages, the endless Gauntlet with double or nothing, or Hot-seat.", False),
    ("CONTROLS", True),
    ("←→ select · ↑↓ items/actions · Enter use · 1-8 item · S self · O opponent · C call bluff", False),
    ("? help · I item guide · Q menu. The mouse works too: click items, buttons and dealers.", False),
]


# ═════════════════════════════ UI ═════════════════════════════
class UI:
    KEYMAP = {curses.KEY_UP: "UP", curses.KEY_DOWN: "DOWN", curses.KEY_LEFT: "LEFT", curses.KEY_RIGHT: "RIGHT",
              curses.KEY_PPAGE: "PGUP", curses.KEY_NPAGE: "PGDN", curses.KEY_HOME: "HOME", curses.KEY_END: "END",
              curses.KEY_BTAB: "BTAB", curses.KEY_ENTER: "ENTER", curses.KEY_BACKSPACE: "BACKSPACE",
              curses.KEY_DC: "BACKSPACE", curses.KEY_RESIZE: "RESIZE"}

    def __init__(self, scr, config):
        self.scr = scr
        self.config = config
        self.oy = self.ox = 0
        self.shake_x = 0
        self.hits = []
        self.brain = None
        self.c = {}
        self.has_color = curses.has_colors()
        self.default_bg = -1
        self.new_game()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        scr.keypad(True)
        if self.has_color:
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                self.default_bg = curses.COLOR_BLACK
        self.apply_theme()
        self.apply_mouse()

    # ── preferences
    @property
    def prefs(self):
        return self.config.prefs

    @property
    def speed(self):
        return SPEEDS.get(self.prefs["speed"], 1.0)

    def apply_theme(self):
        if not self.has_color:
            return
        theme = THEMES.get(self.prefs["theme"], THEMES["casino"])
        for n, role in enumerate(ROLES, 1):
            fg, bg = theme[role]
            fgc = getattr(curses, "COLOR_" + fg)
            bgc = self.default_bg if bg is None else getattr(curses, "COLOR_" + bg)
            try:
                curses.init_pair(n, fgc, bgc)
                self.c[role] = curses.color_pair(n)
            except curses.error:
                pass

    def apply_mouse(self):
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS if self.prefs["mouse"] else 0)
            curses.mouseinterval(0)
        except curses.error:
            pass

    def sound(self, name):
        if not self.prefs["sound"] or sys.platform != "darwin":
            return
        path = os.path.join(SOUND_DIR, SOUNDS.get(name, "Pop") + ".aiff")
        if not os.path.exists(path) or not shutil.which("afplay"):
            return
        try:
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def clock_limit(self, g):
        if g.event == "rush":
            return RUSH_SECONDS
        c = self.prefs.get("clock", "off")
        return int(c) if c != "off" else None

    def new_game(self):
        self.msg = ""
        self.speech = ""
        self.face, self.face_until = "idle", 0.0
        self.thinking = False
        self.override = None
        self.aim = None
        self.focus = 0
        self.clock_deadline = None

    # ── primitives
    def col(self, k, default=0):
        return self.c.get(k, default)

    def sel_attr(self):
        return self.col("title", curses.A_REVERSE) | curses.A_BOLD

    def frame(self):
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        self.hits = []
        if h < H or w < W:
            lines = [f"SHELL GAME needs a terminal of at least {W}x{H} (yours is {w}x{h}).",
                     "Resize the window, or press Cmd - to shrink the font."]
            for k, m in enumerate(lines):
                try:
                    self.scr.addstr(k, 0, m[:max(0, w - 1)])
                except curses.error:
                    pass
            self.scr.refresh()
            return False
        self.oy, self.ox = (h - H) // 2, (w - W) // 2
        return True

    def put(self, y, x, s, attr=0):
        if y < 0 or y >= H or x < 0 or x >= W or not s:
            return
        try:
            self.scr.addstr(self.oy + y, self.ox + x + self.shake_x, s[:W - x], attr)
        except curses.error:
            pass

    def centered(self, y, text, attr=0):
        self.put(y, max(0, (W - len(text)) // 2), text, attr)

    def segs(self, y, x, parts):
        for t, a in parts:
            self.put(y, x, t, a)
            x += len(t)

    def hit(self, y, x, w, tok):
        self.hits.append((y, x, x + w, tok))

    def box(self, y, x, h, w, title="", attr=0, tattr=None):
        self.put(y, x, "╭" + "─" * (w - 2) + "╮", attr)
        for r in range(1, h - 1):
            self.put(y + r, x, "│", attr)
            self.put(y + r, x + w - 1, "│", attr)
        self.put(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", attr)
        if title:
            self.put(y, x + 2, f" {title} ", curses.A_BOLD if tattr is None else tattr)

    def popup(self, lines, width=None, battr=None, align="center", buttons=None, title=""):
        rows = [(l, 0) if isinstance(l, str) else l for l in lines]
        blen = sum(len(b[0]) + 4 for b in buttons) + 2 * (len(buttons) - 1) if buttons else 0
        iw = width or max([len(t) for t, _ in rows] + [16, blen])
        iw = min(iw, W - 6)
        bw, bh = iw + 4, len(rows) + 2 + (2 if buttons else 0)
        top, left = max(0, (H - bh) // 2), (W - bw) // 2
        ba = self.col("item") if battr is None else battr
        for r in range(bh):
            self.put(top + r, left, " " * bw)
        self.box(top, left, bh, bw, title, ba)
        for k, (t, a) in enumerate(rows):
            txt = t[:iw]
            off = (iw - len(txt)) // 2 if align == "center" else 0
            self.put(top + 1 + k, left + 2 + off, txt, a)
        if buttons:
            y = top + bh - 2
            x = left + 2 + (iw - blen) // 2
            for lbl, tok in buttons:
                s = f"[ {lbl} ]"
                self.put(y, x, s, self.col("item") | curses.A_BOLD)
                self.hit(y, x, len(s), tok)
                x += len(s) + 2
        return top + 1, left + 2, iw

    # ── input
    def _mouse(self):
        try:
            _, mx, my, _, bs = curses.getmouse()
        except curses.error:
            return None
        if bs & getattr(curses, "BUTTON4_PRESSED", 0):
            return "UP"
        b5 = getattr(curses, "BUTTON5_PRESSED", 0)
        if b5 and bs & b5:
            return "DOWN"
        if bs & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
            ly, lx = my - self.oy, mx - self.ox
            for y, x0, x1, tok in reversed(self.hits):
                if y == ly and x0 <= lx < x1:
                    return tok
            return "CLICK"
        return None

    def getkey(self, timeout=None):
        if timeout is not None:
            self.scr.timeout(timeout)
        try:
            while True:
                c = self.scr.getch()
                if c == -1:
                    if timeout is not None:
                        return "TICK"
                    continue
                if c == curses.KEY_MOUSE:
                    tok = self._mouse()
                    if tok:
                        return tok
                    continue
                if c in (10, 13):
                    return "ENTER"
                if c == 27:
                    return "ESC"
                if c in (8, 127):
                    return "BACKSPACE"
                if c == 9:
                    return "TAB"
                if c == 21:
                    return "CTRL_U"
                if 32 <= c < 127:
                    return chr(c)
                return self.KEYMAP.get(c, "")
        finally:
            if timeout is not None:
                self.scr.timeout(-1)

    def wait_key(self):
        self.scr.refresh()
        curses.flushinp()
        while True:
            k = self.getkey()
            if k not in ("RESIZE", ""):
                return k

    def pause(self, secs):
        """Wait up to secs (scaled by animation speed). Returns True if a key or click skipped it."""
        self.scr.refresh()
        end = time.time() + secs * self.speed
        try:
            while True:
                rem = end - time.time()
                if rem <= 0:
                    return False
                self.scr.timeout(max(1, int(rem * 1000)))
                c = self.scr.getch()
                if c in (-1, curses.KEY_RESIZE):
                    continue
                if c == curses.KEY_MOUSE:
                    try:
                        bs = curses.getmouse()[4]
                    except curses.error:
                        continue
                    if bs & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                        return True
                    continue
                return True
        finally:
            self.scr.timeout(-1)

    def nap(self, secs):
        time.sleep(secs * self.speed)

    def set_face(self, name, secs):
        self.face, self.face_until = name, time.time() + secs

    def current_face(self, g):
        if g.players[1].hp <= 0:
            return "dead"
        if time.time() < self.face_until:
            return self.face
        if self.thinking:
            return "think"
        if g.tell and g.vs_ai and g.turn == 0:
            return g.tell
        if g.tilted:
            return "angry"
        return "idle"

    def kind_attr(self, kind):
        return {"live": self.col("live"), "blank": self.col("blank"), "item": self.col("item"),
                "dealer": self.col("dealer"), "hp": self.col("hp"), "title": curses.A_BOLD}.get(kind, 0)

    def border(self, active):
        return (self.col("item") | curses.A_BOLD) if active else curses.A_DIM

    # ═════════ effects ═════════
    def wipe(self):
        if self.speed < 0.3:
            return
        h, w = self.scr.getmaxyx()
        a = self.col("title", curses.A_REVERSE)
        for x in range(0, w, 4):
            for y in range(h):
                seg = "▓▒░ "[:max(0, min(4, w - x - (1 if y == h - 1 else 0)))]
                try:
                    self.scr.addstr(y, x, seg, a)
                except curses.error:
                    pass
            self.scr.refresh()
            time.sleep(0.004)

    def shake(self, g):
        for dx in (2, -2, 1, -1, 0):
            self.shake_x = dx
            self.draw_board(g)
            self.nap(0.035)
        self.shake_x = 0

    def flash(self, g):
        h, w = self.scr.getmaxyx()
        a = self.col("flash", curses.A_REVERSE)
        for _ in range(2):
            for y in range(h):
                try:
                    self.scr.addstr(y, 0, " " * (w - 1 if y == h - 1 else w), a)
                except curses.error:
                    pass
            self.scr.refresh()
            self.nap(0.07)
            self.draw_board(g)
            self.nap(0.07)

    # ═════════ game board ═════════
    def controls(self, g):
        p = g.cur()
        out = [("item", k) for k in range(len(p.items))] + [("btn", "opp"), ("btn", "self")]
        if g.can_call():
            out.append(("btn", "call"))
        return out

    def charges(self, g, idx, y, x, ov):
        p = g.players[idx]
        hp = ov.get("hp", {}).get(idx, p.hp)
        bar = self.col("live") if hp <= 1 else self.col("hp")
        if g.sudden and int(time.time() * 2) % 2:
            bar |= curses.A_REVERSE
        self.put(y, x, "CHARGES", curses.A_BOLD)
        self.put(y, x + 8, "█" * hp, bar | curses.A_BOLD)
        self.put(y, x + 8 + hp, "░" * max(0, p.max_hp - hp), curses.A_DIM)
        self.put(y, x + 9 + p.max_hp, f"{hp}/{p.max_hp}")

    def badges(self, g, idx, y, x):
        p = g.players[idx]
        out = []
        if idx == 1 and g.tilted:
            out.append(("TILTED", "live"))
        if p.shackled:
            out.append(("CHAINED", "item"))
        if p.muzzled:
            out.append(("MUZZLED", "item"))
        if p.vest:
            out.append(("VEST", "hp"))
        if p.ricochet:
            out.append(("RICOCHET", "blank"))
        if p.leech:
            out.append(("LEECH", "live"))
        if "charm" in p.items:
            out.append(("CHARM", "hp"))
        for label, ck in out:
            s = f"[{label}]"
            if x + len(s) > LEFT_W - 2:
                break
            self.put(y, x, s, self.col(ck) | curses.A_BOLD)
            x += len(s) + 1

    def item_grid(self, g, idx, y, x, cols, cell, interactive):
        p = g.players[idx]
        if not p.items:
            self.put(y, x, "(no items)", curses.A_DIM)
        for k, it in enumerate(p.items):
            r, c = divmod(k, cols)
            cy, cx = y + r, x + c * cell
            info = ITEMS[base(it)]
            if interactive:
                text = f" {k + 1} {info['icon']} {info['label']}".ljust(cell - 1)
                usable = g.can_use(idx, it)[0]
                if self.focus == k:
                    a = self.sel_attr()
                elif usable:
                    a = self.col("item") | curses.A_BOLD
                else:
                    a = curses.A_DIM
                self.put(cy, cx, text, a)
                self.hit(cy, cx, cell - 1, f"@item:{k}")
            else:
                dim = g.event == "dry" or g.blind
                self.put(cy, cx, f" {info['icon']} {info['label']}",
                         curses.A_DIM if dim else (self.col("item") if p.is_ai else 0))

    def draw_info(self, g, interactive):
        x, y, iw = RIGHT_X, 1, RIGHT_W - 4
        title, lines = "INFO", []
        if interactive:
            p, i = g.cur(), g.turn
            ctrls = self.controls(g)
            kind, val = ctrls[max(0, min(self.focus, len(ctrls) - 1))]
            if kind == "item":
                it = p.items[val]
                info = ITEMS[base(it)]
                title = f"{info['icon']} {info['label'].upper()} · {info['cat'].upper()}"
                lines = [(l, 0) for l in wrap(info["desc"], iw)][:6] + [("", 0)]
                ok, why = g.can_use(i, it)
                if ok:
                    lines.append(("Enter to use it.", self.col("item") | curses.A_BOLD))
                else:
                    lines += [(l, self.col("live")) for l in wrap("Can't: " + why, iw)]
            elif val == "call":
                t = g.tip
                title = "CALL THE BLUFF"
                txt = [f"He claimed the chambered shell is {'LIVE' if t['claim'] else 'BLANK'}.",
                       f"If he lied, he loses 1 charge and you score +{BLUFF_BONUS}.",
                       "If it's true, you lose 1.", "The shell is revealed either way."]
                for tt in txt:
                    lines += [(l, 0) for l in wrap(tt, iw)]
            else:
                o = g.players[1 - i]
                title = "ACTION"
                n = 2 if g.double else 1
                dmg = g.live_damage()
                shells = "two shells" if n == 2 else "the chambered shell"
                if val == "opp":
                    txt = [f"Shoot {g.obj(o)} with {shells}.", f"Live: they lose {dmg}.", "Blank: your turn ends."]
                    if o.ricochet:
                        txt.append("Their RICOCHET plate will bounce it back at you!")
                else:
                    txt = [f"Shoot yourself with {shells}.", "Blank: you keep your turn.", f"Live: you lose {dmg}."]
                    if g.jammed:
                        txt.append("The Jammer will stop a live shell.")
                for t in txt:
                    lines += [(l, 0) for l in wrap(t, iw)]
                if g.counter_on():
                    lines += [(f"Odds it's live: {round(100 * g.chance_live(i))}%", self.col("item") | curses.A_BOLD)]
        else:
            if g.dealer:
                d = g.dealer
                title = d["name"].upper() + (" · TILTED" if g.tilted else "")
                lines = [(l, curses.A_DIM) for l in wrap(d["tagline"], iw)]
                lines += [(l, self.col(d["color"])) for l in wrap(d["house_rule"], iw)]
            else:
                title = "HOT-SEAT"
                lines = [(l, 0) for l in wrap("Two players, one keyboard, best of three stages. "
                                              "Look away when the other player peeks.", iw)]
            if g.event:
                e = EVENTS[g.event]
                lines = lines[:5] + [(f"{e['icon']} {e['label'].upper()}", self.col("item") | curses.A_BOLD)]
                lines += [(l, self.col("item")) for l in wrap(e["desc"], iw)]
        self.box(y, x, 10, RIGHT_W, title[:RIGHT_W - 6], self.border(interactive), curses.A_BOLD)
        for k, (t, a) in enumerate(lines[:8]):
            self.put(y + 1 + k, x + 2, t, a)

    def action_bar(self, g, interactive):
        p, o = g.cur(), g.players[1 - g.turn]
        n = len(p.items)
        btns = [("opp", f" SHOOT {o.name.upper()[:16]} ", "live"), ("self", " SHOOT YOURSELF ", "blank")]
        if interactive and g.can_call():
            btns.append(("call", " C CALL BLUFF ", "dealer"))
        x = 2
        for k, (tok, lbl, ck) in enumerate(btns):
            s = f"[{lbl}]"
            if interactive and self.focus == n + k:
                a = self.col(ck) | curses.A_REVERSE | curses.A_BOLD
            elif interactive:
                a = self.col(ck) | curses.A_BOLD
            else:
                a = curses.A_DIM
            self.put(26, x, s, a)
            if interactive:
                self.hit(26, x, len(s), f"@btn:{tok}")
            x += len(s) + 2
        if interactive:
            for lbl, tok, bx in ((" ? HELP ", "@help", 74), (" Q MENU ", "@quit", 86)):
                s = f"[{lbl}]"
                self.put(26, bx, s, curses.A_BOLD)
                self.hit(26, bx, len(s), tok)

    def draw_clock(self, clock):
        rem, lim = clock
        rem = max(0.0, rem)
        width = 30
        filled = math.ceil(width * rem / lim) if lim else 0
        ck = "live" if rem < 3 else "item"
        self.segs(27, 2, [("◷ SHOT CLOCK ", curses.A_BOLD),
                          ("█" * filled + "░" * (width - filled), self.col(ck) | curses.A_BOLD),
                          (f" {rem:4.1f}s", self.col(ck) | curses.A_BOLD)])

    def draw_board(self, g, status=None, interactive=False, clock=None):
        if not self.frame():
            return
        ov = self.override or {}
        top, bot = g.players[1], g.players[0]
        viewer = 0 if g.vs_ai else g.turn
        dealer = g.dealer

        # title bar
        if g.vs_ai:
            stage = f"Stage {g.stage}" + ("" if g.mode == "gauntlet" else "/3")
            sc = f"Score {g.score}" + (" (x2 on clear)" if g.double_pending else "")
            t = f" SHELL GAME │ vs {top.name} · {dealer['tier']} │ {stage} │ {sc} │ AI: {self.brain.short_label()}"
        else:
            t = f" SHELL GAME │ Hot-seat │ Stage {g.stage}/3 │ {bot.name} {bot.wins} – {top.wins} {top.name}"
        if g.sudden:
            t += " │ SUDDEN DEATH"
        tattr = (self.col("flash", curses.A_REVERSE) if g.sudden else self.col("title", curses.A_REVERSE))
        self.put(0, 0, t[:W].ljust(W), tattr | curses.A_BOLD)

        # opponent / player 2
        act1 = g.turn == 1 and g.stage_winner is None
        dcol = self.col(dealer["color"]) if dealer else 0
        name1 = top.name.upper() + (f" · {dealer['tier']}" if dealer else "")
        self.box(1, 0, 10, LEFT_W, ("▶ " if act1 else "") + name1, self.border(act1), curses.A_BOLD | dcol)
        for k, line in enumerate(portrait(dealer, self.current_face(g))):
            self.put(2 + k, 2, line, dcol)
        self.charges(g, 1, 2, 20, ov)
        self.badges(g, 1, 3, 20)
        self.item_grid(g, 1, 4, 20, 3, 14, interactive and g.turn == 1)
        if g.tell and g.vs_ai and g.turn == 0 and dealer and dealer.get("tells"):
            self.put(7, 20, dealer["tells"][g.tell][:42], dcol)
        if self.speech and g.vs_ai:
            for k, line in enumerate(wrap(f"“{self.speech}”", 58)[:2]):
                self.put(8 + k, 3, line, dcol | curses.A_BOLD)

        # table
        if g.event:
            e = EVENTS[g.event]
            ttitle, tt_attr = f"TABLE · {e['icon']} {e['label'].upper()}", self.col("item") | curses.A_BOLD
        else:
            ttitle, tt_attr = "TABLE", curses.A_BOLD
        tborder = (self.col("live") | curses.A_BOLD) if g.sudden else curses.A_DIM
        self.box(11, 0, 9, LEFT_W, ttitle, tborder, tt_attr)
        if self.aim:
            self.put(12, 2, self.aim[:58], self.col("live") | curses.A_BOLD)
        elif g.stage_winner is None:
            cur = g.cur()
            whose = "YOUR TURN" if cur.name == "You" else f"{cur.name.upper()}'S TURN"
            self.put(12, 2, f"{'▲' if g.turn == 1 else '▼'} {whose}", curses.A_BOLD)
            if g.vs_ai and g.dealer_key == "accountant" and g.turn == 0:
                ck = "live" if g.uses >= 2 else "hp"
                self.put(12, 48, f"AUDIT {min(g.uses, 3)}/3", self.col(ck) | curses.A_BOLD)
        sawed = ov.get("sawed", g.sawed)
        for k, line in enumerate(gun_art(sawed)):
            self.put(13 + k, 2, line)
        flags = []
        if sawed:
            flags.append(("‡ SAWED OFF", "live"))
        if ov.get("double", g.double):
            flags.append(("‖ DOUBLE LOADED", "item"))
        if ov.get("jammed", g.jammed):
            flags.append(("⊘ JAMMER SET", "blank"))
        if g.blind:
            flags.append((f"$ BLIND SHOTS {g.blind}", "dealer"))
        for r, (label, ck) in enumerate(flags):
            self.put(13 + r, 46, label, self.col(ck) | curses.A_BOLD)
        if len(flags) < 4:
            for h in [h for h in g.players[viewer].hints if h[0] >= g.pos][:1]:
                rng = f"next {h[1] - h[0]}" if h[0] == g.pos else f"#{h[0] - g.pos + 1}-{h[1] - g.pos}"
                self.put(16, 40, f"♠ TAROT {h[2]} live in {rng}"[:22], self.col("item"))
        pos = ov.get("pos", g.pos)
        known = {} if g.blind else g.players[viewer].known
        self.put(17, 2, "CHAMBER", curses.A_BOLD)
        x = 11
        for k in range(pos, len(g.shells)):
            kv = known.get(k)
            if kv is None:
                ch, a = "▯", curses.A_DIM
            else:
                ch, a = "▮", self.col("live" if kv else "blank") | curses.A_BOLD
            if k == pos:
                self.put(17, x, "[", curses.A_BOLD)
                self.put(17, x + 1, ch, a)
                self.put(17, x + 2, "]", curses.A_BOLD)
                x += 4
            else:
                self.put(17, x, ch, a)
                x += 2
        self.put(17, 36, "SPENT", curses.A_BOLD)
        for k, s in enumerate(g.spent[:ov.get("spent", len(g.spent))][-9:]):
            self.put(17, 42 + 2 * k, "▮", self.col("live" if s else "blank"))
        lv, bl = g.loaded
        rem = g.shells[pos:]
        rl = sum(rem)
        self.segs(18, 2, [("LOADED ", curses.A_BOLD), (f"{lv} live ", self.col("live")),
                          (f"{bl} blank", self.col("blank"))])
        if g.counter_on():
            self.segs(18, 28, [("LEFT ", curses.A_BOLD), (f"{rl} live ", self.col("live")),
                               (f"{len(rem) - rl} blank", self.col("blank"))])
            if not ov and g.stage_winner is None and not g.players[viewer].is_ai:
                self.put(18, 50, f"ODDS {round(100 * g.chance_live(viewer))}% live", self.col("item"))
        else:
            why = "blind round" if g.blind else ("blackout" if g.event == "blackout" else "count SPENT")
            self.segs(18, 28, [("LEFT ", curses.A_BOLD), (f"?  {why}", curses.A_DIM)])

        # you / player 1
        act0 = g.turn == 0 and g.stage_winner is None
        self.box(20, 0, 6, LEFT_W, ("▶ " if act0 else "") + bot.name.upper(), self.border(act0))
        self.charges(g, 0, 21, 2, ov)
        self.item_grid(g, 0, 22, 2, 4, 15, interactive and g.turn == 0)
        self.badges(g, 0, 24, 2)

        # right column
        self.draw_info(g, interactive)
        self.box(11, RIGHT_X, 15, RIGHT_W, "LOG", curses.A_DIM)
        lines = []
        for text, kind in g.log[-40:]:
            for wl in wrap(text, RIGHT_W - 4):
                lines.append((wl, kind))
        for k, (tx, kind) in enumerate(lines[-13:]):
            self.put(12 + k, RIGHT_X + 2, tx, self.kind_attr(kind))

        # action bar + footer
        if status:
            self.put(26, 2, status[:W - 4], self.col("item") | curses.A_BOLD)
        else:
            self.action_bar(g, interactive)
        if clock:
            self.draw_clock(clock)
        if self.msg:
            self.put(28, 2, "⚠ " + self.msg[:W - 6], self.col("item"))
        if interactive:
            hint = "←→ select  ↑↓ items/actions  Enter use  1-8 item  S self  O opponent  ? help  Q menu"
            if g.can_call():
                hint = "←→ select  Enter use  1-8 item  S self  O opponent  C CALL BLUFF  ? help  Q menu"
            self.put(29, 2, hint, curses.A_DIM)
        self.scr.refresh()

    # ═════════ animations ═════════
    def anim_load(self, g, live, blank):
        self.sound("load")
        seq = [True] * live + [False] * blank
        n = len(seq)
        self.draw_board(g)
        top, left, iw = self.popup([("LOADING THE GUN", curses.A_BOLD), "", "", "", "",
                                    ("(any key to skip)", curses.A_DIM)], width=34)
        x0 = left + (iw - (2 * n - 1)) // 2
        skip = False
        for k, s in enumerate(seq):
            self.put(top + 2, x0 + 2 * k, "▮", self.col("live" if s else "blank") | curses.A_BOLD)
            if not skip:
                skip = self.pause(0.15)
        a, b = f"{live} LIVE", f"{blank} BLANK"
        xs = left + (iw - (len(a) + 5 + len(b))) // 2
        self.segs(top + 4, xs, [(a, self.col("live") | curses.A_BOLD), ("  ·  ", 0),
                                (b, self.col("blank") | curses.A_BOLD)])
        if not skip:
            skip = self.pause(1.3)
        for _ in range(5):
            order = seq[:]
            random.shuffle(order)
            for k, s in enumerate(order):
                self.put(top + 2, x0 + 2 * k, "▮", self.col("live" if s else "blank") | curses.A_BOLD)
            if not skip:
                skip = self.pause(0.1)
        for k in range(n):
            self.put(top + 2, x0 + 2 * k, "▯", curses.A_DIM)
        self.pause(0.3 if skip else 0.7)

    def anim_event(self, g, key):
        e = EVENTS[key]
        self.sound("event")
        self.draw_board(g)
        for fill in ("░", "▒", "▓", "█"):
            self.popup([("TABLE EVENT", curses.A_BOLD), "", (fill * 20, self.col("item")), ""], width=44)
            self.scr.refresh()
            self.nap(0.09)
        body = [("TABLE EVENT", curses.A_DIM), "",
                (f"{e['icon']}  {e['label'].upper()}  {e['icon']}", self.col("item") | curses.A_BOLD), ""]
        body += wrap(e["desc"], 44)
        self.popup(body, width=48, battr=self.col("item"), buttons=[("Deal me in", "@ok")])
        self.scr.refresh()
        self.pause(3.5)

    def anim_sudden(self, g):
        self.sound("sudden")
        for _ in range(2):
            self.flash(g)
        self.draw_board(g)
        self.popup([("SUDDEN DEATH", self.col("live") | curses.A_BOLD), "",
                    "Both players are on their last charge.", "Healing is off until the stage ends."],
                   battr=self.col("live"))
        self.pause(2.2)

    def anim_bluff(self, g, lied, claim, now):
        self.sound("reveal")
        self.draw_board(g)
        self.popup([("YOU CALL THE BLUFF", self.col("dealer") | curses.A_BOLD), "",
                    f"He said the shell is {'LIVE' if claim else 'BLANK'}.", "", ("...", curses.A_DIM)],
                   width=40, battr=self.col("dealer"))
        self.pause(1.3)
        if lied:
            self.sound("win")
            self.set_face("hurt", 2.0)
            verdict, ck, cost = "HE LIED!", "hp", f"He loses 1 charge. +{BLUFF_BONUS} points."
        else:
            self.sound("lose")
            self.set_face("grin", 2.0)
            verdict, ck, cost = "HE TOLD THE TRUTH", "live", "You lose 1 charge."
        self.shake(g)
        self.draw_board(g)
        self.popup([(verdict, self.col(ck) | curses.A_BOLD), "",
                    (f"The chambered shell is {'LIVE' if now else 'BLANK'}.",
                     self.col("live" if now else "blank") | curses.A_BOLD), "", cost],
                   width=40, battr=self.col(ck))
        self.pause(2.0)

    def anim_tilt(self, g):
        self.sound("trap")
        d = g.dealer
        self.set_face("angry", 2.5)
        self.shake(g)
        self.draw_board(g)
        self.popup([("TILTED!", self.col("live") | curses.A_BOLD), "", f"{g.players[1].name}:",
                    d["tilt"]["line"], "", ("Land a hit on you and he'll calm down.", curses.A_DIM)],
                   battr=self.col("live"))
        self.pause(2.2)

    def anim_calm(self, g):
        self.draw_board(g)
        self.popup([f"{g.players[1].name} regains his composure.", ("The tilt is over.", curses.A_DIM)])
        self.pause(1.2)

    def anim_audit(self, g, label):
        self.sound("trap")
        self.set_face("grin", 1.8)
        self.draw_board(g)
        self.popup([("AUDIT!", self.col("hp") | curses.A_BOLD), "",
                    f"The Accountant confiscates your {label}.",
                    ("Three items in one turn is two too many.", curses.A_DIM)], battr=self.col("hp"))
        self.pause(2.0)

    def anim_highroller(self, g):
        self.sound("dice")
        self.set_face("grin", 2.0)
        self.draw_board(g)
        for k in range(8):
            face = "( HEADS )" if k % 2 == 0 else "( TAILS )"
            self.popup([("HIGH ROLLER ROUND", self.col("item") | curses.A_BOLD), "", (face, self.col("item"))],
                       width=40)
            self.scr.refresh()
            self.nap(0.08 + k * 0.02)
        self.popup([("HIGH ROLLER ROUND", self.col("item") | curses.A_BOLD), "",
                    "The next 2 shots are blind:", "no items, no counter, no peeking.",
                    ("\"Let it ride, pal.\"", curses.A_DIM)], width=40, battr=self.col("item"))
        self.pause(2.2)

    def anim_shot(self, g, shooter, target, results, ov, rico):
        s, t = g.players[shooter], g.players[target]
        aimed = shooter if (target == shooter and not rico) else 1 - shooter
        arrow = "▲▲▲" if aimed == 1 else "▼▼▼"
        at = g.refl(s) if aimed == shooter else g.obj(g.players[aimed])
        extra = " · DOUBLE" if len(results) > 1 or ov.get("double") else ""
        self.override = ov
        self.aim = f"{arrow} {s.name} {g.v(s, 'aim')} at {at}{extra} {arrow}"
        self.draw_board(g)
        self.pause(1.1)
        if rico:
            self.sound("trap")
            self.popup([("↻ RICOCHET!", self.col("item") | curses.A_BOLD), "",
                        f"The shot bounces back at {g.obj(s)}!"], battr=self.col("item"))
            self.pause(1.1)
        self.aim = None
        for r in results:
            if r["jam"]:
                self.sound("click")
                self.draw_board(g)
                if r["jam"] == "jammer":
                    body = [("⊘ JAMMED", self.col("blank") | curses.A_BOLD), "",
                            "A live shell, stopped cold by the Jammer."]
                else:
                    body = [("MISFIRE!", self.col("blank") | curses.A_BOLD), "",
                            "A live shell... and it fizzles. Lucky."]
                self.popup(body, battr=self.col("blank"))
                self.pause(1.2)
            elif r["live"]:
                self.sound("bang")
                self.flash(g)
                self.shake(g)
                if g.vs_ai:
                    self.set_face("hurt" if target == 1 else "grin", 2.0)
                self.draw_board(g)
                c = self.col("live") | curses.A_BOLD
                body = [(l, c) for l in big("BANG!")] + [""]
                body.append(f"{t.name} {g.v(t, 'lose')} {r['dmg']} charge{'s' if r['dmg'] != 1 else ''}.")
                body += [n[0].upper() + n[1:] + "." for n in r["notes"]]
                self.popup(body, battr=self.col("live"))
                self.pause(1.4)
            else:
                self.sound("click")
                self.draw_board(g)
                self.popup([("*click*", self.col("blank") | curses.A_BOLD), "", "Blank."], battr=self.col("blank"))
                self.pause(0.9)
        self.override = None
        self.draw_board(g)

    def gate(self, g, p):
        """Hot-seat privacy screen before a secret reveal."""
        if g.vs_ai:
            return
        if self.frame():
            self.popup([(f"FOR {p.name.upper()}'S EYES ONLY", self.col("item") | curses.A_BOLD), "",
                        "Everyone else: look away."], buttons=[("Reveal", "@ok")])
        self.wait_key()

    def private(self, g, idx, text, live):
        p = g.players[idx]
        if p.is_ai:
            self.set_face("think", 1.5)
            self.draw_board(g)
            self.pause(0.9)
            return
        self.gate(g, p)
        self.sound("reveal")
        self.draw_board(g)
        c = self.col("live" if live else "blank")
        self.popup([("SECRET", curses.A_BOLD), "", (text, c | curses.A_BOLD)],
                   battr=c, buttons=[("Got it", "@ok")])
        self.wait_key()
        self.draw_board(g)

    def anim_snapshot(self, g, idx, vals):
        p = g.players[idx]
        if p.is_ai:
            self.set_face("think", 1.5)
            self.draw_board(g)
            self.pause(0.9)
            return
        self.gate(g, p)
        self.sound("reveal")
        self.draw_board(g)
        n = len(vals)
        top, left, iw = self.popup([("▣ SNAPSHOT", self.col("item") | curses.A_BOLD), "", "", "",
                                    ("memorise it: 1 = chambered", curses.A_DIM), ""], width=max(34, 4 * n + 4))
        x0 = left + (iw - (4 * n - 1)) // 2
        for k, s in enumerate(vals):
            self.put(top + 2, x0 + 4 * k, f"[{'L' if s else 'B'}]", self.col("live" if s else "blank") | curses.A_BOLD)
            self.put(top + 3, x0 + 4 * k + 1, str(k + 1), curses.A_DIM)
        steps = 20
        for k in range(steps):
            bar = "█" * (steps - k) + " " * k
            self.put(top + 5, left + (iw - steps) // 2, bar, self.col("item"))
            self.scr.refresh()
            time.sleep(0.1)  # a fixed two seconds regardless of animation speed
        self.draw_board(g)
        self.popup([("The picture fades.", curses.A_DIM)])
        self.pause(0.6)

    def anim_dice(self, g, idx, roll, text):
        self.sound("dice")
        p = g.players[idx]
        self.draw_board(g)
        for k in range(10):
            face = random.randint(1, 6) if k < 9 else roll
            self.popup([(f"{p.name.upper()} {g.v(p, 'roll').upper()} THE DICE", curses.A_BOLD), "",
                        (f"┌───┐ {face}", self.col("item") | curses.A_BOLD), "", ""], width=32)
            self.scr.refresh()
            self.nap(0.06 + k * 0.015)
        self.popup([(f"{p.name.upper()} {g.v(p, 'roll').upper()} THE DICE", curses.A_BOLD), "",
                    (f"⚄  {roll}  ⚄", self.col("item") | curses.A_BOLD), "", text], width=max(32, len(text)))
        self.pause(1.5)

    def anim_trap(self, g, idx, label):
        self.sound("trap")
        p = g.players[idx]
        if g.vs_ai and idx == 1:
            self.set_face("hurt", 1.5)
        self.shake(g)
        self.draw_board(g)
        self.popup([("¤ RIGGED!", self.col("live") | curses.A_BOLD), "",
                    f"{g.poss(p).capitalize()} {label} was a decoy. -1 charge."], battr=self.col("live"))
        self.pause(1.4)

    def play_events(self, g, events):
        for e in events:
            kind = e[0]
            if kind == "load":
                self.anim_load(g, e[1], e[2])
            elif kind == "event":
                self.anim_event(g, e[1])
            elif kind == "sudden":
                self.anim_sudden(g)
            elif kind == "shot":
                self.anim_shot(g, *e[1:])
            elif kind == "bluff":
                self.anim_bluff(g, e[1], e[2], e[3])
            elif kind == "tilt":
                self.anim_tilt(g)
            elif kind == "calm":
                self.anim_calm(g)
            elif kind == "audit":
                self.anim_audit(g, e[1])
            elif kind == "highroller":
                self.anim_highroller(g)
            elif kind == "private":
                self.private(g, *e[1:])
            elif kind == "snapshot":
                self.anim_snapshot(g, e[1], e[2])
            elif kind == "dice":
                self.anim_dice(g, e[1], e[2], e[3])
            elif kind == "trap":
                self.anim_trap(g, e[1], e[2])
            elif kind == "eject":
                c = self.col("live" if e[1] else "blank")
                self.sound("click")
                self.draw_board(g)
                self.popup(["The shell drops out:", "", ("LIVE" if e[1] else "BLANK", c | curses.A_BOLD)], battr=c)
                self.pause(1.1)
            elif kind == "hurt":
                if g.vs_ai and e[1] == 1:
                    self.set_face("hurt", 1.5)
                self.sound("trap")
                self.draw_board(g)
                self.pause(0.8)
            else:
                self.sound("item")
                self.draw_board(g)
                self.pause(0.5)
        self.draw_board(g)

    def think(self, g, worker, min_time, label):
        self.thinking = True
        start = time.time()
        k = 0
        who = g.cur().name
        suffix = f" (asking {label})" if worker else ""
        while True:
            done = worker is None or not worker.is_alive()
            if done and time.time() - start >= min_time * self.speed:
                break
            self.draw_board(g, status=f"{SPIN[k % len(SPIN)]} {who} is thinking...{suffix}")
            k += 1
            time.sleep(0.08)
        self.thinking = False

    # ═════════ dialogs ═════════
    def banner(self, g, title, lines, ck):
        if ck == "live":
            self.sound("lose")
        elif ck == "hp":
            self.sound("win")
        self.draw_board(g)
        c = self.col(ck)
        body = [(title, c | curses.A_BOLD), ""] + [l for l in lines if l]
        self.popup(body, battr=c, buttons=[("Continue", "@ok")])
        self.wait_key()

    def confirm(self, g, text):
        self.draw_board(g)
        self.popup([text], buttons=[("Yes", "@y"), ("No", "@n")])
        while True:
            k = self.wait_key()
            if k in ("y", "Y", "@y"):
                return True
            if k in ("n", "N", "@n", "ESC"):
                return False

    def choose(self, g, title, labels):
        """Pick one of labels (up to 9). Returns the index or None."""
        self.draw_board(g)
        rows = [(title, curses.A_BOLD), ""]
        rows += [f"[{k + 1}] {lbl}" for k, lbl in enumerate(labels)]
        rows += ["", ("number or click to pick · Esc cancel", curses.A_DIM)]
        top, left, iw = self.popup(rows, align="left")
        for k in range(len(labels)):
            self.hit(top + 2 + k, left, iw, f"@c:{k}")
        while True:
            k = self.wait_key()
            if k == "ESC":
                return None
            if k.startswith("@c:"):
                return int(k[3:])
            if len(k) == 1 and k.isdigit() and 1 <= int(k) <= len(labels):
                return int(k) - 1

    def handover(self, g):
        p = g.cur()
        if self.frame():
            self.popup([(f"{p.name.upper()}'S TURN", self.col("item") | curses.A_BOLD), "",
                        "Pass the keyboard. Everyone else looks away."], buttons=[("I'm ready", "@ok")])
        self.wait_key()

    def ask_double(self, g):
        nxt = DEALERS[DEALER_ORDER[g.stage % len(DEALER_ORDER)]]["name"]
        self.draw_board(g)
        self.popup([("DOUBLE OR NOTHING?", self.col("item") | curses.A_BOLD), "",
                    f"Bank {g.score} points now, or face {nxt} in stage {g.stage + 1}.",
                    "Clear it and your score doubles. Die and you lose it all."],
                   buttons=[("C  Cash out", "@c"), ("D  Double or nothing", "@d")])
        while True:
            k = self.wait_key()
            if k in ("c", "C", "@c"):
                return "cash"
            if k in ("d", "D", "@d"):
                return "double"

    def text_input(self, title, prefill="", mask=False, maxlen=60, width=40, hint=None):
        buf = prefill or ""
        curses.flushinp()
        while True:
            top, left, iw = self.popup([(title, curses.A_BOLD), "", "", "",
                                        (hint or "Enter save · Esc cancel · Ctrl-U clear", curses.A_DIM)],
                                       width=width)
            shown = ("•" * len(buf)) if mask else buf
            shown = shown[-(iw - 3):]
            self.put(top + 2, left, "> " + shown, self.col("item") | curses.A_BOLD)
            self.put(top + 2, left + 2 + len(shown), "_", curses.A_BLINK)
            self.scr.refresh()
            k = self.getkey()
            if k == "ENTER":
                return buf.strip()
            if k == "ESC":
                return None
            if k == "RESIZE":
                self.frame()
            elif k == "BACKSPACE":
                buf = buf[:-1]
            elif k == "CTRL_U":
                buf = ""
            elif len(k) == 1 and len(buf) < maxlen:
                buf += k

    def select_list(self, title, options, current=None):
        filt = ""
        idx = options.index(current) if current in options else 0
        top_i, page = 0, 18
        bx, by, bw, bh = 18, 3, 64, 24
        while True:
            view = [o for o in options if filt.lower() in o.lower()]
            idx = max(0, min(idx, len(view) - 1))
            top_i = min(top_i, idx)
            if idx >= top_i + page:
                top_i = idx - page + 1
            for r in range(bh):
                self.put(by + r, bx, " " * bw)
            self.box(by, bx, bh, bw, title, self.col("item"))
            self.put(by + 1, bx + 2, f"Filter: {filt}_", curses.A_BOLD)
            for r, opt in enumerate(view[top_i:top_i + page]):
                j = top_i + r
                y = by + 3 + r
                mark = "•" if opt == current else " "
                self.put(y, bx + 2, f"{mark} {opt}"[:bw - 4].ljust(bw - 4), self.sel_attr() if j == idx else 0)
                self.hit(y, bx + 1, bw - 2, f"@opt:{j}")
            self.put(by + bh - 2, bx + 2,
                     f"{len(view)} of {len(options)} · type to filter · Enter pick · Esc cancel"[:bw - 4],
                     curses.A_DIM)
            self.scr.refresh()
            k = self.getkey()
            if k == "UP":
                idx -= 1
            elif k == "DOWN":
                idx += 1
            elif k == "PGUP":
                idx -= page
            elif k == "PGDN":
                idx += page
            elif k == "HOME":
                idx = 0
            elif k == "END":
                idx = len(view) - 1
            elif k == "ENTER":
                return view[idx] if view else None
            elif k == "ESC":
                return None
            elif k == "BACKSPACE":
                filt, idx = filt[:-1], 0
            elif k.startswith("@opt:"):
                j = int(k[5:])
                if j < len(view):
                    return view[j]
            elif len(k) == 1:
                filt, idx = filt + k, 0

    def run_with_spinner(self, label, fn):
        w = Worker(fn)
        w.start()
        k = 0
        while w.is_alive():
            self.popup([f"{SPIN[k % len(SPIN)]}  {label}"], width=44)
            self.scr.refresh()
            time.sleep(0.08)
            k += 1
        return w.result, w.error

    # ═════════ menu screens ═════════
    def main_menu(self, config, sel):
        tick = 0
        faces = {dk: "idle" for dk in DEALER_ORDER}
        while True:
            tick += 1
            if tick % 20 == 0:
                dk = random.choice(DEALER_ORDER)
                faces = {d: "idle" for d in DEALER_ORDER}
                faces[dk] = random.choice(["grin", "think", "sweat", "smug"])
            if self.frame():
                flicker = random.random() < 0.05
                tattr = (curses.A_DIM if flicker else curses.A_BOLD) | self.col("item")
                for k, line in enumerate(TITLE_ART):
                    self.centered(1 + k, line, tattr)
                self.centered(6, "a terminal duel of nerve, odds and one very loud gun", curses.A_DIM)
                pattern = [True, False, True, True, False, False, True, False, True, False, False, True]
                ticker_x = (W - 2 * 24) // 2
                for k in range(24):
                    live = pattern[(k + tick // 3) % len(pattern)]
                    self.put(7, ticker_x + 2 * k, "▮", (self.col("live") if live else self.col("blank")) | curses.A_DIM)
                self.box(8, 34, 10, 32, "MENU", curses.A_DIM)
                for k, (_, label, _) in enumerate(MENU):
                    y = 9 + k
                    marker = "▶" if k == sel else " "
                    self.put(y, 36, f"{marker} {k + 1}  {label}".ljust(28), self.sel_attr() if k == sel else 0)
                    self.hit(y, 35, 30, f"@menu:{k}")
                self.centered(19, MENU[sel][2], curses.A_DIM)
                for k, dk in enumerate(DEALER_ORDER):
                    d = DEALERS[dk]
                    x = 8 + k * 23
                    locked = not config.unlocked(dk)
                    a = curses.A_DIM if locked else self.col(d["color"])
                    for r, line in enumerate(portrait(d, faces[dk], locked)):
                        self.put(21 + r, x, line, a)
                        if not locked:
                            self.hit(21 + r, x, 15, f"@fight:{dk}")
                    name = "???" if locked else d["name"]
                    self.put(27, x + (15 - len(name)) // 2, name, a | curses.A_BOLD)
                    if not locked:
                        self.hit(27, x, 15, f"@fight:{dk}")
                st, ck = self.brain.status_line()
                self.centered(28, st, curses.A_DIM if ck == "dim" else self.col(ck))
                self.centered(29, "↑↓ move · Enter select · click a dealer to fight him · Q quit", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey(timeout=150)
            if k == "TICK":
                continue
            if k == "UP":
                sel = (sel - 1) % len(MENU)
            elif k in ("DOWN", "TAB"):
                sel = (sel + 1) % len(MENU)
            elif k in ("ENTER", " "):
                return MENU[sel][0], sel, None
            elif k.startswith("@menu:"):
                sel = int(k[6:])
                return MENU[sel][0], sel, None
            elif k.startswith("@fight:"):
                return "fight", sel, k[7:]
            elif k in ("q", "Q", "ESC"):
                return "quit", sel, None
            elif len(k) == 1 and k.isdigit() and 1 <= int(k) <= len(MENU):
                sel = int(k) - 1
                return MENU[sel][0], sel, None

    def pick_dealer(self, config):
        sel, msg = 0, ""
        while True:
            dk = DEALER_ORDER[sel]
            d = DEALERS[dk]
            locked = not config.unlocked(dk)
            if self.frame():
                self.centered(1, "CHOOSE YOUR OPPONENT", self.col("item") | curses.A_BOLD)
                self.box(3, 2, 14, 30, "DEALERS", curses.A_DIM)
                for k, key in enumerate(DEALER_ORDER):
                    dd = DEALERS[key]
                    lk = not config.unlocked(key)
                    y = 4 + k * 3
                    self.put(y, 4, f" {'???' if lk else dd['name']}".ljust(26),
                             self.sel_attr() if k == sel else curses.A_BOLD)
                    self.put(y + 1, 5, "LOCKED" if lk else dd["tier"], curses.A_DIM if lk else self.col(dd["color"]))
                    self.hit(y, 3, 28, f"@d:{k}")
                    self.hit(y + 1, 3, 28, f"@d:{k}")
                dcol = curses.A_DIM if locked else self.col(d["color"])
                self.box(3, 34, 24, 64, "LOCKED" if locked else d["name"].upper(), dcol, curses.A_BOLD | dcol)
                for r, line in enumerate(portrait(d, "idle", locked)):
                    self.put(5 + r, 37, line, dcol)
                if locked:
                    text = ("The house dealer only sits down for players who have proven themselves. "
                            "Beat any dealer in a 3-stage duel, or clear stage 3 of the Gauntlet, to unlock him.")
                    for r, l in enumerate(wrap(text, 40)):
                        self.put(5 + r, 55, l)
                else:
                    self.put(5, 55, d["name"], curses.A_BOLD)
                    self.put(6, 55, d["tier"], dcol)
                    for r, l in enumerate(wrap(d["bio"], 40)[:4]):
                        self.put(7 + r, 55, l)
                    self.put(12, 37, "PLAYSTYLE", curses.A_BOLD)
                    for r, s in enumerate(d["style"]):
                        self.put(13 + r, 37, "• " + s)
                    self.put(16, 37, "HOUSE RULE", curses.A_BOLD)
                    for r, l in enumerate(wrap(d["house_rule"], 58)[:2]):
                        self.put(17 + r, 37, l, dcol)
                    self.segs(19, 37, [("TELLS ", curses.A_BOLD), (d["tell_desc"], 0)])
                    self.put(20, 37, "CARRIES", curses.A_BOLD)
                    pool = sorted(d["pool"].items(), key=lambda kv: -kv[1])
                    if dk == "croupier":
                        carries = "Everything. All 25 items."
                    else:
                        carries = ", ".join(f"{ITEMS[k]['icon']} {ITEMS[k]['label']}" for k, _ in pool) + "."
                    for r, l in enumerate(wrap(carries, 58)[:2]):
                        self.put(21 + r, 37, l)
                    rl = d["rules"]
                    self.put(23, 37, "STAKES", curses.A_BOLD)
                    self.put(24, 37, f"Charges {'/'.join(map(str, rl['hp']))} · your items "
                                     f"{'/'.join(map(str, rl['you_items']))} · score x{rl['mult']:g} · "
                                     f"counter {'shown' if rl['counter'] else 'HIDDEN'}"[:58])
                    best = best_score(f"duel:{dk}")
                    self.put(25, 37, f"Your best: {best}" if best else "Your best: no wins yet", curses.A_DIM)
                if msg:
                    self.centered(28, msg, self.col("item"))
                self.centered(29, "↑↓ choose · Enter fight · click twice to fight · Esc back", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey()
            msg = ""
            fight = False
            if k == "UP":
                sel = (sel - 1) % len(DEALER_ORDER)
            elif k in ("DOWN", "TAB"):
                sel = (sel + 1) % len(DEALER_ORDER)
            elif k.startswith("@d:"):
                n = int(k[3:])
                fight = n == sel
                sel = n
            elif k in ("ENTER", " "):
                fight = True
            elif k in ("ESC", "q", "Q"):
                return None
            if fight:
                if config.unlocked(DEALER_ORDER[sel]):
                    return DEALER_ORDER[sel]
                msg = "Locked. Beat any other dealer first."

    def item_guide(self):
        sel, top_i, page = 0, 0, 22
        while True:
            it = ITEM_KEYS[sel]
            info = ITEMS[it]
            if sel < top_i:
                top_i = sel
            if sel >= top_i + page:
                top_i = sel - page + 1
            if self.frame():
                self.centered(1, f"ITEM GUIDE · {len(ITEM_KEYS)} ITEMS", self.col("item") | curses.A_BOLD)
                self.box(3, 2, 24, 26, "ITEMS", curses.A_DIM)
                for r, key in enumerate(ITEM_KEYS[top_i:top_i + page]):
                    k = top_i + r
                    ii = ITEMS[key]
                    self.put(4 + r, 4, f" {ii['icon']} {ii['label']}".ljust(22), self.sel_attr() if k == sel else 0)
                    self.hit(4 + r, 3, 24, f"@i:{k}")
                if top_i > 0:
                    self.put(3, 22, " ▲ ", curses.A_DIM)
                if top_i + page < len(ITEM_KEYS):
                    self.put(26, 22, " ▼ ", curses.A_DIM)
                self.box(3, 30, 24, 68, f"{info['icon']} {info['label'].upper()}", self.col("item"),
                         curses.A_BOLD | self.col("item"))
                y = 5
                self.put(y, 33, info["short"][0].upper() + info["short"][1:], self.col("item") | curses.A_BOLD)
                self.put(y, 96 - len(info["cat"]), info["cat"].upper(), curses.A_DIM)
                y += 2
                for head, body in (("WHAT IT DOES", info["desc"]), ("WHEN TO USE IT", info["tip"])):
                    self.put(y, 33, head, curses.A_BOLD)
                    y += 1
                    for l in wrap(body, 62):
                        self.put(y, 33, l)
                        y += 1
                    y += 1
                common = [DEALERS[d]["name"] for d in DEALER_ORDER[:3] if DEALERS[d]["pool"].get(it, 0) >= 3]
                rare = [DEALERS[d]["name"] for d in DEALER_ORDER[:3] if 0 < DEALERS[d]["pool"].get(it, 0) < 3]
                parts = []
                if common:
                    parts.append("Common at: " + ", ".join(common) + ".")
                if rare:
                    parts.append("Rare at: " + ", ".join(rare) + ".")
                parts.append("The Croupier carries everything, and you can always draw it yourself.")
                self.put(y, 33, "WHERE YOU'LL SEE IT", curses.A_BOLD)
                y += 1
                for l in wrap(" ".join(parts), 62):
                    self.put(y, 33, l)
                    y += 1
                self.centered(29, "↑↓ browse · PgUp/PgDn jump · Esc back", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey()
            if k == "UP":
                sel = (sel - 1) % len(ITEM_KEYS)
            elif k in ("DOWN", "TAB"):
                sel = (sel + 1) % len(ITEM_KEYS)
            elif k == "PGUP":
                sel = max(0, sel - 8)
            elif k == "PGDN":
                sel = min(len(ITEM_KEYS) - 1, sel + 8)
            elif k.startswith("@i:"):
                sel = int(k[3:])
            elif k in ("ESC", "q", "Q", "ENTER"):
                return

    def scores_screen(self):
        data = load_scores()
        if self.frame():
            self.centered(1, "HIGH SCORES", self.col("item") | curses.A_BOLD)
            slots = [(f"duel:{dk}", DEALERS[dk]["name"].upper(), DEALERS[dk]["color"]) for dk in DEALER_ORDER]
            slots.append(("gauntlet", "GAUNTLET", "item"))
            spots = [(3, 1), (3, 34), (3, 67), (14, 17), (14, 50)]
            for (key, title, ck), (y, x) in zip(slots, spots):
                self.box(y, x, 10, 32, title, curses.A_DIM, curses.A_BOLD | self.col(ck))
                entries = [e for e in data.get(key, []) if isinstance(e, dict)][:7]
                if not entries:
                    self.put(y + 2, x + 2, "no scores yet", curses.A_DIM)
                for r, e in enumerate(entries):
                    row = f"{e.get('score', 0):>7}  {str(e.get('name', ''))[:10]:<10} {str(e.get('date', ''))[5:]}"
                    self.put(y + 1 + r, x + 2, row[:28], self.col("item") | curses.A_BOLD if r == 0 else 0)
            self.centered(29, "press any key", curses.A_DIM)
            self.scr.refresh()
        self.wait_key()

    def help_screen(self):
        if self.frame():
            self.box(1, 4, 27, 92, "HOW TO PLAY", self.col("item"), curses.A_BOLD | self.col("item"))
            for k, (text, head) in enumerate(HELP_TEXT):
                self.put(2 + k, 7, text, (self.col("item") | curses.A_BOLD) if head else 0)
            self.centered(29, "press any key", curses.A_DIM)
            self.scr.refresh()
        self.wait_key()

    def _pick_model(self, brain, config):
        res, err = self.run_with_spinner("Fetching models...", brain.list_models)
        if err:
            return f"Couldn't list models: {short_err(err)}", "live"
        if not res:
            return "The server returned no models.", "item"
        m = self.select_list("CHOOSE A MODEL", res, brain.model())
        if not m:
            return "", "item"
        config.data["models"][brain.provider] = m
        config.save()
        brain.reset()
        return f"Model set to {m}.", "hp"

    @staticmethod
    def _cycle(options, cur, step):
        i = options.index(cur) if cur in options else 0
        return options[(i + step) % len(options)]

    def settings(self, brain, config):
        sel, note, note_ck = 1, "", "item"
        prefs = config.prefs
        cyclers = ("provider", "theme", "sound", "speed", "mouse", "events", "misfires", "clock")
        while True:
            p = brain.provider
            info = PROVIDERS[p]
            rows = [{"kind": "header", "label": "AI BRAIN"},
                    {"kind": "field", "label": "Provider", "value": f"◀ {info['label']} ▶", "tok": "provider",
                     "help": "Who plays the dealers. ←/→ or Enter to switch. 'Off' uses the built-in strategies."}]
            if p != "off":
                key, src = brain.key()
                kv = f"{mask_key(key)}   ({src})" if key else "not set: press Enter to paste one"
                key_help = ("Paste your SleepyAI key (sk-...) from the SleepyAI dashboard."
                            if p == "sleepyai" else "Paste your Gemini API key.")
                rows += [
                    {"kind": "field", "label": "API key", "value": kv, "tok": "key",
                     "help": key_help + " Stored in the macOS Keychain, never in a file."},
                    {"kind": "field", "label": "Base URL", "value": brain.base_url() or "(not set)", "tok": "base",
                     "help": f"Default {info.get('base')}. Enter to edit; clear it to reset."
                     if info.get("edit_base") else "Fixed for Gemini."},
                    {"kind": "field", "label": "Model", "value": brain.model() or "(not set: choose one below)",
                     "tok": "model", "help": "Enter to type a model ID, or pick one from the list below."},
                    {"kind": "button", "value": "Choose model from list", "tok": "pick",
                     "help": "Fetches the models your key can use and lets you pick one."},
                    {"kind": "button", "value": "Test connection", "tok": "test",
                     "help": "Sends one tiny request to check the key, URL and model."},
                ]
                if key and src in ("macOS Keychain", "this session only"):
                    rows.append({"kind": "button", "value": "Remove saved key", "tok": "delkey",
                                 "help": "Deletes this provider's key from the Keychain."})
            clock_label = "Off" if prefs["clock"] == "off" else f"{prefs['clock']} seconds"
            rows += [
                {"kind": "header", "label": "GAME RULES"},
                {"kind": "field", "label": "Table events", "value": f"◀ {'On' if prefs['events'] else 'Off'} ▶",
                 "tok": "events", "help": "Each reload may flip a random event card that bends the rules until "
                                          "the next reload."},
                {"kind": "field", "label": "Misfires", "value": f"◀ {'On' if prefs['misfires'] else 'Off'} ▶",
                 "tok": "misfires", "help": "Live shells have a 5% chance to fizzle, so no shot is ever certain."},
                {"kind": "field", "label": "Shot clock", "value": f"◀ {clock_label} ▶", "tok": "clock",
                 "help": "Time limit per decision. Run out and you fire at a random target. Rush Hour forces 10s."},
                {"kind": "header", "label": "DISPLAY & SOUND"},
                {"kind": "field", "label": "Theme", "value": f"◀ {THEMES[prefs['theme']]['label']} ▶", "tok": "theme",
                 "help": "Casino (classic reds), Neon (magenta and cyan) or Noir (black and white with red)."},
                {"kind": "field", "label": "Sound", "value": f"◀ {'On' if prefs['sound'] else 'Off'} ▶", "tok": "sound",
                 "help": "Plays built-in macOS system sounds for shots, reloads, items and wins."},
                {"kind": "field", "label": "Animations", "value": f"◀ {prefs['speed'].title()} ▶", "tok": "speed",
                 "help": "Normal, Fast or Turbo. Turbo skips the screen wipe and trims every pause."},
                {"kind": "field", "label": "Mouse", "value": f"◀ {'On' if prefs['mouse'] else 'Off'} ▶", "tok": "mouse",
                 "help": "Click items and buttons. Turn it off to select text in Terminal normally."},
                {"kind": "button", "value": "Done", "tok": "done", "help": "Back to the main menu."},
            ]
            selectable = [k for k, r in enumerate(rows) if r["kind"] != "header"]
            if sel not in selectable:
                sel = min(selectable, key=lambda k: abs(k - sel))
            if self.frame():
                self.centered(1, "SETTINGS", self.col("item") | curses.A_BOLD)
                self.box(2, 10, len(rows) + 2, 80, "", curses.A_DIM)
                for k, r in enumerate(rows):
                    y = 3 + k
                    if r["kind"] == "header":
                        self.put(y, 13, f"── {r['label']} ".ljust(72, "─"), self.col("item") | curses.A_BOLD)
                        continue
                    a_sel = self.sel_attr() if k == sel else None
                    if r["kind"] == "field":
                        self.put(y, 13, r["label"], curses.A_BOLD)
                        dim = r["tok"] == "base" and not info.get("edit_base")
                        self.put(y, 28, f" {r['value']} "[:60], a_sel or (curses.A_DIM if dim else 0))
                    else:
                        self.put(y, 28, f"[ {r['value']} ]", a_sel or (self.col("item") | curses.A_BOLD))
                    self.hit(y, 12, 76, f"@row:{k}")
                hy = len(rows) + 4
                self.box(hy, 10, 4, 80, "", curses.A_DIM)
                self.put(hy + 1, 13, rows[sel]["help"][:74], curses.A_DIM)
                if note:
                    self.put(hy + 2, 13, note[:74], self.col(note_ck) | curses.A_BOLD)
                self.centered(29, "↑↓ move · Enter select/edit · ←→ change · Esc back", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey()
            if k.startswith("@row:"):
                sel = int(k[5:])
                k = "ENTER"
            tok = rows[sel]["tok"]
            if k == "UP":
                sel = selectable[(selectable.index(sel) - 1) % len(selectable)]
                continue
            if k in ("DOWN", "TAB"):
                sel = selectable[(selectable.index(sel) + 1) % len(selectable)]
                continue
            if k in ("ESC", "q", "Q"):
                return
            step = -1 if k == "LEFT" else 1
            if k in ("LEFT", "RIGHT", "ENTER", " ") and tok in cyclers:
                if tok == "provider":
                    config.data["provider"] = self._cycle(PROVIDER_ORDER, p, step)
                    brain.reset()
                    note = ""
                elif tok == "theme":
                    prefs["theme"] = self._cycle(THEME_ORDER, prefs["theme"], step)
                    self.apply_theme()
                elif tok == "sound":
                    prefs["sound"] = not prefs["sound"]
                    self.sound("item")
                elif tok == "speed":
                    prefs["speed"] = self._cycle(list(SPEEDS), prefs["speed"], step)
                elif tok == "mouse":
                    prefs["mouse"] = not prefs["mouse"]
                    self.apply_mouse()
                elif tok in ("events", "misfires"):
                    prefs[tok] = not prefs[tok]
                elif tok == "clock":
                    prefs["clock"] = self._cycle(CLOCK_OPTIONS, prefs["clock"], step)
                config.save()
                continue
            if k not in ("ENTER", " "):
                continue
            if tok == "done":
                return
            if tok == "key":
                s = self.text_input(f"PASTE YOUR {info['label'].upper()} API KEY", mask=True, maxlen=500, width=64,
                                    hint="Cmd+V to paste · Enter save · Esc cancel · Ctrl-U clear")
                if s:
                    note, note_ck = brain.set_key(s), "hp"
                    brain.reset()
                    if not brain.model():
                        n2, ck2 = self._pick_model(brain, config)
                        if n2:
                            note, note_ck = f"{note} {n2}", ck2
            elif tok == "base":
                if not info.get("edit_base"):
                    note, note_ck = "Gemini's URL is fixed.", "item"
                    continue
                s = self.text_input("BASE URL", prefill=brain.base_url(), maxlen=200, width=64)
                if s is not None:
                    config.data["base_urls"][p] = s.rstrip("/")
                    config.save()
                    brain.reset()
                    note, note_ck = ("Base URL saved." if s else "Base URL reset to the default."), "hp"
            elif tok == "model":
                s = self.text_input("MODEL ID", prefill=brain.model(), maxlen=120, width=64)
                if s:
                    config.data["models"][p] = s
                    config.save()
                    brain.reset()
                    note, note_ck = f"Model set to {s}.", "hp"
            elif tok == "pick":
                n2, ck2 = self._pick_model(brain, config)
                if n2:
                    note, note_ck = n2, ck2
            elif tok == "test":
                res, err = self.run_with_spinner("Testing the connection...", brain.test)
                brain.reset()
                if err:
                    note, note_ck = f"✗ {short_err(err)}", "live"
                else:
                    note, note_ck = f"✓ Connected: {brain.model()} answered in {res:.1f}s.", "hp"
            elif tok == "delkey":
                note, note_ck = brain.delete_key(), "item"
                brain.reset()


# ═════════════════════════════ game flow ═════════════════════════════
def decide(ui, g, i, brain, step, force_shot=False):
    if force_shot:
        return dealer_decision(g, i, allow_items=False)
    if brain.enabled:
        system = build_system_prompt(g)
        user = json.dumps(ai_state(g, i, step))
        think = g.rules["think"]
        w = Worker(lambda: brain.complete(system, user, think))
        w.start()
        ui.think(g, w, 0.5, brain.short_label())
        if w.error is None:
            d = validate_decision(g, i, parse_json_obj(w.result))
            if d:
                brain.failures = 0
                return d
        else:
            ui.msg = brain.note_failure(short_err(w.error))
    else:
        ui.think(g, None, 0.6 + random.random() * 0.6, None)
    d = dealer_decision(g, i)
    if g.dealer and random.random() < 0.25:
        d["taunt"] = random.choice(g.dealer["lines"])
    return d


def ai_turn(ui, g, brain):
    i = g.turn
    ui.play_events(g, g.try_high_roller())
    for step in range(14):
        if g.stage_winner is not None or g.turn != i or g.needs_reload:
            break
        d = decide(ui, g, i, brain, step, force_shot=(step == 13))
        if d.get("taunt"):
            ui.speech = d["taunt"]
        if d["action"] == "use_item":
            ok, _, ev = g.use_item(i, d["item"], d.get("arg"))
            if ok:
                ui.play_events(g, ev)
                continue
            d = dealer_decision(g, i, allow_items=False)
        ui.play_events(g, g.shoot(i, d["action"] == "shoot_self"))
        break
    if g.dealer_key == "liar" and g.stage_winner is None and g.turn != i:
        g.pending_tip = True
    curses.flushinp()


def give_tip(ui, g):
    g.pending_tip = False
    if g.left() <= 0:
        return
    line = g.make_tip()
    ui.speech = line
    g.add_log(f'{g.players[1].name} whispers: "{line}"', "dealer")
    ui.msg = "Press C to call his bluff, or ignore him."
    ui.set_face("grin", 1.5)
    ui.draw_board(g)
    ui.pause(1.2)


def item_args(ui, g, i, entry):
    """Ask the player for whatever an item needs. Returns (ok, arg)."""
    b = base(entry)
    o = g.players[1 - i]
    if b == "hook":
        opts = g.stealable(i)
        k = ui.choose(g, "↩ HOOK: steal which item?", [item_line(x) for x in opts])
        return (k is not None), (opts[k] if k is not None else None)
    if b == "crowbar":
        opts = list(o.items)
        k = ui.choose(g, "⌐ CROWBAR: smash which item?", [item_line(x) for x in opts])
        return (k is not None), (opts[k] if k is not None else None)
    if b == "decoy":
        k = ui.choose(g, "¤ DECOY: disguise the gift as...", [item_line(x) for x in DECOY_FORMS])
        return (k is not None), (DECOY_FORMS[k] if k is not None else None)
    if b == "slip":
        k = ui.choose(g, "↧ SLIP: which shell?", ["LIVE shell", "BLANK shell"])
        if k is None:
            return False, None
        n = g.left()
        labels = []
        for j in range(1, n + 2):
            tag = " (chamber: fires next)" if j == 1 else (" (bottom of the gun)" if j == n + 1 else "")
            labels.append(f"Position {j}{tag}")
        k2 = ui.choose(g, "↧ SLIP: where?", labels)
        if k2 is None:
            return False, None
        return True, {"live": k == 0, "pos": k2 + 1}
    return True, None


def time_up(ui, g):
    ui.clock_deadline = None
    i = g.turn
    p = g.players[i]
    at_self = random.random() < 0.5
    g.add_log(f"Time's up! {p.name} {g.v(p, 'fire')} blindly.", "live")
    ui.sound("trap")
    ui.draw_board(g)
    ui.popup([("◷ TIME'S UP", ui.col("live") | curses.A_BOLD), "",
              "Your hand slips. The gun goes off at a random target."], battr=ui.col("live"))
    ui.pause(1.4)
    ui.play_events(g, g.shoot(i, at_self))


def human_action(ui, g):
    i = g.turn
    p = g.players[i]
    limit = ui.clock_limit(g)
    if not limit:
        ui.clock_deadline = None
    elif ui.clock_deadline is None:
        ui.clock_deadline = time.time() + limit
    ctrls = ui.controls(g)
    ui.focus = max(0, min(ui.focus, len(ctrls) - 1))
    while True:
        remaining = (ui.clock_deadline - time.time()) if ui.clock_deadline else None
        if remaining is not None and remaining <= 0:
            time_up(ui, g)
            return None
        ui.draw_board(g, interactive=True, clock=(remaining, limit) if remaining is not None else None)
        poll = 150 if (remaining is not None or g.sudden) else None
        k = ui.getkey(timeout=poll)
        if k != "TICK":
            break
    ui.msg = ""
    if k in ("", "RESIZE", "CLICK"):
        return None
    t0 = time.time()

    def refund():
        """Dialogs and help screens don't eat the shot clock."""
        if ui.clock_deadline:
            ui.clock_deadline += time.time() - t0

    n = len(p.items)
    cols = 4 if i == 0 else 3
    act = None
    if k in ("LEFT", "BTAB"):
        ui.focus = (ui.focus - 1) % len(ctrls)
    elif k in ("RIGHT", "TAB"):
        ui.focus = (ui.focus + 1) % len(ctrls)
    elif k == "UP":
        if ui.focus >= n and n:
            ui.focus = n - 1
        elif ui.focus >= cols:
            ui.focus -= cols
    elif k == "DOWN":
        if ui.focus < n:
            ui.focus = ui.focus + cols if ui.focus + cols < n else n
    elif k in ("ENTER", " "):
        act = ctrls[ui.focus]
    elif k.startswith("@item:"):
        ui.focus = int(k[6:])
        act = ("item", ui.focus)
    elif k.startswith("@btn:"):
        act = ("btn", k[5:])
    elif len(k) == 1 and k.isdigit() and k != "0":
        if int(k) - 1 < n:
            ui.focus = int(k) - 1
            act = ("item", ui.focus)
        else:
            ui.msg = "No item in that slot."
    elif k in ("s", "S"):
        act = ("btn", "self")
    elif k in ("o", "O"):
        act = ("btn", "opp")
    elif k in ("c", "C"):
        if g.can_call():
            act = ("btn", "call")
        else:
            ui.msg = "There's no tip to call right now."
    elif k in ("?", "@help"):
        ui.help_screen()
        refund()
    elif k in ("i", "I"):
        ui.item_guide()
        refund()
    elif k in ("q", "Q", "ESC", "@quit"):
        if ui.confirm(g, "Leave the table? This run will be lost."):
            return "quit"
        refund()
    if not act:
        return None
    kind, val = act
    if kind == "btn":
        ui.clock_deadline = None
        if val == "call":
            if g.can_call():
                ui.play_events(g, g.call_bluff())
            return None
        ui.play_events(g, g.shoot(i, val == "self"))
        return None
    entry = p.items[val]
    ok, msg = g.can_use(i, entry)
    if not ok:
        ui.msg = msg
        return None
    ok, arg = item_args(ui, g, i, entry)
    refund()
    if not ok:
        return None
    ok, msg, ev = g.use_item(i, entry, arg)
    if ok:
        ui.clock_deadline = None
        ui.play_events(g, ev)
    else:
        ui.msg = msg
    return None


def stage_over(ui, g, config):
    """Handle the end of a stage. Returns True when the run or match is over."""
    w = g.stage_winner
    if not g.vs_ai:
        wp = g.players[w]
        wp.wins += 1
        a, b = g.players
        tally = f"{a.name} {a.wins} – {b.wins} {b.name}"
        if wp.wins >= 2:
            ui.banner(g, f"{wp.name.upper()} WINS THE MATCH", [tally], "hp")
            return True
        ui.banner(g, f"{wp.name.upper()} TAKES STAGE {g.stage}", [tally], "item")
        return False

    dname = g.players[1].name
    if w == 1:
        if g.mode == "gauntlet":
            lost, g.score = g.score, 0
            ui.banner(g, "YOU DIED", [f"{dname} got you in stage {g.stage}.",
                                      f"The house keeps all {lost} points." if lost else ""], "live")
        else:
            best = record_score(f"duel:{g.dealer_key}", g.score, f"died in stage {g.stage}")
            ui.banner(g, "YOU DIED", [f"{dname} wins in stage {g.stage}. Score: {g.score}",
                                      "New high score!" if best else ""], "live")
        return True

    pts = g.award(1000 * g.stage)
    note = ""
    if g.double_pending:
        g.score *= 2
        g.double_pending = False
        note = "Double or nothing paid off: score doubled!"
    if g.mode == "duel" and g.stage >= 3:
        g.award(2000)
        best = record_score(f"duel:{g.dealer_key}", g.score, "won")
        ui.banner(g, f"YOU BEAT {dname.upper()}", [note, f"Final score: {g.score}",
                                                   "New high score!" if best else ""], "hp")
        if g.dealer_key != "croupier" and config.unlock("croupier"):
            ui.banner(g, "THE CROUPIER WILL SEE YOU NOW",
                      ["A new dealer is waiting at the table.", "Pick him from the Duel menu."], "live")
        return True
    ui.banner(g, f"STAGE {g.stage} CLEARED", [f"+{pts} points. {note}".strip(), f"Score: {g.score}"], "hp")
    if g.mode == "gauntlet":
        if g.stage == 3 and config.unlock("croupier"):
            ui.banner(g, "THE CROUPIER WILL SEE YOU NOW",
                      ["He's now available in Duel mode too."], "live")
        if ui.ask_double(g) == "cash":
            best = record_score("gauntlet", g.score, f"cashed out after stage {g.stage}")
            ui.banner(g, "CASHED OUT", [f"You walk away with {g.score} points.",
                                        "New high score!" if best else ""], "item")
            return True
        g.double_pending = True
    return False


def run_game(ui, brain, config, mode, dealer_key=None):
    opts = {"events": config.prefs["events"], "misfires": config.prefs["misfires"]}
    if mode == "hotseat":
        n1 = ui.text_input("PLAYER 1 NAME", "Player 1", maxlen=12)
        if n1 is None:
            return
        n2 = ui.text_input("PLAYER 2 NAME", "Player 2", maxlen=12)
        if n2 is None:
            return
        g = Game("hotseat", [n1 or "Player 1", n2 or "Player 2"], vs_ai=False, opts=opts)
    elif mode == "duel":
        g = Game("duel", ["You", DEALERS[dealer_key]["name"]], vs_ai=True, dealer_key=dealer_key, opts=opts)
    else:
        g = Game("gauntlet", ["You", "?"], vs_ai=True, opts=opts)
    brain.reset()
    ui.new_game()
    ui.wipe()
    ui.play_events(g, g.start_stage())
    last = None
    while True:
        if g.stage_winner is not None:
            if stage_over(ui, g, config):
                return
            ui.speech = ""
            ui.focus = 0
            ui.clock_deadline = None
            ui.wipe()
            ui.play_events(g, g.start_stage())
            last = None
            continue
        if g.needs_reload:
            ui.clock_deadline = None
            ui.play_events(g, g.reload())
            continue
        if not g.vs_ai and g.turn != last:
            ui.clock_deadline = None
            ui.handover(g)
        last = g.turn
        if g.cur().is_ai:
            ui.clock_deadline = None
            ai_turn(ui, g, brain)
            continue
        if g.pending_tip:
            give_tip(ui, g)
        if g.update_tell():
            ui.draw_board(g)
            ui.pause(0.6)
        if human_action(ui, g) == "quit":
            return


def main(scr, offline=False):
    config = Config()
    brain = Brain(config, offline)
    ui = UI(scr, config)
    ui.brain = brain
    sel = 0
    while True:
        action, sel, extra = ui.main_menu(config, sel)
        if action == "quit":
            return
        if action == "duel":
            dk = ui.pick_dealer(config)
            if dk:
                run_game(ui, brain, config, "duel", dk)
        elif action == "fight":
            run_game(ui, brain, config, "duel", extra)
        elif action in ("gauntlet", "hotseat"):
            run_game(ui, brain, config, action)
        elif action == "items":
            ui.item_guide()
        elif action == "scores":
            ui.scores_screen()
        elif action == "settings":
            ui.settings(brain, config)
        elif action == "help":
            ui.help_screen()


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(main, "--offline" in sys.argv)
    except KeyboardInterrupt:
        pass
