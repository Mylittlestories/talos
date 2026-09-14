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
