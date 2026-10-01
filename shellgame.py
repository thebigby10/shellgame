#!/usr/bin/env python3
"""
SHELL GAME: a terminal duel of nerve, odds and one very loud gun.

  python3 shellgame.py             play
  python3 shellgame.py --offline   ignore AI settings; dealers use built-in strategies

AI dealers (optional): open Settings from the main menu, pick a provider
(Google Gemini, OpenAI, OpenRouter, Ollama or any OpenAI-compatible endpoint),
paste an API key (stored in the macOS Keychain) and choose a model.
Environment variables also work: GEMINI_API_KEY / GOOGLE_API_KEY,
OPENAI_API_KEY, OPENROUTER_API_KEY.

Python 3.8+, standard library only. Terminal must be at least 100x30.
Settings: ~/.shellgame_config.json    High scores: ~/.shellgame_scores.json
"""
import curses
import getpass
import json
import locale
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
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

ITEMS = {
    "loupe": {
        "label": "Loupe", "short": "peek at the chambered shell", "weight": 3,
        "desc": "Peer at the shell sitting in the chamber. Only you learn if it's live or blank; "
                "your opponent just sees you peek.",
        "tip": "Use it before deciding who to shoot. A Loupe followed by a Saw on a live shell is the classic combo.",
    },
    "rack": {
        "label": "Rack", "short": "eject the chambered shell", "weight": 3,
        "desc": "Pump the action and eject the chambered shell without firing it. Everyone sees "
                "what it was, and your turn goes on.",
        "tip": "Dump a shell you're afraid of, or thin out the gun when the odds are a coin flip.",
    },
    "saw": {
        "label": "Saw", "short": "next shot deals 2 damage", "weight": 2,
        "desc": "Saw off the barrel. Your next shot deals 2 damage instead of 1, whoever you aim at. "
                "Spent on that shot, live or blank.",
        "tip": "Best right after a Loupe shows a live shell. Never saw the barrel and then shoot yourself on a hunch.",
    },
    "shackles": {
        "label": "Shackles", "short": "opponent skips next turn", "weight": 2,
        "desc": "Chain your opponent to the table. They skip their next turn, so you act again. "
                "No effect on someone already chained.",
        "tip": "Use it when you know the next two shells are live, or to buy time while you're low.",
    },
    "tonic": {
        "label": "Tonic", "short": "+1 charge", "weight": 3,
        "desc": "A bitter drink that restores 1 charge, up to your maximum. It can't be used at full charge.",
        "tip": "Drink it early. A charge saved now is a live shell survived later.",
    },
    "flipper": {
        "label": "Flipper", "short": "invert the chambered shell", "weight": 2,
        "desc": "Invert the chambered shell: live becomes blank, blank becomes live. The new value "
                "is announced to both players.",
        "tip": "Turn a known blank into a live shell before shooting your opponent, or defuse a live shell you'd face.",
    },
    "radio": {
        "label": "Radio", "short": "learn a random future shell", "weight": 2,
        "desc": "A crackling voice tells you about one random shell further down the gun. Only you "
                "hear it; the chamber row marks it.",
        "tip": "Plan two moves ahead: if you know the second shell is live, a Rack or a blank to yourself sets it up.",
    },
    "hook": {
        "label": "Hook", "short": "steal an item, use it now", "weight": 1,
        "desc": "Steal one of your opponent's items and use it immediately. You can't steal a Hook.",
        "tip": "Steal their Loupe when you're blind, their Saw when you know it's live, or their Tonic when hurt.",
    },
    "pills": {
        "label": "Pills", "short": "50%: +2 charges, 50%: -1", "weight": 2,
        "desc": "Expired pills of unknown origin. Coin flip: restore 2 charges, or lose 1, which can "
                "knock you out cold.",
        "tip": "Only worth it when you're two or more charges down. Never swallow them on your last charge.",
    },
}
ITEM_KEYS = list(ITEMS)
STANDARD_POOL = {k: v["weight"] for k, v in ITEMS.items()}
STANDARD_RULES = {"hp": [2, 4, 5], "you_items": [2, 2, 3], "dealer_items": [2, 2, 3],
                  "counter": True, "mult": 1.0, "think": "low"}

GENERIC_EYES = {"idle": "(o) (o)", "hurt": "(x) (x)", "grin": "(^) (^)", "think": "(-) (o)", "dead": "(+) (+)"}
GENERIC_MOUTH = {"idle": "   ===   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ---   ",
                 "dead": "   ___   "}
PLAYER2_HEAD = ["     ,,,,,,,", "    .-------."]

DEALERS = {
    "accountant": {
        "name": "The Accountant", "tier": "EASY", "color": "hp",
        "tagline": "Cautious. Audits every shell before he shoots.",
        "bio": "A pale man in a green visor who logs every shell in a ledger. He won't act on a hunch "
               "while a Loupe is in reach, and he patches up the moment he's hurt.",
        "style": ["Always uses a Loupe or Radio before he shoots",
                  "Shoots you only when the numbers favor live",
                  "Heals at once with Tonic, never touches Pills"],
        "pool": {"loupe": 5, "tonic": 4, "radio": 3, "rack": 3, "shackles": 1, "saw": 1},
        "rules": {"hp": [3, 4, 5], "you_items": [2, 3, 3], "dealer_items": [2, 2, 3],
                  "counter": True, "mult": 1.0, "think": "low"},
        "head": ["     _______", "    /_______\\"],
        "eyes": {"idle": "[o]-[o]", "hurt": "[x]-[x]", "grin": "[^]-[^]", "think": "[-]-[o]", "dead": "[+]-[+]"},
        "mouth": {"idle": "   ---   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ...   ",
                  "dead": "   ___   "},
        "prompt": "You are THE ACCOUNTANT: meticulous, risk-averse and dry. Strategy: if the chambered shell "
                  "is unknown and you hold a loupe (or can hook one), ALWAYS use it first; use the radio "
                  "whenever you have it. Heal with tonic as soon as you are below max. Never take pills. "
                  "Shoot your opponent only when the shell is known live or the chance of live is 50% or "
                  "more; shoot yourself only when it is known blank or the chance of live is 30% or less. "
                  "Taunts: dry accounting jargon (ledgers, audits, margins, write-offs).",
        "lines": ["Let me check the figures.", "The numbers don't lie.", "Margins are thin today.",
                  "Filed under: your mistake.", "An audit is in order."],
    },
    "gambler": {
        "name": "The Gambler", "tier": "EASY", "color": "item",
        "tagline": "Reckless. Shoots himself on a coin flip, for the thrill.",
        "bio": "A loud high-roller with a gold tooth. He treats a coin flip as an invitation, saws "
               "the barrel on a hunch and eats Pills like candy.",
        "style": ["Shoots himself on 50/50s to chase the extra turn",
                  "Saws the barrel off on a hunch",
                  "Takes Pills when hurt, rarely bothers with a Loupe"],
        "pool": {"saw": 4, "pills": 4, "flipper": 3, "loupe": 1, "tonic": 1, "rack": 1},
        "rules": {"hp": [3, 4, 5], "you_items": [2, 3, 3], "dealer_items": [2, 3, 3],
                  "counter": True, "mult": 1.0, "think": "low"},
        "head": ["      ,---.", "  ___/_____\\___"],
        "eyes": {"idle": "($) ($)", "hurt": "(x) (x)", "grin": "(*) (*)", "think": "(o) (-)", "dead": "(x) (x)"},
        "mouth": {"idle": "   \\_/   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   -o-   ",
                  "dead": "   ___   "},
        "prompt": "You are THE GAMBLER: a reckless, flashy high-roller. Strategy: when the chance of live is "
                  "50% or less, shoot YOURSELF for the thrill of the extra turn; otherwise shoot your "
                  "opponent. Use the saw on hunches whenever the odds look even remotely good, take pills "
                  "whenever you are hurt, flip shells on a whim, and rarely bother with the loupe. "
                  "Taunts: casino slang (jackpots, hot streaks, let it ride).",
        "lines": ["Let it ride!", "Feeling lucky? I always am.", "Double or nothing, baby!",
                  "Hot streak incoming!", "House money, pal."],
    },
    "liar": {
        "name": "The Liar", "tier": "MEDIUM", "color": "dealer",
        "tagline": "A con artist. Tips you off about the next shell. Usually lies.",
        "bio": "Silver-tongued and smiling, he always has a tip about the next shell, and he's right "
               "just often enough to keep you listening.",
        "style": ["Whispers a 'tip' about the next shell each turn",
                  "Usually lies. Sometimes, cruelly, tells the truth",
                  "Favors Flipper, Hook and Shackles"],
        "pool": {"flipper": 3, "hook": 3, "shackles": 3, "loupe": 2, "radio": 2, "tonic": 1},
        "rules": {"hp": [2, 4, 5], "you_items": [2, 2, 3], "dealer_items": [2, 3, 4],
                  "counter": True, "mult": 1.5, "think": "low"},
        "head": ["     ~~~~~~~", "    .-------."],
        "eyes": {"idle": "(o) (-)", "hurt": "(x) (x)", "grin": "(^) (-)", "think": "(-) (-)", "dead": "(+) (+)"},
        "mouth": {"idle": "  \\___/~ ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ~~~   ",
                  "dead": "   ___   "},
        "prompt": "You are THE LIAR: a smooth, smiling con artist. Strategy: play solidly: use the loupe when "
                  "blind, turn known blanks live with the flipper, shackle your opponent when you know a live "
                  "shell is coming, and hook their best items. Taunts are your weapon: claim to know shells "
                  "you don't, and usually state the OPPOSITE of the truth about the chambered or next shell. "
                  "Tell the truth just often enough to stay unpredictable. Never admit to lying.",
        "lines": ["Would I lie to you?", "Trust me. Everyone does.", "I never bluff. Well. Rarely.",
                  "Such an honest face, isn't it?", "You look nervous. Good."],
    },
    "croupier": {
        "name": "The Croupier", "tier": "HARD · BOSS", "color": "live", "locked": True,
        "tagline": "The house itself. Cold, precise, almost never wrong.",
        "bio": "He deals every game in this room and has never been seen to lose. He wastes nothing, "
               "and at his table the shell counter goes dark.",
        "style": ["Plays the odds almost perfectly",
                  "Chains items: Loupe, then Saw on a live shell",
                  "Shell counter is switched off at his table"],
        "pool": dict(STANDARD_POOL),
        "rules": {"hp": [2, 3, 4], "you_items": [1, 2, 3], "dealer_items": [2, 3, 4],
                  "counter": False, "mult": 2.5, "think": "medium"},
        "head": ["      _____", "    _|_____|_"],
        "eyes": GENERIC_EYES,
        "mouth": GENERIC_MOUTH,
        "prompt": "You are THE CROUPIER: the house itself. Cold, courteous and nearly flawless. Strategy: "
                  "play the odds precisely, chain items (loupe, then saw on a live shell; flipper on a known "
                  "blank), heal before you are in danger, and never waste an item or a turn. "
                  "Taunts: quiet, polite menace.",
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
    "openai": {"label": "OpenAI", "short": "OpenAI", "kind": "openai",
               "base": "https://api.openai.com/v1", "model": "gpt-5.4-mini",
               "env": ["OPENAI_API_KEY"], "needs_key": True, "edit_base": False},
    "openrouter": {"label": "OpenRouter", "short": "OpenRouter", "kind": "openai",
                   "base": "https://openrouter.ai/api/v1", "model": "openai/gpt-5.4-mini",
                   "env": ["OPENROUTER_API_KEY"], "needs_key": True, "edit_base": False},
    "ollama": {"label": "Ollama (local)", "short": "Ollama", "kind": "openai",
               "base": "http://localhost:11434/v1", "model": "llama3.2",
               "env": [], "needs_key": False, "edit_base": True},
    "custom": {"label": "Custom OpenAI-compatible", "short": "Custom", "kind": "openai",
               "base": "", "model": "", "env": [], "needs_key": False, "edit_base": True},
}
PROVIDER_ORDER = ["off", "gemini", "openai", "openrouter", "ollama", "custom"]

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
        eyes, mouth = e.get(face, e["idle"]), m.get(face, m["idle"])
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


# ═════════════════════════════ game model ═════════════════════════════
class Player:
    def __init__(self, name, is_ai=False):
        self.name = name
        self.is_ai = is_ai
        self.hp = self.max_hp = 0
        self.items = []
        self.shackled = False
        self.known = {}  # absolute shell index -> True (live) / False (blank)
        self.wins = 0


class Game:
    def __init__(self, mode, names, vs_ai, dealer_key=None):
        self.mode, self.vs_ai, self.dealer_key = mode, vs_ai, dealer_key
        self.players = [Player(names[0]), Player(names[1], is_ai=vs_ai)]
        self.stage = 0
        self.shells, self.pos, self.spent = [], 0, []
        self.loaded = (0, 0)
        self.turn = 0
        self.sawed = False
        self.log = []
        self.score = 0
        self.stage_winner = None
        self.needs_reload = False
        self.double_pending = False
        self.pending_tip = False

    @property
    def dealer(self):
        return DEALERS.get(self.dealer_key) if self.dealer_key else None

    @property
    def rules(self):
        d = self.dealer
        return d["rules"] if d else STANDARD_RULES

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

    def remaining(self):
        rem = self.shells[self.pos:]
        live = sum(rem)
        return live, len(rem) - live

    def _scaled(self, key, cap):
        base = self.rules[key]
        idx = min(self.stage, 3) - 1
        extra = (self.stage - 2) // 2 if self.stage > 3 else 0
        return min(cap, base[idx] + extra)

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
            p.shackled = False
        self.sawed = False
        self.stage_winner = None
        self.pending_tip = False
        self.turn = 0 if self.vs_ai else (self.stage - 1) % 2
        intro = f" · {self.players[1].name} sits down" if self.mode == "gauntlet" else ""
        self.add_log(f"── STAGE {self.stage}{intro} · {hp} charges ──", "title")
        return self.reload()

    def reload(self):
        self.needs_reload = False
        lo, hi = {1: (2, 4), 2: (3, 6)}.get(self.stage, (4, 8))
        n = random.randint(lo, hi)
        live = random.randint(max(1, n // 2 - 1), min(n - 1, (n + 1) // 2 + 1))
        self.shells = [True] * live + [False] * (n - live)
        random.shuffle(self.shells)
        self.pos, self.spent, self.loaded = 0, [], (live, n - live)
        self.sawed = False
        for p in self.players:
            p.known = {}
        self.add_log(f"The gun is loaded: {live} live, {n - live} blank.", "info")
        for idx, p in enumerate(self.players):
            dealer_side = self.vs_ai and idx == 1
            pool = self.dealer["pool"] if dealer_side else STANDARD_POOL
            k = self._scaled("dealer_items" if dealer_side else "you_items", 6)
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
        return [("load", live, n - live)]

    # ── items
    def _can_apply(self, i, item, via_hook=False):
        p, o = self.players[i], self.players[1 - i]
        if item == "loupe" and self.pos in p.known:
            return False, "You already know the chambered shell."
        if item == "saw" and self.sawed:
            return False, "The barrel is already sawed off."
        if item == "shackles" and o.shackled:
            return False, f"{o.name} is already shackled."
        if item == "tonic" and p.hp >= p.max_hp:
            return False, "Already at full charge."
        if item == "radio" and len(self.shells) - self.pos < 2:
            return False, "No future shells to listen for."
        if item == "hook":
            if via_hook:
                return False, "You can't hook a Hook."
            if not self.stealable(i):
                return False, "Nothing worth stealing."
        return True, ""

    def can_use(self, i, item):
        if item not in self.players[i].items:
            return False, "You don't have that item."
        return self._can_apply(i, item)

    def stealable(self, i):
        out = []
        for x in self.players[1 - i].items:
            if x != "hook" and x not in out and self._can_apply(i, x, True)[0]:
                out.append(x)
        return out

    def legal_items(self, i):
        out = []
        for x in self.players[i].items:
            if x not in out and self._can_apply(i, x)[0]:
                out.append(x)
        return out

    def use_item(self, i, item, steal=None):
        ok, msg = self.can_use(i, item)
        if not ok:
            return False, msg, []
        if item == "hook" and steal not in self.stealable(i):
            return False, "Pick something to steal.", []
        self.players[i].items.remove(item)
        return True, "", self._apply(i, item, steal)

    def _apply(self, i, item, steal=None):
        p, o = self.players[i], self.players[1 - i]
        P = p.name
        ev = []
        if item == "loupe":
            live = self.shells[self.pos]
            p.known[self.pos] = live
            self.add_log(f"{P} {self.v(p, 'peek')} into the chamber with a Loupe.", "item")
            ev.append(("private", i, f"The chambered shell is {'LIVE' if live else 'BLANK'}.", live))
        elif item == "rack":
            live = self.shells[self.pos]
            self.pos += 1
            self.spent.append(live)
            self.add_log(f"{P} {self.v(p, 'rack')} the gun: a {'LIVE' if live else 'BLANK'} shell drops out.",
                         "live" if live else "blank")
            ev.append(("eject", live))
            if self.pos >= len(self.shells):
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
            p.hp = min(p.max_hp, p.hp + 1)
            self.add_log(f"{P} {self.v(p, 'drink')} a Tonic: +1 charge.", "item")
            ev.append(("minor",))
        elif item == "flipper":
            self.shells[self.pos] = not self.shells[self.pos]
            now = self.shells[self.pos]
            for pl in self.players:
                pl.known[self.pos] = now
            self.add_log(f"{P} {self.v(p, 'flip')} the chambered shell. It's now {'LIVE' if now else 'BLANK'}.",
                         "live" if now else "blank")
            ev.append(("minor",))
        elif item == "radio":
            k = random.randrange(self.pos + 1, len(self.shells))
            live = self.shells[k]
            p.known[k] = live
            self.add_log(f"{P} {self.v(p, 'tune')} the Radio. A voice whispers...", "item")
            ev.append(("private", i,
                       f"The {ordinal(k - self.pos + 1)} shell is {'LIVE' if live else 'BLANK'} "
                       f"(the chambered one is 1st).", live))
        elif item == "hook":
            o.items.remove(steal)
            self.add_log(f"{P} {self.v(p, 'hook')} {self.poss(o)} {ITEMS[steal]['label']}!", "item")
            ev += self._apply(i, steal)
        elif item == "pills":
            if random.random() < 0.5:
                p.hp = min(p.max_hp, p.hp + 2)
                self.add_log(f"{P} {self.v(p, 'swallow')} the Pills: +2 charges.", "item")
                ev.append(("minor",))
            else:
                p.hp = max(0, p.hp - 1)
                self.add_log(f"{P} {self.v(p, 'swallow')} the Pills. Bad batch: -1 charge.", "live")
                ev.append(("hurt", i))
                if p.hp <= 0:
                    self.stage_winner = 1 - i
                    self.add_log(f"{P} {self.v(p, 'collapse')}.", "live")
        return ev

    # ── shooting
    def shoot(self, i, at_self):
        p = self.players[i]
        ti = i if at_self else 1 - i
        t = self.players[ti]
        ov = {"hp": {ti: t.hp}, "pos": self.pos, "sawed": self.sawed, "spent": len(self.spent)}
        live = self.shells[self.pos]
        self.pos += 1
        self.spent.append(live)
        dmg = 2 if self.sawed else 1
        self.sawed = False
        who = self.refl(p) if at_self else self.obj(t)
        if live:
            t.hp = max(0, t.hp - dmg)
            self.add_log(f"{p.name} {self.v(p, 'shoot')} {who}. BANG! -{dmg}.", "live")
            if self.vs_ai and i == 0 and not at_self:
                self.award(100 * dmg)
        else:
            tail = " Extra turn." if at_self else ""
            self.add_log(f"{p.name} {self.v(p, 'shoot')} {who}. Click, blank.{tail}", "blank")
            if self.vs_ai and i == 0 and at_self:
                self.award(150)
        ev = [("shot", i, ti, live, dmg, ov)]
        if t.hp <= 0:
            self.stage_winner = 1 - ti
            self.add_log(f"{t.name} {self.v(t, 'go')} down.", "live")
            return ev
        if live or not at_self:
            self.pass_turn()
        if self.pos >= len(self.shells):
            self.needs_reload = True
            self.add_log("The gun is empty.", "info")
        return ev

    def pass_turn(self):
        nxt = self.players[1 - self.turn]
        if nxt.shackled:
            nxt.shackled = False
            self.add_log(f"{nxt.name} {self.v(nxt, 'be')} shackled and {self.v(nxt, 'lose')} a turn.", "item")
        else:
            self.turn = 1 - self.turn


# ═════════════════════════════ built-in dealer strategies ═════════════════════════════
def _use(item, steal=None):
    return {"action": "use_item", "item": item, "steal": steal}


def _opp():
    return {"action": "shoot_opponent"}


def _me():
    return {"action": "shoot_self"}


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
            return _use(it, random.choice(g.stealable(i)) if it == "hook" else None)
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
    ctx = {"L": legal, "st": g.stealable(i) if "hook" in legal else [],
           "cur": g.effective_current(i), "pl": g.chance_live(i),
           "p": g.players[i], "o": g.players[1 - i], "n": len(g.shells) - g.pos}
    d = STRATEGIES.get(g.dealer_key, strat_croupier)(g, i, ctx)
    d.setdefault("steal", None)
    return d


def liar_tip(g, i):
    truth = g.effective_current(i)
    if truth is None:
        claim = random.random() < 0.5
    else:
        claim = (not truth) if random.random() < 0.7 else truth
    return random.choice(LIAR_SAYS_LIVE if claim else LIAR_SAYS_BLANK)


# ═════════════════════════════ AI prompts ═════════════════════════════
SYSTEM_RULES = """You are {name}, an opponent in SHELL GAME, a turn-based terminal duel.
A shotgun is loaded with a publicly known number of LIVE and BLANK shells in a hidden random order.

Rules:
- On your turn you may use items one at a time, then you must shoot: yourself or your opponent.
- A live shell removes 1 charge from the target (2 if the saw is active). A blank does nothing.
- Shooting YOURSELF with a BLANK lets you keep your turn. Every other shot ends your turn.
- A player at 0 charges loses the stage. When the gun is empty it is reloaded and both players draw new items.

Items:
- loupe: privately see the chambered shell.
- rack: eject the chambered shell without firing; everyone sees it.
- saw: your next shot deals 2 damage.
- shackles: your opponent skips their next turn.
- tonic: +1 charge (not above max).
- flipper: invert the chambered shell (live <-> blank); the new value is announced to everyone.
- radio: privately learn one random future shell (position 1 = chambered).
- hook: steal one opponent item (not a hook) and use it immediately. Put its name in "steal".
- pills: 50% chance +2 charges, 50% chance -1 charge (can kill you).

You receive the game state as JSON. Choose exactly ONE next action; you will be asked again after each item.
Only use items listed in "usable_items". Stay in character: your personality below decides your strategy.

Reply with JSON only, no prose:
{"action": "use_item" | "shoot_self" | "shoot_opponent", "item": "<item or null>", "steal": "<item or null>", "taunt": "<one short in-character line, max 60 characters>"}"""


def build_system_prompt(dealer):
    return SYSTEM_RULES.replace("{name}", dealer["name"].upper()) + "\n\nPersonality:\n" + dealer["prompt"]


def ai_state(g, i, step):
    p, o = g.players[i], g.players[1 - i]
    live, blank = g.remaining()
    cur = g.effective_current(i)
    future = {str(k - g.pos + 1): ("live" if v else "blank")
              for k, v in sorted(p.known.items()) if k > g.pos}
    return {
        "you_are": p.name, "opponent": o.name, "stage": g.stage,
        "your_charges": p.hp, "max_charges": p.max_hp, "opponent_charges": o.hp,
        "shells_remaining": live + blank, "live_remaining": live, "blank_remaining": blank,
        "chambered_shell": "unknown" if cur is None else ("live" if cur else "blank"),
        "chance_chambered_is_live": round(g.chance_live(i), 2),
        "known_future_shells": future,
        "saw_active": g.sawed, "opponent_shackled": o.shackled,
        "your_items": p.items, "opponent_items": o.items,
        "usable_items": g.legal_items(i),
        "stealable_with_hook": g.stealable(i) if "hook" in p.items else [],
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
    if act == "use_item":
        item = str(d.get("item") or "").strip().lower()
        if item not in g.legal_items(i):
            return None
        out = {"action": "use_item", "item": item, "taunt": taunt, "steal": None}
        if item == "hook":
            steal = str(d.get("steal") or "").strip().lower()
            opts = g.stealable(i)
            out["steal"] = steal if steal in opts else random.choice(opts)
        return out
    return None


# ═════════════════════════════ networking ═════════════════════════════
class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg

    def __str__(self):
        return f"HTTP {self.code}: {self.msg}" if self.code else self.msg


def http_json(url, body=None, headers=None, timeout=API_TIMEOUT):
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers or {},
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        msg = detail.strip()
        try:
            j = json.loads(detail)
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, dict):
                msg = err.get("message") or msg
            elif isinstance(err, str):
                msg = err
        except ValueError:
            pass
        raise ApiError(e.code, " ".join(str(msg).split())[:160])
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
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "off"


class Config:
    def __init__(self):
        d = load_json(CONFIG_FILE)
        for k, t in (("models", dict), ("base_urls", dict), ("unlocked", list)):
            if not isinstance(d.get(k), t):
                d[k] = t()
        if d.get("provider") not in PROVIDERS:
            d["provider"] = detect_provider()
        self.data = d

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
                   "moderation", "search", "sora", "davinci", "babbage")

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

    def ready(self):
        p = self.provider
        if p == "off" or not self.base_url() or not self.model():
            return False
        return bool(self.key()[0]) or not self.needs_key()

    def reset(self):
        self.enabled = self.ready()
        self.failures = 0
        self.gem_thinking = True
        self.json_mode = True

    def short_label(self):
        return PROVIDERS[self.provider]["short"] if self.enabled else "built-in"

    def status_line(self):
        if self.offline:
            return "AI: off (--offline). Dealers use their built-in strategies.", "dim"
        p = self.provider
        if p == "off":
            return "AI: off. Dealers use built-in strategies. Open Settings to connect an AI.", "dim"
        label = PROVIDERS[p]["label"]
        if not self.ready():
            return f"AI: {label} is selected but needs a key or model. Open Settings.", "item"
        return f"AI: {label} · {self.model()} · key: {self.key()[1]}", "hp"

    # ── requests
    def complete(self, system, user, think="low"):
        p = self.provider
        kind = PROVIDERS[p]["kind"]
        key = self.key(p)[0]
        timeout = 60 if p == "ollama" else API_TIMEOUT
        if kind == "gemini":
            return self._gemini(system, user, think, key, timeout)
        if kind == "openai":
            return self._openai(system, user, key, timeout)
        raise ApiError(0, "no AI provider selected")

    def _gemini(self, system, user, think, key, timeout):
        gen = {"responseMimeType": "application/json"}
        if self.gem_thinking:
            gen["thinkingConfig"] = {"thinkingLevel": think}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": gen}
        url = f"{self.base_url()}/models/{self.model()}:generateContent"
        try:
            resp = http_json(url, body, {"Content-Type": "application/json", "x-goog-api-key": key or ""}, timeout)
        except ApiError as e:
            if e.code == 400 and self.gem_thinking and "think" in e.msg.lower():
                self.gem_thinking = False
                return self._gemini(system, user, think, key, timeout)
            raise
        cands = resp.get("candidates") or []
        if not cands:
            raise ApiError(0, "empty reply")
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts if not part.get("thought"))

    def _openai(self, system, user, key, timeout):
        body = {"model": self.model(),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "X-Title": "Shell Game"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = http_json(f"{self.base_url()}/chat/completions", body, headers, timeout)
        except ApiError as e:
            low = e.msg.lower()
            if e.code in (400, 422) and self.json_mode and ("response_format" in low or "json" in low):
                self.json_mode = False
                return self._openai(system, user, key, timeout)
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
        else:
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            resp = http_json(f"{self.base_url()}/models", None, headers)
            ids = [m.get("id") for m in resp.get("data", []) if isinstance(m, dict) and m.get("id")]
            out = [x for x in ids if not any(s in x.lower() for s in self.SKIP_MODELS)] or ids
        return sorted(set(out))

    def test(self):
        if not self.ready():
            raise ApiError(0, "add an API key and a model first")
        t0 = time.time()
        text = self.complete('Reply with the JSON object {"ok": true} and nothing else. This is JSON mode.',
                             "ping", "low")
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
    ("items", "Item guide", "What every item does and when to use it."),
    ("scores", "High scores", "Your best runs against each dealer."),
    ("settings", "Settings", "Connect Gemini or an OpenAI-compatible AI to play the dealers."),
    ("help", "How to play", "The rules on one screen."),
    ("quit", "Quit", "Leave the table."),
]

HELP_TEXT = [
    ("THE GUN", True),
    ("Each load holds a known mix of LIVE and BLANK shells in a hidden order. The TABLE panel", False),
    ("shows what was loaded, what's been spent and, at most tables, how many of each are left.", False),
    ("YOUR TURN", True),
    ("Use as many items as you like, then shoot: your opponent, or yourself.", False),
    ("  • Live shell: the target loses 1 charge (2 if the barrel is sawed off).", False),
    ("  • Blank at yourself: you keep your turn. Any other shot ends it.", False),
    ("Lose every charge and you lose the stage. An empty gun is reloaded and both players", False),
    ("draw new items (8 max). You always draw from the standard pool; dealers carry their own.", False),
    ("MODES", True),
    ("Duel: beat one dealer three stages running. Beat anyone to unlock the Croupier.", False),
    ("Gauntlet: every dealer in turn, forever. After each stage: cash out, or double or nothing.", False),
    ("Hot-seat: two humans, one keyboard, best of three stages.", False),
    ("CONTROLS", True),
    ("←→ / Tab select an item or action · ↑↓ jump between items and actions · Enter use it", False),
    ("1-8 quick-use an item · S shoot yourself · O shoot opponent · ? help · I item guide · Q menu", False),
    ("The mouse works too: click items, buttons, menu entries and dealers.", False),
    ("DEALERS", True),
    ("Each dealer has a personality, a strategy and an item pool. Read their profile before you", False),
    ("sit down. The Liar's tips are worth exactly what you paid for them.", False),
]


# ═════════════════════════════ UI ═════════════════════════════
class UI:
    KEYMAP = {curses.KEY_UP: "UP", curses.KEY_DOWN: "DOWN", curses.KEY_LEFT: "LEFT", curses.KEY_RIGHT: "RIGHT",
              curses.KEY_PPAGE: "PGUP", curses.KEY_NPAGE: "PGDN", curses.KEY_HOME: "HOME", curses.KEY_END: "END",
              curses.KEY_BTAB: "BTAB", curses.KEY_ENTER: "ENTER", curses.KEY_BACKSPACE: "BACKSPACE",
              curses.KEY_DC: "BACKSPACE", curses.KEY_RESIZE: "RESIZE"}

    def __init__(self, scr):
        self.scr = scr
        self.oy = self.ox = 0
        self.hits = []
        self.brain = None
        self.c = {}
        self.new_game()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        scr.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except curses.error:
            pass
        if curses.has_colors():
            curses.start_color()
            bg = -1
            try:
                curses.use_default_colors()
            except curses.error:
                bg = curses.COLOR_BLACK
            spec = [("live", curses.COLOR_RED, bg), ("blank", curses.COLOR_CYAN, bg),
                    ("item", curses.COLOR_YELLOW, bg), ("hp", curses.COLOR_GREEN, bg),
                    ("dealer", curses.COLOR_MAGENTA, bg), ("flash", curses.COLOR_WHITE, curses.COLOR_RED),
                    ("title", curses.COLOR_BLACK, curses.COLOR_YELLOW)]
            for n, (name, fg, b) in enumerate(spec, 1):
                try:
                    curses.init_pair(n, fg, b)
                    self.c[name] = curses.color_pair(n)
                except curses.error:
                    pass

    def new_game(self):
        self.msg = ""
        self.speech = ""
        self.face, self.face_until = "idle", 0.0
        self.thinking = False
        self.override = None
        self.aim = None
        self.focus = 0

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
            self.scr.addstr(self.oy + y, self.ox + x, s[:W - x], attr)
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

    def getkey(self):
        while True:
            c = self.scr.getch()
            if c == -1:
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

    def wait_key(self):
        self.scr.refresh()
        curses.flushinp()
        while True:
            k = self.getkey()
            if k not in ("RESIZE", ""):
                return k

    def pause(self, secs):
        """Wait up to secs. Returns True if a key or click skipped it."""
        self.scr.refresh()
        end = time.time() + secs
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

    def set_face(self, name, secs):
        self.face, self.face_until = name, time.time() + secs

    def current_face(self, g):
        if g.players[1].hp <= 0:
            return "dead"
        if time.time() < self.face_until:
            return self.face
        return "think" if self.thinking else "idle"

    def kind_attr(self, kind):
        return {"live": self.col("live"), "blank": self.col("blank"), "item": self.col("item"),
                "dealer": self.col("dealer"), "title": curses.A_BOLD}.get(kind, 0)

    def border(self, active):
        return (self.col("item") | curses.A_BOLD) if active else curses.A_DIM

    # ═════════ game board ═════════
    def controls(self, g):
        p = g.cur()
        return [("item", k) for k in range(len(p.items))] + [("btn", "opp"), ("btn", "self")]

    def charges(self, g, idx, y, x, ov):
        p = g.players[idx]
        hp = ov.get("hp", {}).get(idx, p.hp)
        bar = self.col("live") if hp <= 1 else self.col("hp")
        self.put(y, x, "CHARGES", curses.A_BOLD)
        self.put(y, x + 8, "█" * hp, bar | curses.A_BOLD)
        self.put(y, x + 8 + hp, "░" * max(0, p.max_hp - hp), curses.A_DIM)
        self.put(y, x + 9 + p.max_hp, f"{hp}/{p.max_hp}")
        if p.shackled:
            self.put(y, x + 14 + p.max_hp, "SHACKLED", self.col("item") | curses.A_BOLD)

    def item_grid(self, g, idx, y, x, cols, cell, interactive):
        p = g.players[idx]
        if not p.items:
            self.put(y, x, "(no items)", curses.A_DIM)
        for k, it in enumerate(p.items):
            r, c = divmod(k, cols)
            cy, cx = y + r, x + c * cell
            label = ITEMS[it]["label"]
            if interactive:
                text = f" {k + 1} {label} ".ljust(cell - 1)
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
                self.put(cy, cx, f" · {label}", self.col("item") if p.is_ai else 0)

    def draw_info(self, g, interactive):
        x, y, iw = RIGHT_X, 1, RIGHT_W - 4
        title, lines = "INFO", []
        if interactive:
            p, i = g.cur(), g.turn
            ctrls = self.controls(g)
            kind, val = ctrls[max(0, min(self.focus, len(ctrls) - 1))]
            if kind == "item":
                it = p.items[val]
                info = ITEMS[it]
                title = f"ITEM · {info['label'].upper()}"
                lines = [(l, 0) for l in wrap(info["desc"], iw)] + [("", 0)]
                ok, why = g.can_use(i, it)
                if ok:
                    lines.append(("Enter to use it.", self.col("item") | curses.A_BOLD))
                else:
                    lines += [(l, self.col("live")) for l in wrap("Can't use now: " + why, iw)]
            else:
                o = g.players[1 - i]
                title = "ACTION"
                if val == "opp":
                    txt = [f"Shoot {g.obj(o)}.", "Live: they lose 1 charge (2 if sawed off).", "Blank: your turn ends."]
                else:
                    txt = ["Shoot yourself.", "Blank: you keep your turn.", "Live: you lose 1 charge (2 if sawed off)."]
                for t in txt:
                    lines += [(l, 0) for l in wrap(t, iw)]
                if g.rules["counter"]:
                    lines += [("", 0), (f"Odds it's live: {round(100 * g.chance_live(i))}%",
                                        self.col("item") | curses.A_BOLD)]
        elif g.dealer:
            d = g.dealer
            title = d["name"].upper()
            lines = [(l, curses.A_DIM) for l in wrap(d["tagline"], iw)] + [("", 0)]
            for s in d["style"]:
                lines += [(l, 0) for l in wrap("• " + s, iw)]
        else:
            title = "HOT-SEAT"
            lines = [(l, 0) for l in wrap("Two players, one keyboard, best of three stages. "
                                          "Look away when the other player peeks.", iw)]
        self.box(y, x, 10, RIGHT_W, title, self.border(interactive), curses.A_BOLD)
        for k, (t, a) in enumerate(lines[:8]):
            self.put(y + 1 + k, x + 2, t, a)

    def action_bar(self, g, interactive):
        p, o = g.cur(), g.players[1 - g.turn]
        n = len(p.items)
        btns = [("opp", f" SHOOT {o.name.upper()[:16]} ", "live"), ("self", " SHOOT YOURSELF ", "blank")]
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
            x += len(s) + 3
        if interactive:
            for lbl, tok, bx in ((" ? HELP ", "@help", 72), (" Q MENU ", "@quit", 84)):
                s = f"[{lbl}]"
                self.put(26, bx, s, curses.A_BOLD)
                self.hit(26, bx, len(s), tok)

    def draw_board(self, g, status=None, interactive=False):
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
        self.put(0, 0, t[:W].ljust(W), self.col("title", curses.A_REVERSE) | curses.A_BOLD)

        # opponent / player 2
        act1 = g.turn == 1 and g.stage_winner is None
        dcol = self.col(dealer["color"]) if dealer else 0
        name1 = top.name.upper() + (f" · {dealer['tier']}" if dealer else "")
        self.box(1, 0, 10, LEFT_W, ("▶ " if act1 else "") + name1, self.border(act1), curses.A_BOLD | dcol)
        for k, line in enumerate(portrait(dealer, self.current_face(g))):
            self.put(2 + k, 2, line, dcol)
        self.charges(g, 1, 2, 20, ov)
        if dealer:
            self.put(3, 20, dealer["tagline"][:42], curses.A_DIM)
        self.item_grid(g, 1, 4, 20, 3, 14, interactive and g.turn == 1)
        if self.speech and g.vs_ai:
            for k, line in enumerate(wrap(f"“{self.speech}”", 58)[:2]):
                self.put(8 + k, 3, line, dcol | curses.A_BOLD)

        # table
        self.box(11, 0, 9, LEFT_W, "TABLE", curses.A_DIM)
        if self.aim:
            self.put(12, 2, self.aim[:58], self.col("live") | curses.A_BOLD)
        elif g.stage_winner is None:
            cur = g.cur()
            whose = "YOUR TURN" if cur.name == "You" else f"{cur.name.upper()}'S TURN"
            self.put(12, 2, f"{'▲' if g.turn == 1 else '▼'} {whose}", curses.A_BOLD)
        sawed = ov.get("sawed", g.sawed)
        for k, line in enumerate(gun_art(sawed)):
            self.put(13 + k, 2, line)
        if sawed:
            self.put(13, 48, "SAWED OFF", self.col("live") | curses.A_BOLD)
            self.put(14, 48, "next shot x2", self.col("live"))
        pos = ov.get("pos", g.pos)
        known = g.players[viewer].known
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
        for k, s in enumerate(g.spent[:ov.get("spent", len(g.spent))]):
            self.put(17, 42 + 2 * k, "▮", self.col("live" if s else "blank"))
        lv, bl = g.loaded
        rem = g.shells[pos:]
        rl = sum(rem)
        self.segs(18, 2, [("LOADED ", curses.A_BOLD), (f"{lv} live ", self.col("live")),
                          (f"{bl} blank", self.col("blank"))])
        if g.rules["counter"]:
            self.segs(18, 28, [("LEFT ", curses.A_BOLD), (f"{rl} live ", self.col("live")),
                               (f"{len(rem) - rl} blank", self.col("blank"))])
            if not ov and g.stage_winner is None and not g.players[viewer].is_ai:
                self.put(18, 50, f"ODDS {round(100 * g.chance_live(viewer))}% live", self.col("item"))
        else:
            self.segs(18, 28, [("LEFT ", curses.A_BOLD), ("?  count SPENT", curses.A_DIM)])

        # you / player 1
        act0 = g.turn == 0 and g.stage_winner is None
        self.box(20, 0, 6, LEFT_W, ("▶ " if act0 else "") + bot.name.upper(), self.border(act0))
        self.charges(g, 0, 21, 2, ov)
        self.item_grid(g, 0, 22, 2, 4, 15, interactive and g.turn == 0)

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
        if self.msg:
            self.put(28, 2, self.msg[:W - 4], self.col("item"))
        if interactive:
            self.put(29, 2, "←→ select  ↑↓ items/actions  Enter use  1-8 item  S self  O opponent  "
                            "? help  I items  Q menu", curses.A_DIM)
        self.scr.refresh()

    # ═════════ animations ═════════
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
            time.sleep(0.07)
            self.draw_board(g)
            time.sleep(0.07)

    def anim_load(self, g, live, blank):
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

    def anim_shot(self, g, shooter, target, live, dmg, ov):
        s, t = g.players[shooter], g.players[target]
        arrow = "▲▲▲" if target == 1 else "▼▼▼"
        at = g.refl(s) if shooter == target else g.obj(t)
        self.override = ov
        self.aim = f"{arrow} {s.name} {g.v(s, 'aim')} at {at} {arrow}"
        self.draw_board(g)
        self.pause(1.1)
        self.aim = None
        if live:
            self.flash(g)
            self.override = None
            if g.vs_ai:
                self.set_face("hurt" if target == 1 else "grin", 2.0)
            self.draw_board(g)
            c = self.col("live") | curses.A_BOLD
            self.popup([(l, c) for l in big("BANG!")]
                       + ["", f"{t.name} {g.v(t, 'lose')} {dmg} charge{'s' if dmg > 1 else ''}."],
                       battr=self.col("live"))
            self.pause(1.4)
        else:
            self.override = None
            self.draw_board(g)
            self.popup([("*click*", self.col("blank") | curses.A_BOLD), "", "Blank."], battr=self.col("blank"))
            self.pause(1.0)
        self.draw_board(g)

    def private(self, g, idx, text, live):
        p = g.players[idx]
        if p.is_ai:
            self.set_face("think", 1.5)
            self.draw_board(g)
            self.pause(0.9)
            return
        if not g.vs_ai:
            if self.frame():
                self.popup([(f"FOR {p.name.upper()}'S EYES ONLY", self.col("item") | curses.A_BOLD), "",
                            "Everyone else: look away.", "", ("press any key to reveal", curses.A_DIM)])
            self.wait_key()
        self.draw_board(g)
        c = self.col("live" if live else "blank")
        self.popup([("SECRET", curses.A_BOLD), "", (text, c | curses.A_BOLD), "",
                    ("press any key", curses.A_DIM)], battr=c)
        self.wait_key()
        self.draw_board(g)

    def play_events(self, g, events):
        for e in events:
            kind = e[0]
            if kind == "load":
                self.anim_load(g, e[1], e[2])
            elif kind == "shot":
                self.anim_shot(g, *e[1:])
            elif kind == "private":
                self.private(g, *e[1:])
            elif kind == "eject":
                c = self.col("live" if e[1] else "blank")
                self.draw_board(g)
                self.popup(["The shell drops out:", "", ("LIVE" if e[1] else "BLANK", c | curses.A_BOLD)], battr=c)
                self.pause(1.1)
            elif kind == "hurt":
                if g.vs_ai and e[1] == 1:
                    self.set_face("hurt", 1.5)
                self.draw_board(g)
                self.pause(0.8)
            else:
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
            if done and time.time() - start >= min_time:
                break
            self.draw_board(g, status=f"{SPIN[k % len(SPIN)]} {who} is thinking...{suffix}")
            k += 1
            time.sleep(0.08)
        self.thinking = False

    # ═════════ dialogs ═════════
    def banner(self, g, title, lines, ck):
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

    def choose(self, g, title, options):
        self.draw_board(g)
        rows = [(title, curses.A_BOLD), ""]
        rows += [f"[{k + 1}] {ITEMS[o]['label']:<9}{ITEMS[o]['short']}" for k, o in enumerate(options)]
        rows += ["", ("number or click to pick · Esc cancel", curses.A_DIM)]
        top, left, iw = self.popup(rows, align="left")
        for k in range(len(options)):
            self.hit(top + 2 + k, left, iw, f"@c:{k}")
        while True:
            k = self.wait_key()
            if k == "ESC":
                return None
            if k.startswith("@c:"):
                return options[int(k[3:])]
            if len(k) == 1 and k.isdigit() and 1 <= int(k) <= len(options):
                return options[int(k) - 1]

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
        while True:
            if self.frame():
                for k, line in enumerate(TITLE_ART):
                    self.centered(1 + k, line, self.col("item") | curses.A_BOLD)
                self.centered(6, "a terminal duel of nerve, odds and one very loud gun", curses.A_DIM)
                self.box(8, 34, 10, 32, "MENU", curses.A_DIM)
                for k, (_, label, _) in enumerate(MENU):
                    y = 9 + k
                    self.put(y, 36, f" {k + 1}  {label}".ljust(28), self.sel_attr() if k == sel else 0)
                    self.hit(y, 35, 30, f"@menu:{k}")
                self.centered(19, MENU[sel][2], curses.A_DIM)
                for k, dk in enumerate(DEALER_ORDER):
                    d = DEALERS[dk]
                    x = 8 + k * 23
                    locked = not config.unlocked(dk)
                    a = curses.A_DIM if locked else self.col(d["color"])
                    for r, line in enumerate(portrait(d, "idle", locked)):
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
            k = self.getkey()
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
                    self.put(17, 37, "CARRIES", curses.A_BOLD)
                    pool = sorted(d["pool"].items(), key=lambda kv: -kv[1])
                    carries = ", ".join(ITEMS[k]["label"] for k, _ in pool) + ". You draw from the standard pool."
                    for r, l in enumerate(wrap(carries, 58)[:2]):
                        self.put(18 + r, 37, l)
                    rl = d["rules"]
                    self.put(21, 37, "STAKES", curses.A_BOLD)
                    self.put(22, 37, f"Charges per stage {'/'.join(map(str, rl['hp']))}  ·  "
                                     f"your items per load {'/'.join(map(str, rl['you_items']))}")
                    self.put(23, 37, f"Score x{rl['mult']:g}  ·  shell counter {'shown' if rl['counter'] else 'HIDDEN'}")
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
        sel = 0
        while True:
            it = ITEM_KEYS[sel]
            info = ITEMS[it]
            if self.frame():
                self.centered(1, "ITEM GUIDE", self.col("item") | curses.A_BOLD)
                self.box(3, 2, 11, 26, "ITEMS", curses.A_DIM)
                for k, key in enumerate(ITEM_KEYS):
                    self.put(4 + k, 4, f" {ITEMS[key]['label']}".ljust(22), self.sel_attr() if k == sel else 0)
                    self.hit(4 + k, 3, 24, f"@i:{k}")
                self.box(3, 30, 24, 68, info["label"].upper(), self.col("item"), curses.A_BOLD | self.col("item"))
                y = 5
                self.put(y, 33, info["short"][0].upper() + info["short"][1:], self.col("item") | curses.A_BOLD)
                y += 2
                for head, body in (("WHAT IT DOES", info["desc"]), ("WHEN TO USE IT", info["tip"])):
                    self.put(y, 33, head, curses.A_BOLD)
                    y += 1
                    for l in wrap(body, 62):
                        self.put(y, 33, l)
                        y += 1
                    y += 1
                common = [DEALERS[d]["name"] for d in DEALER_ORDER if DEALERS[d]["pool"].get(it, 0) >= 3]
                rare = [DEALERS[d]["name"] for d in DEALER_ORDER if 0 < DEALERS[d]["pool"].get(it, 0) < 3]
                parts = []
                if common:
                    parts.append("Common at: " + ", ".join(common) + ".")
                if rare:
                    parts.append("Rare at: " + ", ".join(rare) + ".")
                parts.append("You can always draw it from the standard pool.")
                self.put(y, 33, "WHERE YOU'LL SEE IT", curses.A_BOLD)
                y += 1
                for l in wrap(" ".join(parts), 62):
                    self.put(y, 33, l)
                    y += 1
                self.centered(29, "↑↓ browse · Esc back", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey()
            if k == "UP":
                sel = (sel - 1) % len(ITEM_KEYS)
            elif k in ("DOWN", "TAB"):
                sel = (sel + 1) % len(ITEM_KEYS)
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
            y = 2
            for text, head in HELP_TEXT:
                if head and y > 2:
                    y += 0
                self.put(y, 7, text, (self.col("item") | curses.A_BOLD) if head else 0)
                y += 1
            self.centered(29, "press any key", curses.A_DIM)
            self.scr.refresh()
        self.wait_key()

    def settings(self, brain, config):
        sel, note, note_ck = 0, "", "item"
        while True:
            p = brain.provider
            info = PROVIDERS[p]
            rows = [("Provider", f"◀ {info['label']} ▶", "provider",
                     "Who plays the dealers. ←/→ or Enter to switch. 'Off' uses the built-in strategies.")]
            if p != "off":
                key, src = brain.key()
                if key:
                    kv = f"{mask_key(key)}   ({src})"
                elif not brain.needs_key():
                    kv = "optional, not set"
                else:
                    kv = "not set: press Enter to paste one"
                eb = info.get("edit_base")
                rows += [
                    ("API key", kv, "key",
                     "Enter to paste a key. It's stored in the macOS Keychain (service 'shellgame'), never in a file."),
                    ("Base URL", brain.base_url() or "(not set)", "base",
                     "The OpenAI-compatible endpoint, usually ending in /v1. Enter to edit."
                     if eb else "Fixed for this provider. Pick 'Custom' to use another endpoint."),
                    ("Model", brain.model() or "(not set)", "model",
                     "Enter to type a model ID, or pick one from the list below."),
                    ("", "Choose model from list", "pick", "Fetches the models your key can use and lets you pick one."),
                    ("", "Test connection", "test", "Sends one tiny request to check the key, URL and model."),
                ]
                if key and src in ("macOS Keychain", "this session only"):
                    rows.append(("", "Remove saved key", "delkey", "Deletes this provider's key from the Keychain."))
            rows.append(("", "Done", "done", "Back to the main menu."))
            sel = max(0, min(sel, len(rows) - 1))
            if self.frame():
                self.centered(1, "SETTINGS", self.col("item") | curses.A_BOLD)
                self.centered(2, "Connect an AI to play the dealers, or leave it off.", curses.A_DIM)
                self.box(4, 10, len(rows) * 2 + 1, 80, "AI BRAIN", curses.A_DIM)
                for k, (label, val, tok, _) in enumerate(rows):
                    y = 5 + k * 2
                    if label:
                        self.put(y, 13, label, curses.A_BOLD)
                        dim = tok == "base" and not info.get("edit_base")
                        a = self.sel_attr() if k == sel else (curses.A_DIM if dim else 0)
                        self.put(y, 26, f" {val} "[:62], a)
                    else:
                        a = self.sel_attr() if k == sel else (self.col("item") | curses.A_BOLD)
                        self.put(y, 26, f"[ {val} ]", a)
                    self.hit(y, 12, 76, f"@row:{k}")
                self.box(23, 10, 5, 80, "HELP", curses.A_DIM)
                self.put(24, 13, rows[sel][3][:74], curses.A_DIM)
                if note:
                    for r, l in enumerate(wrap(note, 74)[:2]):
                        self.put(25 + r, 13, l, self.col(note_ck) | curses.A_BOLD)
                self.centered(29, "↑↓ move · Enter select/edit · ←→ switch provider · Esc back", curses.A_DIM)
                self.scr.refresh()
            k = self.getkey()
            if k.startswith("@row:"):
                sel = int(k[5:])
                k = "ENTER"
            tok = rows[sel][2]
            if k == "UP":
                sel = (sel - 1) % len(rows)
                continue
            if k in ("DOWN", "TAB"):
                sel = (sel + 1) % len(rows)
                continue
            if k in ("ESC", "q", "Q"):
                return
            if tok == "provider" and k in ("LEFT", "RIGHT", "ENTER", " "):
                i = PROVIDER_ORDER.index(p) if p in PROVIDER_ORDER else 0
                i = (i + (-1 if k == "LEFT" else 1)) % len(PROVIDER_ORDER)
                config.data["provider"] = PROVIDER_ORDER[i]
                config.save()
                brain.reset()
                note = ""
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
            elif tok == "base":
                if not info.get("edit_base"):
                    note, note_ck = "This provider's URL is fixed. Pick 'Custom' to use another endpoint.", "item"
                    continue
                s = self.text_input("BASE URL", prefill=brain.base_url(), maxlen=200, width=64)
                if s is not None:
                    config.data["base_urls"][p] = s.rstrip("/")
                    config.save()
                    brain.reset()
                    note, note_ck = "Base URL saved.", "hp"
            elif tok == "model":
                s = self.text_input("MODEL ID", prefill=brain.model(), maxlen=120, width=64)
                if s:
                    config.data["models"][p] = s
                    config.save()
                    brain.reset()
                    note, note_ck = f"Model set to {s}.", "hp"
            elif tok == "pick":
                res, err = self.run_with_spinner("Fetching models...", brain.list_models)
                if err:
                    note, note_ck = f"Couldn't list models: {short_err(err)}", "live"
                elif not res:
                    note, note_ck = "The server returned no models.", "item"
                else:
                    m = self.select_list("CHOOSE A MODEL", res, brain.model())
                    if m:
                        config.data["models"][p] = m
                        config.save()
                        brain.reset()
                        note, note_ck = f"Model set to {m}.", "hp"
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
        system = build_system_prompt(g.dealer)
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
    for step in range(12):
        if g.stage_winner is not None or g.turn != i or g.needs_reload:
            break
        d = decide(ui, g, i, brain, step, force_shot=(step == 11))
        if d.get("taunt"):
            ui.speech = d["taunt"]
        if d["action"] == "use_item":
            ok, _, ev = g.use_item(i, d["item"], d.get("steal"))
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
    line = liar_tip(g, 1)
    ui.speech = line
    g.add_log(f'{g.players[1].name} whispers: "{line}"', "dealer")
    ui.set_face("grin", 1.5)
    ui.draw_board(g)
    ui.pause(1.2)


def human_action(ui, g):
    i = g.turn
    p = g.players[i]
    ctrls = ui.controls(g)
    ui.focus = max(0, min(ui.focus, len(ctrls) - 1))
    ui.draw_board(g, interactive=True)
    k = ui.getkey()
    ui.msg = ""
    if k in ("", "RESIZE", "CLICK"):
        return None
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
    elif k in ("?", "@help"):
        ui.help_screen()
    elif k in ("i", "I"):
        ui.item_guide()
    elif k in ("q", "Q", "ESC", "@quit"):
        if ui.confirm(g, "Leave the table? This run will be lost."):
            return "quit"
    if not act:
        return None
    kind, val = act
    if kind == "btn":
        ui.play_events(g, g.shoot(i, val == "self"))
        return None
    it = p.items[val]
    ok, msg = g.can_use(i, it)
    if not ok:
        ui.msg = msg
        return None
    steal = None
    if it == "hook":
        steal = ui.choose(g, "HOOK: steal which item?", g.stealable(i))
        if steal is None:
            return None
    ok, msg, ev = g.use_item(i, it, steal)
    if ok:
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
    if mode == "hotseat":
        n1 = ui.text_input("PLAYER 1 NAME", "Player 1", maxlen=12)
        if n1 is None:
            return
        n2 = ui.text_input("PLAYER 2 NAME", "Player 2", maxlen=12)
        if n2 is None:
            return
        g = Game("hotseat", [n1 or "Player 1", n2 or "Player 2"], vs_ai=False)
    elif mode == "duel":
        g = Game("duel", ["You", DEALERS[dealer_key]["name"]], vs_ai=True, dealer_key=dealer_key)
    else:
        g = Game("gauntlet", ["You", "?"], vs_ai=True)
    brain.reset()
    ui.new_game()
    ui.play_events(g, g.start_stage())
    last = None
    while True:
        if g.stage_winner is not None:
            if stage_over(ui, g, config):
                return
            ui.speech = ""
            ui.focus = 0
            ui.play_events(g, g.start_stage())
            last = None
            continue
        if g.needs_reload:
            ui.play_events(g, g.reload())
            continue
        if not g.vs_ai and g.turn != last:
            ui.handover(g)
        last = g.turn
        if g.cur().is_ai:
            ai_turn(ui, g, brain)
            continue
        if g.pending_tip:
            give_tip(ui, g)
        if human_action(ui, g) == "quit":
            return


def main(scr, offline=False):
    config = Config()
    brain = Brain(config, offline)
    ui = UI(scr)
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
