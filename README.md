# TALOS — The Living Chess Studio

A modern, fully local chess playing, training and *land-building* suite,
inspired by [Lucas Chess](https://github.com/lukasmonk/lucaschess) and advanced
in every direction — plus **Battle Chess** as a feature: capture a piece and a
procedurally generated 3D fight plays out, ending with the loser losing its
head, being flattened, or shattering into simulated debris.

Everything runs on your machine. No accounts, no servers, no telemetry.

```
python run.py
```

---

## Four editions, one codebase

| Edition | How you get it | Notes |
|---|---|---|
| **Browser** | open the [Pages site](https://github.com/Mylittlestories/talos) → *Play in your browser*, or serve `web/` locally | nothing to install; works offline after the first visit |
| **Android** | open the site in Chrome → **Add to Home Screen** | a real full-screen app icon, no APK, no store |
| **Windows** | `TALOS-<version>-windows-x86_64.zip` from the release, or the Inno Setup installer | `.pgn` association, portable zip, no admin rights needed |
| **Linux** | `TALOS-<version>-linux-x86_64.tar.gz` → `./install.sh` | installs into `~/.local`, ships `.desktop` + AppStream metadata |

Every edition runs **the same Python modules**. The browser and Android
editions execute them under [Pyodide](https://pyodide.org) in a Web Worker; the
desktop editions run them on CPython. There is no "web version" of the engine —
`web/python/lc/core/engine.py` is a byte-for-byte copy of `lc/core/engine.py`,
re-copied by `tools/build_web.py` on every build.

The only desktop-only feature is Battle Chess mode, because it needs real-time
OpenGL. Everything else — the engine and its 12 levels, the puzzle sets, the
learning coach, Anarchchess, Anarchess — is identical everywhere.

To try the browser edition straight from a clone:

```bash
python tools/build_web.py          # writes web/python/, web/data/, web/icons/
python -m http.server 8080 --directory web
# -> http://localhost:8080
```

---

## What is in the box

### Play
* **Standard chess + 12 variants**: Chess960, Crazyhouse (with piece pockets
  and drops), Atomic, King of the Hill, Three-check, Horde, Racing Kings,
  Antichess, Giveaway, Suicide — plus the two TALOS originals below.
* **Human vs engine, human vs human, engine vs engine**, any combination,
  any colour.
* **12 strength levels** (800 → 2250 Elo) and **7 personalities**
  (Balanced, Aggressive, Defensive, Positional, Tactical, Solid, Wild).
  Weak levels are genuinely weak *and* human-like: they blunder, they make
  small inaccuracies, and they see the board through their own bias.
* **Any UCI engine** (Stockfish, Lc0, …) with its own time budget, depth,
  `Skill Level` or `UCI_Elo` cap. One-click Stockfish installer is built in
  (`Engines ▸ Install Stockfish`); engines already on your `PATH` are found
  automatically.
* **Clocks**: presets from 1 min to 30+20, fixed seconds per move, or
  unlimited, with increment, move counter, low-time ticks and flag detection.

### Anarchchess — the house rules, as a real playable variant
The rules the community actually plays, collected from r/AnarchyChess and the
Anarchchess bots, each one a switch you can turn off
(`Anarchy ▸ Choose the rules…`).

| Rule | What happens |
|---|---|
| En passant is forced | If it is on the table you must take it |
| Knooks | Move a knight onto a friendly rook and they fuse: rook *and* knight powers in one piece (drawn with an amber badge) |
| c4 is explosive | The first piece to land on c4 detonates and kills a one-square ring — rooks and knooks shrug it off |
| Double check wins | Give a double check and the game is over |
| The king cannot go to c2 | On either side of the board |
| Il Vaticano | Two friendly bishops three squares apart on a diagonal swap places and take everything between them |
| Siberian Swipe | An unmoved rook takes the enemy rook across the board on the same file |
| Vertical castling | King and rook trade places along their file |
| Knight boost | Promoting to a knight earns an immediate extra move |
| Dismount | A knight that has just moved may become a pawn |
| Radioactive queen decay | Taking a queen irradiates the square: the neighbours die too |
| *Full anarchy adds:* | the omnipotent pawn, promotion roulette, the hyper-accelerated Bongcloud win, and random events every turn |

Two presets ship ready: **Anarchchess** (the eleven famous rules) and
**Full anarchy** (everything, including the chaos). The built-in engine plays
both — it only ever asks python-chess what is legal, so a new rule needs no
engine changes.

### Anarchess — the land before Chess
A reconstruction of **Anarchess** by Dimitris Grammenos (FORTH), from the
components and the scoring rules described by its author.

Chess-land before the White and Black kingdoms, when the "pawns" were free
entities. Two to four players share 32 light and 32 dark tiles and grow a
landscape:

1. **Lay a tile** next to the land, choosing its colour (or drawing one blind,
   if you prefer the bag).
2. **Then, optionally, one pawn action**: settle a new pawn, step one square,
   or attack a neighbour.

When the last tile is laid the game ends and every **area of two or more
same-coloured tiles** scores for whoever has the most pawns in it.
8 pawns each with two players, 6 with three, 5 with four.

The rules that the published sources leave open are listed in the app
(`Anarchy ▸ Anarchess`) as eight numbered reconstruction decisions, and most of
them are switches: the bag versus the colour choice, whether an attack needs a
supporting pawn, whether captives return, whether the last tile ends the game,
and whether an area scores per tile or as a whole.

### Analysis
* Continuous analysis with a vertical evaluation bar, MultiPV candidate
  lines (click a line to see it on the board) and an evaluation graph.
* Three-step graded hints: the target square, then the piece, then the move.
* **Analyse the whole game**: every move gets an evaluation, a centipawn-loss
  figure and PGN NAGs (`?`, `??`, `!!`), so blunders stand out in the move
  list and in the exported PGN.
* Right-drag to draw arrows, right-click to mark squares, `Esc` to clear.

### Training — 14 modes on real Lucas Chess data
The importer converts the original Lucas Chess data files (tactics, mates,
endgames, STS, 40H openings, game database) into one SQLite file:
**112,198 puzzles in 182 sets, 10,000 games, 6,633 openings — 24 MB**.

| Mode | What you do |
|---|---|
| Tactics & mates | Play the solution line; the opponent answers from the line |
| Strategy (STS) | Find the best move — scored in points, like the real STS |
| Endgame technique | Win real endgame positions against the engine |
| Guess the move | Reproduce the move played in a master game (BMT/albums) |
| Openings | Play moves that master practice knows, with frequency stats |
| Everest | Climb a ladder of positions taken from real games |
| Resistance | Survive; the engine gets stronger the longer you last |
| Your Elo | Play a game, get a rating estimate from your centipawn loss |
| Blindfold | The board hides after a few moves |
| Turn on the lights | Memorise highlighted squares, then click them back |
| Routes | Guide a piece to a square in as few moves as possible |
| Square colours | Name the colour of a square, against the clock |

### The learning coach
Every drill you answer is remembered (`Train ▸ Learning coach…`, `Ctrl+J`).

* **Spaced repetition (SM-2)** moves each puzzle to the day you are about to
  forget it: right answers stretch the interval, quick answers stretch it
  further, hints shrink it, and a card that keeps slipping is flagged and
  pushed back to the front of the queue.
* **A rating per theme** — tactics, mates, endgames, strategy, openings,
  calculation, visualisation, memory — updated against the difficulty of
  whatever you just attempted, so missing a mate in one costs more than
  missing a mate in four.
* **A plan, not a to-do list**: `Review what is due` builds a session out of
  exactly the cards whose day has come; `Train my weakest theme` opens the
  mode that matches your lowest bar.
* Mastery bars, a seven-day forecast, recent accuracy and one sentence of
  advice, all stored in your own database.

### Database & PGN
* Save/load games to the built-in database, import and export PGN,
  replay any game by clicking the move list.
* **Master game database**: 10,000 real games, browsable and replayable.
* **Opening explorer**: for the current position, the moves played in the
  database with frequency, score and average Elo.

### Battle Chess mode
`Battle ▸ Battle Chess` (or `Ctrl+B`) swaps the flat board for a real-time 3D
board:

* Pieces are generated procedurally (surfaces of revolution + primitives) —
  no art assets, no downloads.
* The attacker's choreography depends on the piece: the pawn stabs, the knight
  slashes, the bishop fires a beam, the rook smashes down, the queen unleashes
  a shockwave, the king hammers.
* **The victim dies its own death**, decided by who it is and who killed it:
  **kings are beheaded** (the head tumbles off, spins and lands), **pawns are
  knocked over** like skittles, the rook **flattens** its target into a
  pancake that crumbles, the pawn **impales** and throws, the bishop
  **disintegrates** its victim into ash, the queen blows it apart.
* **Blood, at the level you choose.** `Battle ▸ Gore ▸ Classic` is the 1988
  tone: stylised spray that stains the board, pooling decals that spread and
  dry, and the odd severed limb bouncing across the squares. `Arcade`
  replaces every drop with dust and sparks and keeps the choreography.
* Captured pieces also **shatter into rigid-body shards** that fly, spin,
  bounce and settle — gravity, restitution and spin damping included.
* Knights hop, castling moves both pieces, promotions burst into sparks.
* Orbit/zoom with the mouse, three camera presets, quality setting
  (Low → Ultra) that rebuilds the meshes at a different tessellation.
* The 2D board stays in charge of the rules: the 3D view mirrors it, so
  every mode (training, analysis, variants) works in Battle mode too.

---

## The built-in engine

A from-scratch alpha-beta engine: tapered evaluation, piece-square tables,
null-move pruning with verification, late-move reductions, futility and
reverse-futility pruning, late-move pruning, SEE-ordered captures, killer and
history heuristics, a transposition table, quiescence search with SEE and
check evasions, and multi-threaded root splitting.

Tuning is measured, not guessed. `tools/bench.py` scores the engine against
real Lucas puzzles:

| stage | solved (150 puzzles, 400 ms/move) |
|---|---|
| before the ablation study | 88 (58.7%) |
| **shipped** | **109–110 (72.7–73.3%)** |

The single biggest win came from a leave-one-out ablation over every pruning
heuristic, which showed **razoring was costing 22 puzzles** — a static
evaluation far below alpha is exactly what a sacrifice looks like — so it is
off by default. Re-run the study with `python tools/bench.py --count 150`.

---

## Install (desktop)

```bash
git clone <this repo> talos && cd talos
python3 -m pip install -r requirements.txt
python run.py
```

Requirements: Python 3.9+, PyQt6, python-chess, PyOpenGL (for Battle mode).
On Linux you may also need the Qt runtime libraries — `tools/setup_env.sh`
installs them on Debian/Ubuntu.

### Build the installers

```bash
python -m pip install pyinstaller
pyinstaller packaging/talos.spec --noconfirm --distpath dist
```

* **Windows** — `packaging/windows-installer.iss` (Inno Setup) wraps
  `dist/talos` into a proper installer.
* **Linux** — `dist/talos` plus `packaging/linux-install.sh`, which copies the
  build into `~/.local`, installs `packaging/talos.desktop` and the AppStream
  file `packaging/talos.metainfo.xml`.
* **macOS** — the same spec produces `dist/TALOS.app`.

`packaging/README.md` has the full recipe for all three.

### Build the browser (and Android) edition

```bash
python tools/build_web.py     # Python core, vendored python-chess, puzzles, icons
python tools/web_smoke.mjs    # needs: npm install pyodide@0.27.7
```

The result in `web/` is a plain static site: upload it anywhere, or open it from
a file server. Add it to a phone's home screen and it is the Android edition.

### Build the presentation

```bash
python tools/make_deck.py     # -> presentation/index.html (self-contained)
```

One file, no internet needed. `←`/`→` to move, `O` for the overview, `F` for
fullscreen, `P` to print. Every number in it is generated from the source, so
it cannot drift from the code.

## Releases

Push a `v*` tag and GitHub Actions does the rest:

* three build jobs produce the Windows zip, the Linux tarball and the macOS
  app zip, a fourth zips the browser edition for self-hosting;
* the release notes are lifted out of `CHANGELOG.md` for that version
  (`tools/release_notes.py`);
* `SHA256SUMS.txt` is generated;
* a **draft** release is opened with everything attached — nothing is public
  until somebody reads it and presses publish;
* the Pages site is rebuilt: the presentation at `/`, the playable app at
  `/web/`.

Check a downloaded bundle with `sha256sum -c SHA256SUMS.txt`.

```
lucaschess/
├── run.py                 launcher
├── requirements.txt
├── data/lucas.db          imported Lucas Chess content (24 MB, ships ready)
├── engines/               drop your UCI engines here (or use the installer)
├── web/                   the browser + Android edition (static site)
│   ├── index.html         play / train / anarchess / rules
│   ├── js/                board, worker, engine wrapper, views
│   ├── python_src/bridge.py   the only web-specific Python file
│   ├── python/            generated: the real core + vendored python-chess
│   └── icons/             generated from assets/ by build_web.py
├── presentation/index.html    the deck (generated by tools/make_deck.py)
├── packaging/             PyInstaller spec, .desktop, AppStream, installers
├── tools/
│   ├── build_web.py       builds web/ from the real modules
│   ├── web_smoke.mjs      boots the payload in Pyodide and plays it
│   ├── make_deck.py       builds the presentation
│   ├── make_icon.py       builds the icon set in assets/
│   ├── release_notes.py   lifts one version out of CHANGELOG.md
│   ├── selftest.py        100 headless checks
│   └── bench.py           engine benchmark / ablation harness
└── lc/
    ├── core/              engine, UCI driver, game model, players, clocks
    │   ├── engine.py      the built-in alpha-beta engine (all variants)
    │   ├── uci.py         UCI client (Stockfish & friends)
    │   ├── players.py     player abstraction + levels and personalities
    │   └── game.py        board, clocks, variants, PGN
    ├── variants/          Anarchchess: the house rules as a board class
    ├── anarchess/         Anarchess: rules, bot, board widget
    ├── ui/                Qt widgets: board, panels, dialogs, theme, sounds
    ├── battle/            3D Battle Chess: meshes, physics, choreography, gore
    ├── training/          14 training sessions, panel and the learning model
    └── data/              importer, Stockfish installer, opening explorer
```

## Keyboard

| Key | Action |
|---|---|
| `Ctrl+N` / `Ctrl+Shift+N` | New game / repeat last settings |
| `Ctrl+Z` | Takeback (your move and the reply) |
| `Ctrl+R` | Resign |
| `Ctrl+H` | Hint (three grades) |
| `Ctrl+B` | Toggle Battle Chess 3D |
| `Ctrl+A` | Analyse the whole game |
| `Ctrl+J` | Learning coach |
| `Ctrl+Shift+A` | Anarchess |
| `Ctrl+S` / `Ctrl+O` / `Ctrl+E` | Save / import / export PGN |
| `F` | Flip the board |
| `Esc` | Stop training, clear arrows |
| right-drag / right-click | Draw arrows / mark squares |

## Data provenance and licence

* The training content is imported from the **Lucas Chess** project by
  Lukas Monk (GPLv2 or later). `lc/data/importer.py` rebuilds
  `data/lucas.db` from a checkout of that repository:
  `python -m lc.data.importer ~/lucaschess`.
* **Anarchess** is a game by **Dimitris Grammenos** (Institute of Computer
  Science, FORTH). This is an independent reconstruction made from the
  publicly described components and scoring rules; the eight open questions
  are documented as reconstruction decisions inside the app rather than
  presented as the published rules.
* TALOS itself is released under the **GNU GPL v2 or later**, in the same
  spirit as the project that inspired it.
* All graphics in this build are drawn procedurally at runtime (Qt vector
  paths for the 2D pieces, generated meshes for the 3D pieces, inline SVG for
  the icons) and all sound effects are synthesised — no third-party art or
  audio is bundled.

## Notes and troubleshooting

* **Battle mode says 3D is unavailable** – install PyOpenGL
  (`pip install PyOpenGL`) and make sure OpenGL works on your machine. The
  game keeps every feature in 2D if it cannot start.
* **No sound** – the sound bank disables itself when the machine has no audio
  output device (this avoids multi-second stalls on headless Linux).
* **Stockfish** – `Engines ▸ Install Stockfish` downloads a build for your
  platform; the binary is ~110 MB, which is why it is not shipped in the
  repo. The built-in engine needs nothing extra and plays all variants,
  including the ones Stockfish cannot.
* **Check yourself** – `python tools/selftest.py` runs 100 headless checks
  over the engine, every variant, the Anarchchess rules, the Anarchess game,
  the learning model, the training modes, the database, the UCI driver and
  the Battle Chess simulation (no display required).
* **Screenshots** – `python tools/capture_preview.py` renders the real
  application into `preview/`. It needs a display: on a headless machine run
  it under `xvfb-run -s "-screen 0 1600x1000x24"`.
