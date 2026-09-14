# Changelog

All notable changes to TALOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning: **MAJOR** for breaking changes, **MINOR** for new
features, **PATCH** for fixes.

Every entry below is also the text of the matching GitHub Release: the
release workflow lifts the section for the tag out of this file.

---

## [Unreleased]

Nothing yet.

---

## [2.1.0] — The land before Chess, and thirty ways to die

Anarchess stopped being a reconstruction, and Battle Chess learned to walk.

### Added

- **Anarchess is played from the designer's own rulebook.** The version in the
  repository had been pieced together from a summary, and every open question
  in it had been answered with a switch. The published rules replace it: the
  opening is four tiles with the two light ones diagonal, the die names the
  colour and the *other* tribe lays it, a tile touching only one other must be
  of the opposite colour, attacks land on the diagonal with no support needed,
  a pawn may only be settled onto the tile just laid, and the scoring is two
  points a tile — three where the area matches its owner's colour or is held
  by a lone pawn, but only one in the largest area, which is taxed. A single
  tile scores nothing and a pawn left in the reserve costs six.
- **Anarchess SOLO and Anarcheckers**, the two further variants from the same
  author, now play. SOLO is one player against a target of 192, playing both
  tribes, with the pawn action forced in a fixed order. Anarcheckers steps and
  captures on the diagonals, with captures forced and chains that must be
  followed through.
- **Thirty duels.** The 1988 original gave every capture its own animation —
  "a different animation for each permutation" — and so does this now. Six
  pieces can take, five can be taken, and each of the thirty pairs has its own
  name, its own way of striking, its own death, its own length and its own
  mess. A knight taking a knight cuts his enemy limb from limb; a knight
  facing the queen dodges her magic and turns it against her.
- **Six ways to walk.** Each rank crosses the board differently: the knight
  leaves the ground altogether, the rook takes two enormous paces and thuds on
  each, the bishop never quite touches the floor, the pawn hurries with his
  head down, the queen struts and the king waddles. Longer moves take longer,
  but not proportionally.
- `python tools/app_smoke.py` builds the real window and plays Anarchess in
  all three of its modes. Twenty checks on the wiring rather than the parts.

### Changed

- **The Anarchess dialog is rebuilt.** Four switches that described the old
  reconstruction are gone; in their place are the variant, the size of the
  land, and the rulebook's own dials — the tax on the largest area, the colour
  bonus, and what a pawn left in reserve costs.
- **The board shows what things are worth.** Areas are outlined rather than
  tinted, the taxed largest area wears a broken outline, and each is labelled
  with what it currently scores. The tile just laid is ringed: it is the only
  place a pawn may be settled.
- The presentation deck described the reconstruction. It describes the
  published game now, and names the walks and the duels.

### Fixed

- **The bot was paid to lose.** Its evaluation rewarded keeping pawns in the
  reserve, which the published scoring charges six points for. It now follows
  the rulebook's arithmetic.
- **The strongest level was losing to the weakest.** Level 3's opponent model
  measured its own loss, which barely differs between candidate tiles. It
  measures the opponent's gain now: level 3 beats level 1 five games in six,
  and the ladder is ordered throughout.
- **The browser edition could not settle a pawn at all.** Each snapshot
  dropped the tile just laid, and settling is only ever onto that tile, so the
  reserve could never be spent. The snapshot also carried rule fields that no
  longer exist, which crashed every snapshot outright, and offered two
  triangles per cell to pick a colour the die had already chosen, so every
  tile click was rejected.
- **A solo player with no pawn action available had no legal move**, which
  stopped the game dead. The action is forced only when one exists.
- **Two deaths could never finish dying.** Flattening and melting shrank the
  piece by subtracting from a value they had just overwritten, so the victim
  was still standing when the turn ended and got cut off mid-animation. The
  turn now waits for it, as the original did.
- **"engine sees mate in one" failed about one run in ten.** Not the search:
  it asked the Club level, which is built to play a worse move 8% of the time.
  It asks Master+ now, which blunders never.

---

## [2.0.3] — The name on the box

An audit of what the project claims about itself, prompted by a screenshot of
the About box.

### Fixed

- **The About box said "Lucas Chess NX"**, the project's old name, and listed
  a feature set two releases out of date. It now says TALOS, shows the mark at
  96 px, and states the version. Its numbers are counted from the code - the
  levels, the Elo range, the personalities and the variants - so they cannot
  drift away from reality again. Which they had: the old text claimed ten
  variants and 109 engine levels. There are twelve variants and twelve levels,
  800 to 2250 Elo.
- **The old name survived in nine other places**: four package docstrings, the
  self test, the fake UCI engine used by the tests, and the environment setup
  script. All now say TALOS. The changelog keeps its historical mention.
- **The browser edition reported version 2.0.0** regardless of what it was.
  The version is now read from `lc/__init__.py` and stamped into the bundle at
  build time, since that file is deliberately not shipped to the browser.
- **The presentation deck was frozen at 2.0.0**, including the release slide
  that told you to tag `v2.0.0`. It reads the version from the code too, so
  every rebuild is current.
- **The PWA manifest described 15,000 puzzles.** The library holds 112,198;
  the page description was right and only the manifest was understating it.

### Changed

- **The icon is redrawn.** The knight was built out of separate tiles with gaps
  between them, which held together at 1024 px and came apart long before it
  mattered: at 64 px the eye met a scatter of squares instead of a horse, and
  at 16 px on a taskbar there was nothing left to read. The silhouette is now
  filled as one piece of amber and the land tiles are laid *into* it in a
  close second tone, flush, so the outline survives every size and the mosaic
  only shows where there is room for it. Each size is drawn for itself rather
  than shrunk from the master, because a mosaic that reads as detail at 1024
  becomes stripes at 32. The knight also stands on a faint board along the
  foot of the plate, so the mark says chess before it says anything else.
- **The Android icon no longer gets cropped.** The maskable variant drew the
  same rounded plate, so nearly half of it fell outside the safe circle and
  the launcher cut the mark off. It is full bleed now, with a circular rim at
  the safe edge and the knight pulled in to 33% - inside the zone every
  launcher guarantees.
- **The browser header drew its own imitation of the mark**: a 3x2 block of
  tiles typed into `app.js`, in different colours, which had drifted away from
  the icon entirely. It now uses the icon file, so the header, the taskbar,
  the home screen and the window are the same picture by construction.

### Added

- **The app carries the mark itself.** The toolbar showed only the name in
  text, so inside the program there was no icon anywhere: it appeared on the
  window and in the taskbar, and nowhere in the interface. The mark now sits
  beside the name in the toolbar, drawn from the same artwork as the
  application icon - one ``app_logo()`` helper feeds the window, the taskbar,
  the About box and the toolbar, so they cannot disagree. ``theme.py`` also
  held a hand-drawn stand-in mark that nothing called and that did not look
  like the real icon; it is now only a fallback for a checkout whose
  ``assets/`` has not been generated yet.
- **The repository shows the icon.** The README now leads with the mark, the
  current release badge, a live play-in-browser badge and the licence.

---

## [2.0.2] — The icon and the room to play

### Fixed

- **The board now has an icon, and room to breathe.** The desktop window
  carried Qt's default mark on Linux: PyInstaller stamps the icon into the
  Windows and macOS bundles, but the running window only shows it if the
  application is told about it. TALOS now sets its own window icon on every
  platform, at every size from 16 to 256 pixels, so it is the same mark in the
  title bar, the taskbar and the Alt-Tab switcher.
- **The browser edition ships its icons.** `web/icons/` was generated at build
  time and deliberately not committed, so a fresh clone - or anything served
  straight out of the repository - showed the browser's blank-page icon
  instead of TALOS. The six icon files are now in the repository. They are
  279 KB in total and regenerate byte for byte, so nothing drifts.

### Changed

- **The board uses the space it has.** Capping it at 640 px left a 1080p
  screen looking mostly empty, which read as flimsy rather than calm. It now
  grows to `min(760px, 100vw - 480px, 100vh - 240px)` - 760 px on a 1080p
  screen, and it still comes only from the viewport, so a longer move list or
  a wrapped status line cannot move it by a pixel.

---

## [2.0.1] — Fixes

Three fixes, all from hands-on play rather than from theory.

### Fixed

- **The board no longer breathes.** In the browser edition the board was sized
  by its neighbours in the flex row, so a growing move list, a status line
  that wrapped onto two lines, or a scrollbar appearing could resize the board
  by a few pixels on almost every move. The size now comes only from the
  viewport (`min(640px, 100%, 100vh - 210px)`), and the status line reserves
  the two lines it may need, so the board is the same square on every move.
- **Battle Chess no longer takes the application down with it.** It used to
  die the moment the mode was switched on: an error while drawing the 3D
  board repeated at sixty frames a second, which buried the window under
  error dialogs, and on machines without a working OpenGL driver Qt simply
  left a blank panel where the board should be. Three things now stand
  between that and the player. The mode asks whether a GL context can be
  created *before* it switches, and says so plainly if not. A drawing error
  is caught once: the animation loop stops, the window returns to the flat
  board, and a single dialog carries the traceback. And if no frame has
  arrived after a couple of seconds, a watchdog pulls the game back to the
  flat board. Every other feature carries on either way.
- **Anarchess is no longer dark.** The land is unbounded, so most of the
  canvas is board that simply has no tile on it yet — but it was painted flat
  black, which read as fog of war. Two changes: the land now scales to fit the
  window, so it stays whole however far it spreads (instead of running off the
  edge), and the empty squares are drawn as a faint grid, so it is obvious
  where a tile can still be placed. Both the desktop and the browser board.

---

## [2.0.0] — TALOS

The release that gives the project its name. TALOS — *The Living Chess
Studio* — is a chess school, a Battle Chess stage, an anarchic rulebook and a
land before Chess, in one local application.

### Added

**Anarchchess — the house rules, playable**
- A new variant family with fifteen switches, collected from r/AnarchyChess,
  anarchychess.org and the Anarchchess bots. Every rule is a checkbox under
  `Anarchy ▸ Choose the rules…`.
- Forced en passant, **knooks** (a knight fuses with a friendly rook and
  gains both move sets), the **c4 detonation**, **double check wins**, the
  king may never go to **c2**, **Il Vaticano**, the **Siberian Swipe**,
  **vertical castling**, the **knight boost**, **dismounting**, and
  **radioactive queen decay**.
- **Full anarchy** adds the omnipotent pawn, **promotion roulette**, the
  hyper-accelerated **Bongcloud** win and random events every turn.
- Two presets ship ready: *Anarchchess* (curated) and *Full anarchy*.
- The built-in engine plays both without a single change: it only ever asks
  python-chess what is legal.

**Anarchess — the land before Chess**
- A reconstruction of Anarchess by Dimitris Grammenos (FORTH), built from the
  components and scoring described by its author: 32 light + 32 dark tiles,
  2–4 players (8/6/5 pawns each), lay a tile then take one optional pawn
  action, score every area of two or more tiles.
- Playable against three bot levels, with a pan/zoom board and a live
  territory readout.
- The eight questions the published sources leave open are documented in the
  app as numbered reconstruction decisions — and most of them are switches.

**The learning coach**
- SM-2 spaced repetition over every drill: right answers stretch the
  interval, quick answers stretch it further, hints shrink it, and cards that
  keep slipping are flagged and pushed to the front of the queue.
- An Elo-style rating for eight themes — tactics, mates, endgames, strategy,
  openings, calculation, visualisation, memory — updated against the
  difficulty of what you just attempted.
- `Train ▸ Learning coach…` (`Ctrl+J`): mastery bars, a seven-day forecast,
  recent accuracy, one sentence of advice, and two buttons that act on it —
  *Review what is due* builds a session from exactly the cards whose day has
  come, *Train my weakest theme* opens the mode you need.

**Battle Chess: the victims fight back**
- Six death choreographies, chosen by who dies and who kills: kings are
  **beheaded**, pawns are **knocked over**, the rook **flattens**, the pawn
  **impales**, the bishop **disintegrates**, the queen blows the target apart.
- Blood at two levels: `Battle ▸ Gore ▸ Classic` is the 1988 tone (stylised
  spray that stains the board, pooling decals that spread and dry, severed
  limbs that bounce and settle); `Arcade` replaces every drop with dust.
- New physics: splatting droplets, irregular growing stains, body-part
  debris, a fatter point pass for droplets and a wider shake on impact.

**Interface**
- A real design system (`lc/ui/theme.py`): three palettes — midnight, slate,
  parchment — switchable from `View ▸ Interface theme`, including a
  recoloured toolbar.
- Thirty inline-SVG icons (no external files, so the app works offline and in
  sandboxes).
- The launcher sets the application name, organisation, version and theme.

**Editions — one codebase, four ways to play**
- **Browser edition** (`web/`): the real Python engine, the Anarchess rules
  and the Anarchchess rules running under Pyodide in a Web Worker. Play,
  puzzles, Anarchess and the rule switches, with no install at all.
- **Android edition**: the same site, installable — *Add to Home Screen*
  gives a full-screen app that works offline. No APK, no store, no SDK.
- **Windows and Linux packaging**: a PyInstaller one-folder build, an Inno
  Setup installer with a `.pgn` association, and a user-space Linux installer
  with a `.desktop` file and AppStream metadata (`packaging/`).
- **macOS**: the same spec builds `TALOS.app` (unsigned).
- A service worker caches the whole studio, so the second visit — on a phone
  or a laptop — needs no network.
- The presentation (`presentation/index.html`) doubles as the GitHub Pages
  landing page, with the playable app at `/web/`.
- Releases: every `v*` tag builds all four artefacts, lifts this section out
  of the changelog, attaches `SHA256SUMS.txt` and opens a **draft** release.

### Changed

- The application is **TALOS** everywhere: window title, PGN `Event`/`Site`
  tags, `.desktop` file and installer.
- `run.py` applies the saved interface theme before the first window appears.
- Training sessions now report failures to the learning model, so a wrong
  answer brings the card back tomorrow instead of being forgotten.

### Fixed

- Anarchess deadlocked when a player's pawns were all boxed in: the pawn
  action is optional, so *pass* must always be legal. It now is.
- python-chess 1.11's `remove_piece_at`/`set_piece_at` call `clear_stack()`,
  which silently erased the whole game history every time an anarchic effect
  fired. The variant now edits bitboards directly.
- A king left exposed by an earthquake or a c4 detonation could be captured.
  Eaten kings are struck from the move list, so the exposed side is simply in
  check and loses if it cannot escape.

### Engine

- **Razoring is now off.** A leave-one-out ablation over every pruning
  heuristic showed it cost 22 puzzles on the Lucas tactics set: a static
  evaluation far below alpha is exactly what a sacrifice looks like.
- Puzzle score: **58.7% → 73.3%** on 150 real Lucas puzzles at 400 ms/move
  (`tools/bench.py`), with the self test at 100/100.

---

## [1.0.0]

The first release, then called Lucas Chess NX.

- Standard chess plus ten FICS variants, 12 strength levels and 7
  personalities, any UCI engine, clocks.
- 14 training modes on real Lucas Chess data (112,198 puzzles, 10,000 games,
  6,633 openings).
- Continuous analysis, MultiPV, evaluation graph, whole-game analysis with
  centipawn loss and PGN NAGs.
- Battle Chess 3D mode: procedural pieces, six fight styles, rigid-body
  shards, three cameras.
- Master game database, opening explorer, PGN import/export.
