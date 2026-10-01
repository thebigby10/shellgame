#!/usr/bin/env python3
"""
SHELL GAME: a terminal duel of nerve, odds and one very loud gun.

  python3 shellgame.py             play
  python3 shellgame.py --offline   ignore Gemini, use the built-in dealer

Let Gemini play the dealer:
  export GEMINI_API_KEY="your-key"          (GOOGLE_API_KEY also works)
  export GEMINI_MODEL="gemini-3.8-flash"    (optional override)

Python 3.8+, standard library only. Terminal must be at least 80x24.
High scores are saved to ~/.shellgame_scores.json
"""
import curses
import getpass
import json
import locale
import os
import random
import ssl
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from datetime import date

os.environ.setdefault("ESCDELAY", "25")

# ───────────────────────────── config ─────────────────────────────
DEFAULT_MODEL = "gemini-3.8-flash"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_TIMEOUT = 20
SCORE_FILE = os.path.expanduser("~/.shellgame_scores.json")
W, H = 80, 24
LOG_X, LOG_W = 48, 31
MAX_ITEMS = 8

ITEMS = {  # key: (label, short description, draw weight)
    "loupe":    ("Loupe",    "peek at the chambered shell", 3),
    "rack":     ("Rack",     "eject the chambered shell",   3),
    "saw":      ("Saw",      "next shot deals 2 damage",    2),
    "shackles": ("Shackles", "opponent skips next turn",    2),
    "tonic":    ("Tonic",    "+1 charge",                   3),
    "flipper":  ("Flipper",  "invert the chambered shell",  2),
    "radio":    ("Radio",    "learn a random future shell", 2),
    "hook":     ("Hook",     "steal an item, use it now",   1),
    "pills":    ("Pills",    "50%: +2 charges, 50%: -1",    2),
}
ITEM_KEYS = list(ITEMS)
ITEM_WEIGHTS = [ITEMS[k][2] for k in ITEM_KEYS]

DIFFICULTY = {
    "easy":   {"hp": [3, 4, 5], "items": [2, 3, 4], "counter": True,  "think": "low",    "mult": 0.5, "sloppy": 0.3},
    "normal": {"hp": [2, 4, 5], "items": [1, 2, 4], "counter": True,  "think": "low",    "mult": 1.0, "sloppy": 0.0},
    "hard":   {"hp": [2, 3, 4], "items": [1, 2, 3], "counter": False, "think": "medium", "mult": 2.0, "sloppy": 0.0},
}

TAUNTS = [
    "Feeling lucky?", "The house always wins.", "Tick, tock.", "Don't blink.",
    "Let's make this interesting.", "Odds are odds. Nerves are nerves.",
    "One of us is sweating. Not me.", "Care to double down?",
]

# ───────────────────────────── art ─────────────────────────────
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


_EYES = {"idle": "(o) (o)", "hurt": "(x) (x)", "grin": "(^) (^)", "think": "(-) (o)", "dead": "(+) (+)"}
_MOUTH = {"idle": "   ===   ", "hurt": "   ~~~   ", "grin": "  \\___/  ", "think": "   ---   ", "dead": "   ___   "}


def portrait(face, dealer):
    head = ["      _____", "    _|_____|_"] if dealer else ["     ,,,,,,,", "    .-------."]
    return head + [
        "   /  _   _  \\",
        "  |  " + _EYES[face] + "  |",
        "   \\" + _MOUTH[face] + "/",
        "    '-------'",
    ]


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


# ───────────────────────────── game model ─────────────────────────────
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
    def __init__(self, mode, diff, names, vs_ai):
        self.mode, self.diff, self.vs_ai = mode, diff, vs_ai
        self.cfg = DIFFICULTY[diff]
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
        pts = int(pts * self.cfg["mult"])
        self.score += pts
        return pts

    def remaining(self):
        rem = self.shells[self.pos:]
        live = sum(rem)
        return live, len(rem) - live

    def _scaled(self, key, cap):
        base = self.cfg[key]
        if self.stage <= 3:
            return base[self.stage - 1]
        return min(cap, base[2] + (self.stage - 2) // 2)

    def effective_current(self, i):
        """What player i can know or deduce about the chambered shell."""
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
        hp = self._scaled("hp", 6)
        for p in self.players:
            p.hp = p.max_hp = hp
            p.items = []
            p.shackled = False
        self.sawed = False
        self.stage_winner = None
        self.turn = 0 if self.vs_ai else (self.stage - 1) % 2
        self.add_log(f"── STAGE {self.stage} · {hp} charges each ──", "title")
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
        k = self._scaled("items", 5)
        for p in self.players:
            got = []
            for _ in range(k):
                if len(p.items) >= MAX_ITEMS:
                    break
                it = random.choices(ITEM_KEYS, weights=ITEM_WEIGHTS)[0]
                p.items.append(it)
                got.append(ITEMS[it][0])
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
            self.add_log(f"{P} {self.v(p, 'hook')} {self.poss(o)} {ITEMS[steal][0]}!", "item")
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


# ───────────────────────────── built-in dealer ─────────────────────────────
def heuristic_decision(g, i, sloppy=0.0, allow_items=True):
    p, o = g.players[i], g.players[1 - i]
    legal = g.legal_items(i) if allow_items else []
    n = len(g.shells) - g.pos
    cur = g.effective_current(i)

    def use(it, steal=None):
        return {"action": "use_item", "item": it, "steal": steal}

    opp, me = {"action": "shoot_opponent"}, {"action": "shoot_self"}

    if sloppy and random.random() < sloppy:
        if legal and random.random() < 0.5:
            it = random.choice(legal)
            return use(it, random.choice(g.stealable(i)) if it == "hook" else None)
        return dict(random.choice([opp, me]))

    steal_ok = g.stealable(i) if "hook" in legal else []
    if "tonic" in legal:
        return use("tonic")
    if "pills" in legal and p.hp >= 2 and p.max_hp - p.hp >= 2:
        return use("pills")
    if cur is None:
        if "loupe" in legal:
            return use("loupe")
        if "loupe" in steal_ok:
            return use("hook", "loupe")
        if "radio" in legal and n > 2 and random.random() < 0.4:
            return use("radio")
        pl = g.chance_live(i)
        if "rack" in legal and 0.4 <= pl <= 0.6:
            return use("rack")
        if pl >= 0.5:
            if "saw" in legal and pl >= 0.65 and o.hp > 1:
                return use("saw")
            return opp
        if "flipper" in legal and pl <= 0.25:
            return use("flipper")
        return me
    if cur:
        if "shackles" in legal and n > 1:
            return use("shackles")
        if "saw" in legal and o.hp > 1:
            return use("saw")
        if "saw" in steal_ok and o.hp > 1:
            return use("hook", "saw")
        return opp
    if "flipper" in legal:
        return use("flipper")
    return me


# ───────────────────────────── Gemini dealer ─────────────────────────────
SYSTEM_PROMPT = """You are THE CROUPIER, the house opponent in SHELL GAME, a turn-based terminal duel.
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
Only use items listed in "usable_items". If "chambered_shell" is known, act on it.

Reply with JSON only, no prose:
{"action": "use_item" | "shoot_self" | "shoot_opponent", "item": "<item or null>", "steal": "<item or null>", "taunt": "<one short in-character line, max 60 characters>"}"""

PERSONAS = {
    "easy": "Personality: overconfident and sloppy. You trust your gut over the odds, sometimes waste items, and love a dramatic gamble.",
    "normal": "Personality: a calm professional. Play sensibly and follow the odds.",
    "hard": "Personality: ruthless and precise. Play to win: weigh probabilities carefully, combine items "
            "(for example loupe, then saw on a live shell) and never waste a turn.",
}


def ai_state(g, i, step):
    p, o = g.players[i], g.players[1 - i]
    live, blank = g.remaining()
    cur = g.effective_current(i)
    future = {str(k - g.pos + 1): ("live" if v else "blank")
              for k, v in sorted(p.known.items()) if k > g.pos}
    return {
        "you_are": p.name,
        "opponent": o.name,
        "stage": g.stage,
        "your_charges": p.hp,
        "max_charges": p.max_hp,
        "opponent_charges": o.hp,
        "shells_remaining": live + blank,
        "live_remaining": live,
        "blank_remaining": blank,
        "chambered_shell": "unknown" if cur is None else ("live" if cur else "blank"),
        "chance_chambered_is_live": round(g.chance_live(i), 2),
        "known_future_shells": future,
        "saw_active": g.sawed,
        "opponent_shackled": o.shackled,
        "your_items": p.items,
        "opponent_items": o.items,
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
    t = "".join(c for c in t if c.isprintable() and ord(c) < 0x2E80)
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
        out = {"action": "use_item", "item": item, "taunt": taunt}
        if item == "hook":
            steal = str(d.get("steal") or "").strip().lower()
            opts = g.stealable(i)
            out["steal"] = steal if steal in opts else random.choice(opts)
        return out
    return None


class GeminiDealer:
    def __init__(self, offline=False):
        self.offline = offline
        self.key = None if offline else (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        self.model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self.reset()

    def reset(self):
        self.enabled = bool(self.key)
        self.failures = 0
        self.use_thinking = True

    def status(self):
        if self.offline:
            return "Dealer brain: built-in (--offline)"
        if not self.key:
            return "Dealer brain: built-in. Set GEMINI_API_KEY to let Gemini play."
        return f"Dealer brain: Gemini ({self.model})"

    def decide(self, g, i, step):
        system = SYSTEM_PROMPT + "\n\n" + PERSONAS[g.diff]
        text = self._generate(system, json.dumps(ai_state(g, i, step)), g.cfg["think"])
        return parse_json_obj(text)

    def _generate(self, system, user, think):
        gen = {"responseMimeType": "application/json"}
        if self.use_thinking:
            gen["thinkingConfig"] = {"thinkingLevel": think}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }
        req = urllib.request.Request(
            API_URL.format(model=self.model),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            msg = detail
            try:
                msg = json.loads(detail)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                pass
            if e.code == 400 and self.use_thinking and "think" in msg.lower():
                self.use_thinking = False  # older model: retry without thinkingConfig
                return self._generate(system, user, think)
            raise RuntimeError(f"HTTP {e.code}: {msg[:80]}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                raise RuntimeError("SSL certs missing; run 'Install Certificates.command' for your Python")
            raise RuntimeError(f"network: {e.reason}")
        cands = resp.get("candidates") or []
        if not cands:
            raise RuntimeError("empty reply")
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts if not part.get("thought"))

    def note_failure(self, err):
        self.failures += 1
        if self.failures >= 3:
            self.enabled = False
            return f"Gemini unavailable ({err}). Built-in dealer takes over."
        return f"Gemini hiccup ({err}). The dealer improvised."


class Worker(threading.Thread):
    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.result, self.error = fn, None, None

    def run(self):
        try:
            self.result = self.fn()
        except Exception as e:  # noqa: BLE001 - surfaced to the player
            self.error = e


# ───────────────────────────── scores ─────────────────────────────
def user_name():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "player"


def load_scores():
    try:
        with open(SCORE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def record_score(mode, diff, score, result):
    if score <= 0:
        return False
    data = load_scores()
    key = f"{mode}:{diff}"
    lst = [e for e in data.get(key, []) if isinstance(e, dict)]
    best = score > max((e.get("score", 0) for e in lst), default=0)
    lst.append({"name": user_name(), "score": int(score), "result": result, "date": date.today().isoformat()})
    lst.sort(key=lambda e: -e.get("score", 0))
    data[key] = lst[:10]
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass
    return best


def help_lines():
    b = curses.A_BOLD
    rows = [
        ("HOW TO PLAY", b),
        "The gun holds a known mix of LIVE and BLANK shells in a hidden order.",
        "On your turn use as many items as you like, then shoot yourself or",
        "your opponent. A live shell costs the target 1 charge (2 if sawed off).",
        "Shoot yourself with a blank and you keep your turn; any other shot",
        "passes it. Hit 0 charges and you lose the stage. An empty gun is",
        "reloaded and everyone draws new items (max 8 each).",
        "",
        ("ITEMS", b),
    ]
    for k in range(0, len(ITEM_KEYS), 2):
        a = ITEM_KEYS[k]
        left = f"{ITEMS[a][0]:<9}{ITEMS[a][1]:<28}"
        right = ""
        if k + 1 < len(ITEM_KEYS):
            z = ITEM_KEYS[k + 1]
            right = f"{ITEMS[z][0]:<9}{ITEMS[z][1]}"
        rows.append(left + right)
    rows += [
        "",
        ("KEYS", b),
        "1-8 use item   S shoot yourself   O shoot opponent   ? help   Q quit",
        "",
        "Hard mode hides the LEFT counter. Count the SPENT row yourself.",
        "Hot-seat: look away when the other player uses a Loupe or Radio.",
        "",
        ("press any key", curses.A_DIM),
    ]
    return rows


# ───────────────────────────── UI ─────────────────────────────
class UI:
    def __init__(self, scr):
        self.scr = scr
        self.oy = self.ox = 0
        self.gem = None
        self.c = {}
        self.new_game()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        scr.keypad(True)
        if curses.has_colors():
            curses.start_color()
            bg = -1
            try:
                curses.use_default_colors()
            except curses.error:
                bg = curses.COLOR_BLACK
            spec = [
                ("live", curses.COLOR_RED, bg), ("blank", curses.COLOR_CYAN, bg),
                ("item", curses.COLOR_YELLOW, bg), ("hp", curses.COLOR_GREEN, bg),
                ("dealer", curses.COLOR_MAGENTA, bg), ("flash", curses.COLOR_WHITE, curses.COLOR_RED),
                ("title", curses.COLOR_BLACK, curses.COLOR_YELLOW),
            ]
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

    # ── primitives
    def col(self, k, default=0):
        return self.c.get(k, default)

    def frame(self):
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        if h < H or w < W:
            msg = f"Enlarge the terminal to at least {W}x{H} (now {w}x{h})."
            try:
                self.scr.addstr(0, 0, msg[:max(0, w - 1)])
            except curses.error:
                pass
            self.scr.refresh()
            return False
        self.oy, self.ox = (h - H) // 2, (w - W) // 2
        return True

    def put(self, y, x, s, attr=0):
        if y < 0 or y >= H or x < 0 or x >= W:
            return
        try:
            self.scr.addstr(self.oy + y, self.ox + x, s[:W - x], attr)
        except curses.error:
            pass

    def segs(self, y, x, parts):
        for t, a in parts:
            self.put(y, x, t, a)
            x += len(t)

    def getkey(self):
        while True:
            c = self.scr.getch()
            if c == -1:
                continue
            if c == curses.KEY_RESIZE:
                return "RESIZE"
            if c in (10, 13, curses.KEY_ENTER):
                return "\n"
            if c in (8, 127, curses.KEY_BACKSPACE):
                return "\b"
            if 0 <= c < 128:
                return chr(c)
            return ""

    def wait_key(self):
        self.scr.refresh()
        curses.flushinp()
        while True:
            k = self.getkey()
            if k != "RESIZE":
                return k

    def pause(self, secs):
        """Sleep up to secs; returns True if a key was pressed (to skip)."""
        self.scr.refresh()
        end = time.time() + secs
        while True:
            rem = end - time.time()
            if rem <= 0:
                return False
            self.scr.timeout(max(1, int(rem * 1000)))
            c = self.scr.getch()
            self.scr.timeout(-1)
            if c not in (-1, curses.KEY_RESIZE):
                return True

    def popup(self, lines, width=None, battr=None, align="center"):
        rows = [(l, 0) if isinstance(l, str) else l for l in lines]
        iw = width or max([len(t) for t, _ in rows] + [16])
        iw = min(iw, W - 6)
        bw, bh = iw + 4, len(rows) + 2
        top, left = max(0, (H - bh) // 2), (W - bw) // 2
        ba = self.col("item") if battr is None else battr
        self.put(top, left, "┌" + "─" * (bw - 2) + "┐", ba)
        for k, (t, a) in enumerate(rows):
            y = top + 1 + k
            self.put(y, left, "│", ba)
            self.put(y, left + 1, " " * (bw - 2))
            txt = t[:iw]
            off = (iw - len(txt)) // 2 if align == "center" else 0
            self.put(y, left + 2 + off, txt, a)
            self.put(y, left + bw - 1, "│", ba)
        self.put(top + bh - 1, left, "└" + "─" * (bw - 2) + "┘", ba)
        return top + 1, left + 2, iw

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
                "title": curses.A_BOLD}.get(kind, 0)

    # ── board
    def header(self, y, name, active):
        mark = "▶ " if active else "  "
        attr = (self.col("item") | curses.A_BOLD) if active else curses.A_DIM
        self.put(y, 0, f"{mark}{name.upper()} ".ljust(LOG_X - 2, "─"), attr)

    def stats(self, g, idx, y, x, cols, cell, ov, inline_status=False):
        p = g.players[idx]
        hp = ov.get("hp", {}).get(idx, p.hp)
        bar = self.col("live") if hp <= 1 else self.col("hp")
        self.put(y, x, "CHARGES", curses.A_BOLD)
        self.put(y, x + 8, "█" * hp, bar | curses.A_BOLD)
        self.put(y, x + 8 + hp, "░" * max(0, p.max_hp - hp), curses.A_DIM)
        self.put(y, x + 9 + p.max_hp, f"{hp}/{p.max_hp}")
        sy, sx = (y, x + 14 + p.max_hp) if inline_status else (y + 1, x)
        if p.shackled:
            self.put(sy, sx, "SHACKLED", self.col("item") | curses.A_BOLD)
        iy = y + 1 if inline_status else y + 2
        active = g.turn == idx and not p.is_ai and g.stage_winner is None
        if not p.items:
            self.put(iy, x, "(no items)", curses.A_DIM)
        for k, it in enumerate(p.items):
            r, c = divmod(k, cols)
            cx = x + c * cell
            if active:
                self.put(iy + r, cx, f"[{k + 1}]", self.col("item") | curses.A_BOLD)
            else:
                self.put(iy + r, cx, " · ", curses.A_DIM)
            self.put(iy + r, cx + 3, ITEMS[it][0], self.col("item") if (active or p.is_ai) else 0)

    def draw_board(self, g, status=None):
        if not self.frame():
            return
        ov = self.override or {}
        top, bot = g.players[1], g.players[0]
        viewer = 0 if g.vs_ai else g.turn

        stage = f"Stage {g.stage}" + ("" if g.mode == "endless" else "/3")
        if g.vs_ai:
            sc = f"Score {g.score}" + (" (x2 on clear)" if g.double_pending else "")
            brain = "Gemini" if (self.gem and self.gem.enabled) else "built-in"
            t = f" SHELL GAME │ {stage} │ {g.diff.upper()} │ {sc} │ Dealer: {brain}"
        else:
            t = f" SHELL GAME │ {stage} │ {g.diff.upper()} │ {bot.name} {bot.wins} – {top.wins} {top.name}"
        self.put(0, 0, t[:W].ljust(W), self.col("title", curses.A_REVERSE) | curses.A_BOLD)

        # log panel
        for y in range(1, 22):
            self.put(y, LOG_X - 2, "│", curses.A_DIM)
        self.put(1, LOG_X, "LOG ".ljust(LOG_W, "─"), curses.A_DIM)
        lines = []
        for text, kind in g.log[-40:]:
            for wl in textwrap.wrap(text, LOG_W) or [""]:
                lines.append((wl, kind))
        for k, (tx, kind) in enumerate(lines[-20:]):
            self.put(2 + k, LOG_X, tx, self.kind_attr(kind))

        # top player
        self.header(1, top.name, g.turn == 1 and g.stage_winner is None)
        pc = self.col("dealer") if g.vs_ai else 0
        for k, line in enumerate(portrait(self.current_face(g), g.vs_ai)):
            self.put(2 + k, 0, line, pc)
        self.stats(g, 1, 2, 18, cols=2, cell=13, ov=ov)
        if g.vs_ai and self.speech:
            self.put(8, 1, f'"{self.speech[:42]}"', self.col("dealer"))
        if self.aim:
            self.put(9, 1, self.aim[:45], self.col("live") | curses.A_BOLD)

        # gun + shells
        sawed = ov.get("sawed", g.sawed)
        for k, line in enumerate(gun_art(sawed)):
            self.put(10 + k, 0, line)
        if sawed:
            self.put(13, 1, "SAWED OFF: x2", self.col("live") | curses.A_BOLD)
        pos = ov.get("pos", g.pos)
        known = g.players[viewer].known
        self.put(14, 1, "CHAMBER ▸", curses.A_BOLD)
        x = 12
        for k in range(pos, len(g.shells)):
            kv = known.get(k)
            if kv is None:
                ch, a = "▯", curses.A_DIM
            else:
                ch, a = "▮", self.col("live" if kv else "blank") | curses.A_BOLD
            if k == pos:
                self.put(14, x, "[", curses.A_BOLD)
                self.put(14, x + 1, ch, a)
                self.put(14, x + 2, "]", curses.A_BOLD)
                x += 4
            else:
                self.put(14, x, ch, a)
                x += 2
        lv, bl = g.loaded
        rem = g.shells[pos:]
        rl = sum(rem)
        self.segs(15, 1, [("LOADED ", curses.A_BOLD), (f"{lv} live ", self.col("live")),
                          (f"{bl} blank", self.col("blank"))])
        if g.cfg["counter"]:
            self.segs(15, 25, [("LEFT ", curses.A_BOLD), (f"{rl} live ", self.col("live")),
                               (f"{len(rem) - rl} blank", self.col("blank"))])
        else:
            self.segs(15, 25, [("LEFT ", curses.A_BOLD), ("?  count SPENT", curses.A_DIM)])
        self.put(16, 1, "SPENT", curses.A_BOLD)
        for k, s in enumerate(g.spent[:ov.get("spent", len(g.spent))]):
            self.put(16, 9 + 2 * k, "▮", self.col("live" if s else "blank"))

        # bottom player
        self.header(17, bot.name, g.turn == 0 and g.stage_winner is None)
        self.stats(g, 0, 18, 1, cols=4, cell=11, ov=ov, inline_status=True)

        cur = g.cur()
        if status:
            self.put(22, 1, status, self.col("item") | curses.A_BOLD)
        elif not cur.is_ai and g.stage_winner is None:
            o = g.players[1 - g.turn]
            ctl = f"[1-8] item   [S] shoot yourself   [O] shoot {o.name[:12]}   [?] help   [Q] quit"
            self.put(22, 1, ctl[:78], curses.A_BOLD)
        if self.msg:
            self.put(23, 1, self.msg[:78], self.col("item"))
        self.scr.refresh()

    # ── animations
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

    def think(self, g, worker, min_time):
        self.thinking = True
        start = time.time()
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        k = 0
        who = g.cur().name
        suffix = " (asking Gemini)" if worker else ""
        while True:
            done = worker is None or not worker.is_alive()
            if done and time.time() - start >= min_time:
                break
            self.draw_board(g, status=f"{frames[k % len(frames)]} {who} is thinking...{suffix}")
            k += 1
            time.sleep(0.08)
        self.thinking = False

    # ── dialogs
    def banner(self, g, title, lines, ck):
        self.draw_board(g)
        c = self.col(ck)
        body = [(title, c | curses.A_BOLD), ""] + [l for l in lines if l] + ["", ("press any key", curses.A_DIM)]
        self.popup(body, battr=c)
        self.wait_key()

    def confirm(self, g, text):
        self.draw_board(g)
        self.popup([text, "", "[Y] yes    [N] no"])
        while True:
            k = self.wait_key().lower()
            if k == "y":
                return True
            if k in ("n", "\x1b"):
                return False

    def choose(self, g, title, options):
        self.draw_board(g)
        rows = [(title, curses.A_BOLD), ""]
        rows += [f"[{k + 1}] {ITEMS[o][0]:<9}{ITEMS[o][1]}" for k, o in enumerate(options)]
        rows += ["", ("[Esc] cancel", curses.A_DIM)]
        self.popup(rows, align="left")
        while True:
            k = self.wait_key()
            if k == "\x1b":
                return None
            if len(k) == 1 and k.isdigit() and 1 <= int(k) <= len(options):
                return options[int(k) - 1]

    def help(self, g=None):
        if g:
            self.draw_board(g)
        else:
            self.frame()
        self.popup(help_lines(), align="left")
        self.wait_key()

    def handover(self, g):
        p = g.cur()
        if self.frame():
            self.popup([(f"{p.name.upper()}'S TURN", self.col("item") | curses.A_BOLD), "",
                        "Pass the keyboard. Everyone else looks away.", "", ("press any key", curses.A_DIM)])
        self.wait_key()

    def ask_double(self, g):
        self.draw_board(g)
        self.popup([("DOUBLE OR NOTHING?", self.col("item") | curses.A_BOLD), "",
                    f"Bank {g.score} points now, or face stage {g.stage + 1}.",
                    "Clear it and your score doubles. Die and you lose it all.", "",
                    "[C] cash out     [D] double or nothing"])
        while True:
            k = self.wait_key().lower()
            if k == "c":
                return "cash"
            if k == "d":
                return "double"

    def text_input(self, prompt, default, maxlen=12):
        buf = ""
        curses.flushinp()
        while True:
            if self.frame():
                hint = f"Enter = {default if not buf else 'done'}   Esc = back"
                top, left, iw = self.popup([(prompt, curses.A_BOLD), "", "", "", (hint, curses.A_DIM)], width=36)
                self.put(top + 2, left + 2, "> " + buf, self.col("item") | curses.A_BOLD)
                self.put(top + 2, left + 4 + len(buf), "_", curses.A_BLINK)
                self.scr.refresh()
            k = self.getkey()
            if k == "\n":
                return buf.strip() or default
            if k == "\x1b":
                return None
            if k == "\b":
                buf = buf[:-1]
            elif len(k) == 1 and k.isascii() and k.isprintable() and len(buf) < maxlen:
                buf += k

    def menu(self, gem):
        opts = [("1", "Duel the Croupier: 3 stages"),
                ("2", "Duel the Croupier: endless, double or nothing"),
                ("3", "Hot-seat: 2 players, best of 3 stages"),
                ("4", "High scores"), ("5", "How to play"), ("q", "Quit")]
        while True:
            if self.frame():
                for k, line in enumerate(TITLE_ART):
                    self.put(2 + k, (W - len(line)) // 2, line, self.col("item") | curses.A_BOLD)
                tag = "a terminal duel of nerve, odds and one very loud gun"
                self.put(7, (W - len(tag)) // 2, tag, curses.A_DIM)
                for k, (key, label) in enumerate(opts):
                    self.put(9 + k, 18, f"[{key.upper()}]", self.col("item") | curses.A_BOLD)
                    self.put(9 + k, 23, label)
                st = gem.status()
                self.put(16, (W - len(st)) // 2, st, self.col("hp") if gem.key else curses.A_DIM)
                for k, line in enumerate(GUN):
                    self.put(18 + k, 18, line, curses.A_DIM)
                self.scr.refresh()
            k = self.getkey().lower()
            if k in ("1", "2", "3", "4", "5"):
                return k
            if k in ("q", "\x1b"):
                return "q"

    def pick_difficulty(self):
        if self.frame():
            self.popup([("CHOOSE DIFFICULTY", curses.A_BOLD), "",
                        "[1] Easy    more charges and items, a reckless dealer",
                        "[2] Normal  the house as intended",
                        "[3] Hard    fewer charges, no shell counter, a sharp dealer",
                        "", ("[Esc] back", curses.A_DIM)], align="left")
        while True:
            k = self.wait_key().lower()
            if k in ("1", "2", "3"):
                return ["easy", "normal", "hard"][int(k) - 1]
            if k in ("\x1b", "q"):
                return None

    def scores_screen(self):
        data = load_scores()
        if self.frame():
            self.put(1, (W - 11) // 2, "HIGH SCORES", self.col("item") | curses.A_BOLD)
            for c, mode in enumerate(("classic", "endless")):
                x = 4 + c * 38
                self.put(3, x, "3 STAGES" if mode == "classic" else "ENDLESS", curses.A_BOLD)
                y = 5
                for diff in ("easy", "normal", "hard"):
                    self.put(y, x, diff.upper(), self.col("item"))
                    y += 1
                    entries = data.get(f"{mode}:{diff}", [])[:4]
                    if not entries:
                        self.put(y, x + 2, "no scores yet", curses.A_DIM)
                        y += 1
                    for e in entries:
                        row = f"{e.get('score', 0):>7}  {str(e.get('name', ''))[:10]:<10} {e.get('date', '')}"
                        self.put(y, x + 2, row[:34])
                        y += 1
                    y += 1
            self.put(23, (W - 13) // 2, "press any key", curses.A_DIM)
            self.scr.refresh()
        self.wait_key()


# ───────────────────────────── game flow ─────────────────────────────
def short_err(e):
    return (str(e) or e.__class__.__name__)[:70]


def decide(ui, g, i, gem, step, force_shot=False):
    if force_shot:
        return heuristic_decision(g, i, allow_items=False)
    if gem.enabled:
        w = Worker(lambda: gem.decide(g, i, step))
        w.start()
        ui.think(g, w, 0.5)
        if w.error is None:
            d = validate_decision(g, i, w.result)
            if d:
                gem.failures = 0
                return d
        else:
            ui.msg = gem.note_failure(short_err(w.error))
    else:
        ui.think(g, None, 0.6 + random.random() * 0.6)
    d = heuristic_decision(g, i, g.cfg["sloppy"])
    if random.random() < 0.3:
        d["taunt"] = random.choice(TAUNTS)
    return d


def ai_turn(ui, g, gem):
    i = g.turn
    for step in range(12):
        if g.stage_winner is not None or g.turn != i or g.needs_reload:
            break
        d = decide(ui, g, i, gem, step, force_shot=(step == 11))
        if d.get("taunt"):
            ui.speech = d["taunt"]
        if d["action"] == "use_item":
            ok, _, ev = g.use_item(i, d["item"], d.get("steal"))
            if ok:
                ui.play_events(g, ev)
                continue
            d = heuristic_decision(g, i, allow_items=False)
        ui.play_events(g, g.shoot(i, d["action"] == "shoot_self"))
        break
    curses.flushinp()


def human_action(ui, g):
    i = g.turn
    p = g.players[i]
    ui.draw_board(g)
    k = ui.getkey()
    ui.msg = ""
    if k in ("RESIZE", ""):
        return None
    kl = k.lower()
    if kl == "q":
        if ui.confirm(g, "Quit to the main menu? This run will be lost."):
            return "quit"
    elif kl in ("?", "h"):
        ui.help(g)
    elif kl == "s":
        ui.play_events(g, g.shoot(i, True))
    elif kl == "o":
        ui.play_events(g, g.shoot(i, False))
    elif len(kl) == 1 and kl in "12345678":
        n = int(kl) - 1
        if n >= len(p.items):
            ui.msg = "No item in that slot."
            return None
        it = p.items[n]
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


def stage_over(ui, g):
    """Handle the end of a stage. Returns True when the run/match is over."""
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

    if w == 1:
        if g.mode == "endless":
            lost, g.score = g.score, 0
            ui.banner(g, "YOU DIED", [f"Stage {g.stage}.",
                                      f"The house keeps all {lost} points." if lost else ""], "live")
        else:
            best = record_score("classic", g.diff, g.score, f"died in stage {g.stage}")
            ui.banner(g, "YOU DIED", [f"Stage {g.stage}. Score: {g.score}",
                                      "New high score!" if best else ""], "live")
        return True

    pts = g.award(1000 * g.stage)
    note = ""
    if g.double_pending:
        g.score *= 2
        g.double_pending = False
        note = "Double or nothing paid off: score doubled!"
    if g.mode == "classic" and g.stage >= 3:
        g.award(2000)
        best = record_score("classic", g.diff, g.score, "beat the house")
        ui.banner(g, "YOU BEAT THE HOUSE", [note, f"Final score: {g.score}",
                                            "New high score!" if best else ""], "hp")
        return True
    ui.banner(g, f"STAGE {g.stage} CLEARED", [f"+{pts} points. {note}".strip(), f"Score: {g.score}"], "hp")
    if g.mode == "endless":
        if ui.ask_double(g) == "cash":
            best = record_score("endless", g.diff, g.score, f"cashed out after stage {g.stage}")
            ui.banner(g, "CASHED OUT", [f"You walk away with {g.score} points.",
                                        "New high score!" if best else ""], "item")
            return True
        g.double_pending = True
    return False


def run_game(ui, gem, mode, diff):
    if mode == "hotseat":
        n1 = ui.text_input("PLAYER 1 NAME", "Player 1")
        if n1 is None:
            return
        n2 = ui.text_input("PLAYER 2 NAME", "Player 2")
        if n2 is None:
            return
        g = Game(mode, diff, [n1, n2], vs_ai=False)
    else:
        g = Game(mode, diff, ["You", "The Croupier"], vs_ai=True)
    gem.reset()
    ui.new_game()
    ui.play_events(g, g.start_stage())
    last = None
    while True:
        if g.stage_winner is not None:
            if stage_over(ui, g):
                return
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
            ai_turn(ui, g, gem)
        elif human_action(ui, g) == "quit":
            return


def main(scr, offline=False):
    ui = UI(scr)
    gem = GeminiDealer(offline)
    ui.gem = gem
    while True:
        choice = ui.menu(gem)
        if choice == "q":
            return
        if choice == "4":
            ui.scores_screen()
            continue
        if choice == "5":
            ui.help()
            continue
        diff = ui.pick_difficulty()
        if not diff:
            continue
        run_game(ui, gem, {"1": "classic", "2": "endless", "3": "hotseat"}[choice], diff)


if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(main, "--offline" in sys.argv)
    except KeyboardInterrupt:
        pass
