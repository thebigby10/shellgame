# SHELL GAME

*A terminal duel of nerve, odds and one very loud gun.*

Shell Game is a turn-based terminal game for macOS, inspired by Buckshot Roulette. A shotgun is loaded with a known mix of live and blank shells in a hidden order. You and your opponent take turns using items and deciding who to shoot: them, or yourself. Opponents are dealers with their own personalities, strategies and house rules. An AI model (Google Gemini or SleepyAI) can optionally play them.

It's a single Python file with no dependencies beyond the standard library.

**Current version: 3.6** (Step 7 of the roadmap). See the [version history](#version-history) and [more to come](#more-to-come).

---

## Contents

- [Requirements](#requirements)
- [Running the game](#running-the-game)
- [How to play](#how-to-play)
- [Controls](#controls)
- [Game modes](#game-modes)
- [The dealers](#the-dealers)
- [Items](#items)
- [Table events](#table-events)
- [Other rules](#other-rules)
- [Mutators, shop and perks](#mutators-shop-and-perks)
- [Scoring](#scoring)
- [Career and achievements](#career-and-achievements)
- [AI dealers](#ai-dealers)
- [Settings](#settings)
- [Self-test](#self-test)
- [Files](#files)
- [Known limitations](#known-limitations)
- [Version history](#version-history)
- [More to come](#more-to-come)

---

## Requirements

- macOS with Terminal.app or iTerm2. Other Unix terminals mostly work too, but the Keychain and sound features are macOS-only.
- Python 3.8 or newer. The `python3` that ships with Apple's Command Line Tools works.
- A terminal window of at least **100 columns × 30 rows**. If yours is smaller, the game tells you. Drag the window bigger or press **Cmd −** to shrink the font.
- A font with the box-drawing and symbol characters, such as Menlo or SF Mono. If item icons show up as boxes, switch fonts.

## Running the game

```bash
python3 shellgame.py               # play
python3 shellgame.py --offline     # ignore AI settings; dealers use built-in strategies
python3 shellgame.py --help        # usage
python3 shellgame.py --selftest    # simulate 2,000 games and check every rule
```

---

## How to play

1. Each load puts a **known mix** of LIVE and BLANK shells into the gun in a **hidden order**.
2. On your turn, use as many items as you like, then **shoot your opponent or yourself**.
   - **Live shell:** the target loses 1 charge, or 2 if the barrel is sawed off.
   - **Blank at yourself:** you keep your turn.
   - **Any other shot** ends your turn.
3. Lose every charge and you lose the stage.
4. When the gun is empty it's reloaded, and both players draw new items (8 max).

The **TABLE** panel shows:
- the chamber, with any shells you know about colored in
- what was loaded
- what has been spent
- how many of each are left (at most tables)
- the odds that the chambered shell is live

---

## Controls

| Key | Action |
|---|---|
| ← → / Tab | Move between your items and the action buttons |
| ↑ ↓ | Jump between the item grid and the action buttons |
| Enter / Space | Use the selected item or button |
| 1–8 | Quick-use the item in that slot |
| S | Shoot yourself |
| O | Shoot your opponent |
| C | Call the Liar's bluff, when he has given you a tip |
| ? | How to play |
| I | Item guide |
| Q / Esc | Leave the table and go back to the menu |

**The mouse works everywhere.** You can click menu entries, dealers, items, buttons and pop-up choices. Turn the mouse off in Settings if you want to select text in Terminal normally.

---

## Game modes

| Mode | Description |
|---|---|
| **Duel** | Pick one of six dealers and survive three stages. You can also click a dealer's portrait on the main menu. |
| **Gauntlet** | Endless. You face every dealer in turn (Accountant → Gambler → Liar → Magician → Twins → Croupier), stopping at a shop between stages. After each stage you can cash out or go double or nothing: clear the next stage and your score doubles; die and you lose it all. |
| **Daily challenge** | The date picks one of the six dealers and one mutator for everyone. Every reload is generated from the date, so all players get the same shells, table events and item draws. Shows today's and yesterday's best. |
| **Classic** | Only the five original items (Loupe, Rack, Saw, Shackles, Tonic), with no events, misfires, sudden death, tells, tilt, bluffs, house rules, mutators, draft or shot clock. Play against The Dealer or in hot-seat. |
| **Hot-seat** | Two people, one keyboard, best of three stages, with the full rules. A "pass the keyboard" screen appears between turns, and you get a privacy screen before secret reveals. |

---

## The dealers

| Dealer | Tier | Score × | Style | House rule | Tells |
|---|---|---|---|---|---|
| **The Accountant** | Easy | 1.0 | Always peeks before shooting, shoots only on good odds, wears a Vest, heals at once | **Audit:** use 3 items in one turn and he confiscates one of yours | Honest (about 75%) |
| **The Gambler** | Easy | 1.0 | Shoots himself on 50/50s, loves the Saw, Double, Dice and Pills | **High Roller:** once per stage, the next two shots are blind (no items, no counter) | Honest (about 80%) |
| **The Liar** | Medium | 1.5 | Rigged gifts, Slip, Shuffle, Ricochet, Muzzle, Hook | **Tips:** after each of his turns he tips you about the chambered shell. Press C to call his bluff | Faked (about 30%) |
| **The Magician** | Tricky | 1.75 | Shuffle, Slip, Flipper, Snapshot, Decoy, Hook, Rewind, Radio; plays on what he saw during his trick | **Sleight of Hand:** on his first turn of each load, a coin flip decides whether he swaps the next two shells. Your knowledge of both (Tarot readings included) is wiped; he knows both either way | Pure noise (50%) |
| **The Twins** (Vera & Vex) | Hard | 2.0 | Vera plays like the Accountant, Vex like the Gambler; they share one hand drawn from both pools | **Seat Swap:** one set of charges, and they swap seats after every turn. The header and portrait show who's in the seat | Vera honest (80%), Vex fake (25%) |
| **The Croupier** | Hard · Boss | 2.5 | Near-optimal play; uses every item | **House Edge:** he sees the first shell of every load. The shell counter is hidden at his table, and he never tilts | None |
| **The Dealer** | Classic | 1.0 | Plays sensibly with the five classic items | None | None |

- **The Croupier is locked** until you beat any dealer in a three-stage duel, or clear stage 3 of the Gauntlet.
- **The Twins are locked** until you beat the Croupier in a duel, or clear his stage in the Gauntlet. The Gauntlet and the Daily can seat any dealer, locked or not.
- **Tells:** when a new shell enters the chamber on your turn, the dealer may react. A sweating face means he thinks it's live; a smug face means blank. A line also appears under his items. How reliable this is depends on the dealer, as shown in the table.
- **Tilt:** hit a dealer twice in a row and he tilts. The Accountant turns reckless, the Gambler turns timid, the Liar's tips and tells turn honest, and the Magician's hands shake too much for his trick. He calms down as soon as he lands a hit on you.
- **Bickering:** the Twins don't tilt. Hit them twice in a row and the twin in the seat takes the blame and sits out; the other one plays every turn (shown as BICKERING · VEX PLAYS) until they land a hit on you, then the seat swap resumes.
- **Calling the bluff:** after the Liar's tip, press **C**. If he lied, he loses 1 charge and you score a bonus. If he told the truth, you lose 1 charge. The shell is revealed either way.

---

## Items

There are 25 items. You draw from all of them; each dealer draws from their own pool. A ★ marks the five items used in Classic mode.

| | Item | Category | Effect |
|---|---|---|---|
| ◎ | **Loupe** ★ | Information | Privately see the chambered shell. |
| ⇥ | **Rack** ★ | Gun | Eject the chambered shell without firing it. Everyone sees what it was. |
| ‡ | **Saw** ★ | Gun | Your next shot deals 2 damage. |
| ∞ | **Shackles** ★ | Control | Your opponent skips their next turn. |
| ♥ | **Tonic** ★ | Defense | +1 charge. Can't be used at full charge or in sudden death. |
| ⇅ | **Flipper** | Gun | Invert the chambered shell. The new value is announced to both players. |
| ♪ | **Radio** | Information | Privately learn one random future shell. |
| ↩ | **Hook** | Control | Steal an opponent's item (not a Hook or Charm) and use it immediately. |
| ◐ | **Pills** | Chaos | 50% chance of +2 charges, 50% chance of −1 charge (which can knock you out). |
| ▣ | **Snapshot** | Information | See every remaining shell for 2 seconds, then the picture fades. |
| ♠ | **Tarot** | Information | Learn how many of the next three shells are live. A memo on the table keeps count as they're fired. |
| ⇄ | **Shuffle** | Gun | Reshuffle the remaining shells. Everyone's knowledge of them is wiped. |
| ↧ | **Slip** | Gun | Insert a live or blank shell at a position you choose. Your opponent sees which kind, not where. |
| ¤ | **Decoy** | Deception | Gift your opponent a rigged item disguised as a normal one. It costs them 1 charge when used. |
| ‖ | **Double** | Gun | Your next shot fires two shells at the same target. |
| ⊘ | **Jammer** | Defense | If the next shell fired, by anyone, is live, it misfires harmlessly. |
| ↻ | **Ricochet** | Defense | The next shot your opponent aims at you bounces back at them. |
| ♦ | **Leech** | Chaos | If your next shot hits your opponent, you gain 1 charge. |
| ▦ | **Vest** | Defense | Absorbs the next 1 damage you take. |
| ♣ | **Charm** | Defense | Passive: the first lethal hit leaves you on 1 charge instead, and the Charm breaks. |
| × | **Muzzle** | Control | Your opponent can't use items on their next turn. |
| † | **Pact** | Chaos | Swap charge totals with your opponent. |
| ⚄ | **Dice** | Chaos | Roll a die. 1: lose a charge · 2: lose an item · 3: nothing · 4: see the chambered shell · 5: +1 charge · 6: shackle your opponent. |
| ⌐ | **Crowbar** | Control | Destroy one of your opponent's items. |
| ↺ | **Rewind** | Gun | Put the last shell that left the gun back in the chamber. Everyone knows its value. |

The in-game **Item guide** shows each item's full description, a tip on when to use it, and which dealers carry it.

---

## Table events

Each reload, except the very first one of a run, has a 55% chance of flipping one of 13 event cards. The event bends the rules until the next reload.

| Event | Effect |
|---|---|
| ● **Blackout** | The LEFT counter goes dark. |
| ² **Double Stakes** | Live shells deal +1 damage. |
| + **Generous House** | Everyone draws 2 extra items. |
| ∅ **Dry Table** | No items can be used. |
| ▲ **Hot Barrel** | The last shell is guaranteed live, and everyone knows it (unless someone shuffles). |
| ◷ **Rush Hour** | A 10-second shot clock runs on every human decision. |
| ☾ **Blood Moon** | Every hit on your opponent heals you 1 charge. |
| ≡ **Heavy Load** | Two extra shells, one live and one blank. |
| ░ **Fog** | Only the total number of shells is shown: the load, LOADED row, LEFT counter and odds hide the mix. The dealers can't count it either; the SPENT row, your reads and Tarot still work. |
| ⇆ **Swap Meet** | Each player hands the other a random item (skipped if there's nothing to give or no room). |
| * **Cold Feet** | A blank at yourself no longer gives you an extra turn. |
| 1 **Last Call** | Each player can use only one item this load (a Hooked item counts). |
| $ **Lucky Streak** | Each player's first blank at their own head earns them a random item. |

## Other rules

- **Misfires:** any live shell has a 5% chance to fizzle. Can be switched off.
- **Sudden death:** when both players are on 1 charge, healing stops for the rest of the stage. A Charm still works.
- **Shot clock:** optional, 20, 15 or 10 seconds per decision. If it runs out, you fire at a random target. Dialogs and help screens pause it.
- **Item draft:** optional. After each reload, items are laid face up and players take turns picking them instead of drawing at random.

---

## Mutators, shop and perks

### Mutators
Before any Duel or Gauntlet run, you can switch on any combination of these. Their multipliers stack onto your score.

| Mutator | Multiplier | Effect |
|---|---|---|
| No Healing | ×1.5 | Nothing heals anyone. |
| Dealer's Eye | ×2 | The dealer sees the first shell of every load. |
| Lights Out | ×1.5 | The LEFT counter is always off. |
| Glass Cannon | ×1.5 | Live shells deal +1 damage, for both players. |
| Empty Pockets | ×2 | You draw 1 fewer item every load. |

### The House Shop (Gauntlet only)
After each cleared stage you can spend points on four items, which you'll hold at the start of the next stage, and on perks that last the rest of the run. Every point you spend is one you can't bank.

| Perk | Cost | Effect |
|---|---|---|
| Thick Skin | 2000 | +1 max charge (can buy twice) |
| Deep Pockets | 2500 | +1 item every load (can buy twice) |
| Keen Eye | 3000 | You see the first shell of every load |
| Iron Vest | 1500 | Start every stage wearing a Vest |
| Card Counter | 1500 | Your LEFT counter always works |
| Sixth Sense | 1200 | Dealer tells show up twice as often |

---

## Scoring

All points are multiplied by the dealer's score multiplier and by any active mutators.

| Action | Points |
|---|---|
| Live hit on the dealer | 100 per charge of damage |
| Blank to your own head | 150 |
| Catching the Liar lying | 250 |
| Clearing a stage | 1000 × the stage number |
| Winning a duel | +2000 |
| Gauntlet double or nothing | Your score doubles when you clear the next stage, or drops to 0 if you die |

---

## Career and achievements

The **Career** screen on the main menu has three tabs:

- **Stats:** runs, wins, stages, best score, best Gauntlet run, shots and hit rate, damage dealt and taken, bluffs called and caught, dealers tilted, hot-seat matches, your win rate against each dealer, and your five most-used items.
- **Achievements:** all 34, in two columns, showing unlock dates and your progress where that applies.
- **High scores:** a 3×3 grid of tables: each of the six dealers, the Gauntlet, today's Daily and Classic.

Only finished runs count, whether you win, die or cash out. Quitting to the menu mid-run doesn't count.

| Achievement | How to unlock |
|---|---|
| First Blood | Win your first duel |
| Cooked the Books | Beat the Accountant in a duel |
| House Money | Beat the Gambler in a duel |
| Lie Detector | Beat the Liar in a duel |
| Breaking the Bank | Beat the Croupier in a duel |
| Trick or Treat | Beat the Magician in a duel |
| Seeing Double | Beat the Twins in a duel |
| Full House | Beat all six dealers in duels |
| Old School | Win a Classic duel |
| Daily Grind | Win a Daily challenge |
| Iron Will | Clear 5 stages in one Gauntlet run |
| Unbreakable | Clear 10 stages in one Gauntlet run |
| Masochist | Win a run with 2 or more mutators on |
| High Roller | Reach 20,000 points in one run |
| By a Thread | Win a stage on your last charge |
| Untouchable | Win a stage without losing a charge |
| Bare Hands | Win a stage without using an item |
| Nerves of Steel | Three blanks to your own head in a row |
| Polygraph | Catch the Liar lying 3 times in one stage |
| Double Tap | Hit with both shells of a Double |
| Clean Cut | Knock out a dealer with a sawed-off shot |
| Return to Sender | A dealer's shot ricochets and knocks him out |
| Lucky Break | Your Charm saves you from a lethal hit |
| Gift Receipt | A dealer gets hurt by your rigged Decoy |
| Devil's Due | Sign a Pact and win that stage |
| Last Man Standing | Win a stage that went to sudden death |
| Storm Chaser | See all 13 table events (across finished runs) |
| Fog of War | Win a stage played under Fog |
| Dud | Survive a live shell to your own head thanks to a misfire |
| Clean Audit | Get audited by the Accountant and still win the stage |
| Tilt Master | Tilt dealers 10 times in total |
| Collector | Use all 24 usable items at least once |
| Trigger Happy | Fire 250 shots in total |
| Veteran | Finish 50 runs |

---

## AI dealers

By default, the dealers use built-in strategies that match their personalities. To let an AI model play them instead:

1. Open **Main menu → Settings → AI brain**.
2. Choose a **Provider**: Google Gemini or SleepyAI.
3. Select **API key** and paste your key with Cmd+V. It's stored in the **macOS Keychain** under the service name `shellgame`, never in a file.
4. Pick a **Model**. **Choose model from list** fetches the models your key can use. For SleepyAI, the model picker opens automatically after you save a key.
5. Run **Test connection** to check everything works.

| Provider | Default endpoint | Default model | Environment variable |
|---|---|---|---|
| Google Gemini | `generativelanguage.googleapis.com/v1beta` (fixed) | `gemini-3.8-flash` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| SleepyAI | `https://www.sleepyai.org/api/v1` (editable) | chosen from the list | `SLEEPYAI_API_KEY` |

How the AI plays:
- It makes one decision at a time and returns JSON. It's asked again after every item it uses.
- Each dealer has their own personality prompt, and each Twin has their own. A tilted dealer (or a bickering Twin) gets an extra instruction, and Classic mode uses a trimmed rules prompt.
- The Magician's trick is played by the game itself, not the AI; afterwards the AI sees both shells in its known shells. Under Fog the live/blank counts are left out of the AI's game state.
- Replies are validated. Anything invalid falls back to the built-in strategy for that decision.
- After 3 failed requests in a row, the built-in strategy takes over for the rest of the game.
- SleepyAI requests use `stream: false`, with a fallback that reads a streamed response if one comes back anyway. Gemini requests use JSON mode with a low thinking level (medium for the Croupier).
- Each AI decision is a separate request, usually 2–5 per dealer turn, and each one counts against your provider's usage limits.

---

## Settings

| Section | Option | Choices |
|---|---|---|
| AI brain | Provider, API key, Base URL, Model, Choose model from list, Test connection, Remove saved key | — |
| Game rules | Table events | On / Off |
| | Misfires | On / Off |
| | Shot clock | Off / 20 / 15 / 10 seconds |
| | Item draft | On / Off |
| Display & sound | Theme | Casino / Neon / Noir |
| | Sound | On / Off (built-in macOS system sounds) |
| | Animations | Normal / Fast / Turbo |
| | Mouse | On / Off |

The game-rule settings don't apply to Classic or the Daily challenge, which use fixed rules.

---

## Self-test

```bash
python3 shellgame.py --selftest              # 2,000 simulated games
python3 shellgame.py --selftest 5000 --seed 42
python3 shellgame.py --selftest-game 41234   # replay one game and print its full log
```

The self-test plays thousands of games without a real terminal, across every mode, dealer, item, table event and mutator. Both sides mix dealer strategies with random item use. After every action it checks the game's rules:
- charges and item limits
- that remembered shells still match the real gun
- that Tarot counts stay correct
- that no turn starts with an empty gun
- that Classic mode stays classic
- that every game ends
- that Last Call allows one item, Cold Feet never gives an extra turn and Heavy Load adds its two shells
- that under Fog the dealers never deduce a shell from the counts, and the counts never reach the AI state
- that Sleight of Hand happens at most once a load, wipes your reads and leaves the Magician knowing both shells
- that the Twins swap seats after every turn, never mid-turn, and that a bickering twin stays in the seat until they land a hit

It also:
- feeds malformed AI replies through the validator
- builds the AI prompt and state
- draws one game in ten, plus every Career tab, through the real UI on a fake screen
- reports how many achievements the simulated player unlocked, and which table events it saw

It never touches your settings, scores or stats files. If something breaks, it prints a seed you can replay with `--selftest-game`.

---

## Files

| File | Contents |
|---|---|
| `shellgame.py` | The whole game |
| `~/.shellgame_config.json` | Settings, AI provider and model, unlocked dealers (owner-only permissions) |
| `~/.shellgame_scores.json` | High-score tables |
| `~/.shellgame_stats.json` | Career stats and achievements |
| macOS Keychain → `shellgame` | API keys, one entry per provider |

---

## Known limitations

- When an API key is saved, it's briefly passed as an argument to macOS's `security` command. Other processes on the same Mac can see it during that moment.
- With the mouse on, selecting text in Terminal needs **Option-drag**. You can also turn the mouse off in Settings.
- Some symbol icons depend on your Terminal font.
- If you installed Python from python.org and see SSL errors when connecting to an AI, run **Install Certificates.command** from that Python's folder in Applications.
- Sound uses `afplay` and the built-in sounds in `/System/Library/Sounds`, so it's macOS only.

---

## Version history

### 3.6: New content *(Step 7)*
- **The Magician** (Tricky, ×1.75): Sleight of Hand, pure-noise tells, and his own portrait, prompt and strategy.
- **The Twins, Vera and Vex** (Hard, ×2, unlocked by beating the Croupier): shared charges, a seat swap after every turn, and bickering instead of tilt.
- **Six new table events** (13 in total): Heavy Load, Fog, Swap Meet, Cold Feet, Last Call and Lucky Streak.
- **Four new achievements** (34 in total), and Full House now needs all six dealers.
- Six-dealer main menu, dealer select, Gauntlet order and Daily; a compact per-dealer stats list, a 3×3 high-score grid and two columns of 17 achievements.
- The self-test covers the new dealers and events, and reports which table events it saw.

### 3.5: Career and achievements *(Step 6)*
- New **Career** screen replaces "High scores". It has three tabs: Stats, Achievements and High scores.
- **30 achievements**, unlocked at the end of a run with a banner. Progress is shown for cumulative ones.
- Lifetime stats are saved to `~/.shellgame_stats.json`.
- The self-test now covers stats and achievements, and draws every Career tab.

### 3.4: Self-test and Classic mode *(Step 5)*
- **`--selftest`**: a headless simulator with rule checks after every action, AI-reply fuzzing, drawing on a fake screen and replayable seeds (`--selftest-game`).
- **Classic mode**: the five original items and no extra rules, against **The Dealer** (a new plain opponent) or in hot-seat. It has its own high-score table and a trimmed AI prompt.
- The 3–4 player hot-seat was dropped from the roadmap.

### 3.3: Progression *(Step 4)*
- **Item draft**: an optional face-up pick after each reload.
- **Gauntlet shop**: buy items and perks between stages.
- **Mutators**: five opt-in run modifiers whose multipliers stack onto your score.
- **Daily challenge**: date-seeded dealer, mutator, shells, events and draws.

### 3.2: Reading the dealer *(Step 3)*
- **Calling the bluff** on the Liar's tips.
- **Tells**: sweating and smug faces, with a different reliability for each dealer.
- **Tilt**: two hits in a row flip a dealer's play style.
- **House rules**: Audit, High Roller, Tips and House Edge.

### 3.1: The table *(Step 2)*
- Seven **table events**, the **shot clock**, **sudden death** and **misfires**.
- A new **Game rules** section in Settings.

### 3.0: UI upgrade and 16 new items *(Step 1)*
- Items grow from 9 to **25**: Snapshot, Tarot, Shuffle, Slip, Decoy, Double, Jammer, Ricochet, Leech, Vest, Charm, Muzzle, Pact, Dice, Crowbar and Rewind.
- **Themes** (Casino, Neon, Noir), **sound**, **animation speed** and a **mouse toggle**.
- Item icons, status badges, a screen shake on hits, a stage wipe, an animated title screen, multi-shell shot animations, and a scrollable Item guide with categories.

### 2.1: SleepyAI
- SleepyAI replaces the general OpenAI-compatible providers (OpenAI, OpenRouter, Ollama, Custom).
- Requests use `stream: false` with a fallback for streamed replies, friendly messages for SleepyAI's error codes, and model listing that copes with different reply formats.

### 2.0: Dealers, a proper TUI and AI settings
- A full **curses TUI** at 100×30, with bordered panels, arrow-key menus, mouse support, an INFO panel describing whatever is selected, and an **Item guide**.
- **Four dealers** with their own personalities, prompts, strategies, item pools and stakes replace the three difficulty levels. The Croupier is unlockable.
- **Settings screen** for AI providers: Gemini and OpenAI-compatible APIs with an editable base URL, keys stored in the macOS Keychain, a model picker and a connection test.

### 1.0: First release
- Terminal game at 80×24 with a Gemini-powered dealer and a built-in fallback.
- 9 items, 3 difficulty levels, a 3-stage mode, an endless double-or-nothing mode, 2-player hot-seat, ASCII art and animations, and high scores.

---

## More to come

None of this is built yet. The steps are ordered so each one makes room for the next.

### Step 8: Room to grow
The screens are full. The main menu uses all ten number keys, the dealer row fits exactly six portraits, the high-score grid has nine slots for nine tables, and the 34 achievements fill both columns. Before any more content goes in:
- **Play submenu.** Duel, Gauntlet, Daily, Classic and Hot-seat move under one **Play** entry, which frees five main-menu slots.
- **Paged achievements.** The Achievements tab shows 34 per page, and the detail box stays where it is.
- **Scrolling dealers and tables.** Use ←→ to scroll past six dealers on the main menu and past nine tables on the High scores tab.

### Step 9: Runs that last
- **Resume a run.** Quitting to the menu mid-run throws the run away today. Instead, it's saved to `~/.shellgame_run.json` (one slot) and **Continue** appears at the top of the menu. The save holds the whole table (charges, items, the gun and the score). It's deleted the moment the run resumes, so reloading can't undo a bad shot.
- **Daily streaks.** The Daily screen shows only today's and yesterday's best. It will also show how many days in a row you've won, with your best streak under Career → Stats and two achievements (3 and 7 days).
- **Weekly challenge.** Seeded by the week, the way the Daily is seeded by the date: a 5-stage Gauntlet with a fixed dealer order, two mutators and the shop, plus its own high-score table.

### Step 10: The Bookie
A seventh dealer (Medium, ×1.5), unlocked by winning 3 Daily challenges.
- **House rule: Odds board.** Before each load he posts odds on the first shell, priced from the true mix minus a house margin. You can stake up to 500 points on live or blank.
- **Tells:** honest but rare. The board itself is a free hint, but because of the margin, a bet only pays off when you know more than the mix.
- **Style:** plays by expected value, saws only when the odds favor live, and hedges with the Vest and Jammer.
- He gets his own portrait, prompt, strategy, duel high-score table and a "beat the Bookie" achievement. Full House then needs all seven dealers.

### Step 11: New items and events
- **Wiretap.** Hear the dealer's plan for his next turn: whether he means to shoot you or himself. It's the first item that reads the opponent instead of the gun. It isn't drawn in hot-seat.
- **Insurance.** If you die this stage, you keep half your score instead of nothing. Sold in the Gauntlet shop only.
- **Blindfold.** Your opponent plays their next turn with no LEFT counter. Dealers lose the live/blank counts the same way they do under Fog.
- **Two table events** (15 in total): **Mirror Match** (both players draw the same items this load) and **Short Straw** (the first shot of the load must be at yourself).
- New achievements for the new items and events, which the paged Achievements tab from Step 8 has room for.
- As in earlier steps, the self-test covers every new dealer, item and event.

### Fixes and polish
- **API key off the command line.** Keys are saved by sending the command to `security -i` on standard input, so they never show up in the process list (see [Known limitations](#known-limitations)).
- **Fewer AI requests.** The dealer plans his whole turn in one reply and is asked again only when an item tells him something new (Loupe, Radio, Tarot, Snapshot). That cuts the usual 2–5 requests per turn to 1–2.
- **Tutorial table.** A scripted first duel against the Dealer, with a fixed gun, that teaches the counter, shooting yourself on a blank and the five Classic items one step at a time. It's offered on first launch.
- **Run recap.** After every finished run, one screen sums it up: shots, hit rate, damage, items used and achievements unlocked, taken from the stats the run already tracks.
- **Linux.** Keys in the Secret Service via `secret-tool` (or environment variables only), and sound via `paplay` or the terminal bell.

### Not planned
- **3–4 player hot-seat.** Dropped; hot-seat stays two players.
- **Online play.** It would need a server and libraries outside the standard library. The game stays one file with no dependencies.
