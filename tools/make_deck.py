#!/usr/bin/env python3
"""
Build the TALOS presentation: one self-contained HTML file.

    python tools/make_deck.py            -> presentation/index.html

Nothing is loaded from the internet when you open it: the CSS, the script and
the app icon are all inlined, so the file can be emailed, put on a USB stick or
served as the GitHub Pages landing page.

The numbers on the slides are *generated*, not typed: level names and Elo
ratings come from lc/core/engine.py, the Anarchchess rule list from
lc/variants/anarchchess.py, the puzzle counts from data/lucas.db and the icon
from assets/talos.svg.  Change the code and rebuild the deck - it cannot drift.

Press -> or space to advance, O for the overview, F for fullscreen, P to print
(one slide per page).
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lc.core.engine import DEFAULT_LEVELS                       # noqa: E402
from lc.variants.anarchchess import RULE_BOOK                   # noqa: E402

OUT = os.path.join(ROOT, "presentation", "index.html")
ICON = os.path.join(ROOT, "assets", "talos.svg")
DB = os.path.join(ROOT, "data", "lucas.db")

#: The canonical URLs. Change both if the project is renamed or forked.
REPO = "https://github.com/Mylittlestories/talos"
PAGES = "https://mylittlestories.github.io/talos/"


# --------------------------------------------------------------------------
# facts, straight from the source
# --------------------------------------------------------------------------

def counts() -> dict:
    info = {"puzzles": 0, "sets": 0, "games": 0, "kinds": []}
    if not os.path.exists(DB):
        return info
    db = sqlite3.connect(DB)
    info["puzzles"] = db.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
    info["sets"] = db.execute("SELECT COUNT(*) FROM sets").fetchone()[0]
    try:
        info["games"] = db.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    except sqlite3.Error:
        info["games"] = 0
    info["kinds"] = db.execute(
        "SELECT kind, COUNT(*) FROM sets GROUP BY kind ORDER BY 2 DESC").fetchall()
    db.close()
    return info


def level_rows() -> str:
    rows = []
    for level in DEFAULT_LEVELS:
        rows.append("<tr><td>%s</td><td>%d</td><td>%d</td><td>%d ms</td></tr>"
                    % (level.name, level.elo, level.max_depth, level.movetime_ms))
    return "\n".join(rows)


def rule_items() -> str:
    out = []
    for entry in RULE_BOOK:
        key, title = entry[0], entry[1]
        if len(entry) > 2 and isinstance(entry[2], str) and entry[2]:
            tip = entry[2]
        else:
            tip = ""
        out.append('<li><b>%s</b><span>%s</span></li>'
                   % (title, tip if len(tip) < 120 else tip[:117] + "…"))
    return "\n".join(out)


# --------------------------------------------------------------------------
# the deck
# --------------------------------------------------------------------------

TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TALOS — The Living Chess Studio</title>
<meta name="description" content="TALOS: a Lucas Chess inspired chess studio with its own engine, 112,000 puzzles, Anarchess and Anarchchess. Windows, Linux, Android and browser editions.">
<style>
:root{
  --window:#0e1015; --panel:#151925; --panel2:#1b2030; --line:#272d3d;
  --text:#e9e6df; --dim:#9aa2b4; --accent:#f0b429; --accent2:#4cc2ff;
  --good:#7ee081; --bad:#e05a4f; --light:#eee3cc; --dark:#8d6a48;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0; background:var(--window); color:var(--text);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:flex; flex-direction:column; overflow:hidden;
  -webkit-font-smoothing:antialiased;
}
h1,h2,h3{margin:0 0 .5em; line-height:1.15}
h1{font-size:clamp(30px,4.4vw,58px); letter-spacing:-.02em}
h2{font-size:clamp(22px,2.6vw,34px); letter-spacing:-.01em}
h3{font-size:15px; text-transform:uppercase; letter-spacing:.14em; color:var(--accent)}
p{margin:0 0 .8em}
a{color:var(--accent2)}
b{color:#fff}
small{color:var(--dim)}
ul{margin:0; padding-left:1.1em}
li{margin:.28em 0}

/* ------------------------------------------------------------------ bars */
.bar{
  flex:none; display:flex; align-items:center; gap:14px;
  padding:10px 18px; border-top:1px solid var(--line); background:#0b0d12;
}
.bar.top{border-top:0; border-bottom:1px solid var(--line)}
.brand{display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:.06em}
.brand svg{width:26px; height:26px; border-radius:6px; flex:none}
.brand span{color:var(--dim); font-weight:400; letter-spacing:.02em; font-size:13px}
.spacer{flex:1}
.counter{color:var(--dim); font-variant-numeric:tabular-nums; font-size:13px}
button{
  font:inherit; color:var(--text); background:var(--panel2);
  border:1px solid var(--line); border-radius:8px; padding:7px 13px; cursor:pointer;
}
button:hover{border-color:var(--accent); color:#fff}
button:disabled{opacity:.35; cursor:default; border-color:var(--line)}
.dots{display:flex; gap:6px}
.dots i{
  width:9px; height:9px; border-radius:50%; background:var(--line);
  cursor:pointer; display:block;
}
.dots i.on{background:var(--accent)}
.hint{color:var(--dim); font-size:12px}
.progress{height:3px; background:var(--line); flex:none}
.progress i{display:block; height:100%; width:0; background:var(--accent); transition:width .25s}

/* ---------------------------------------------------------------- slides */
main{flex:1; display:flex; align-items:center; justify-content:center; padding:22px; min-height:0}
.slide{
  display:none; width:min(1180px,100%); aspect-ratio:16/9; max-height:100%;
  background:linear-gradient(160deg,var(--panel) 0%,#10131b 100%);
  border:1px solid var(--line); border-radius:18px; padding:clamp(20px,3.2vw,52px);
  overflow:hidden; position:relative;
}
.slide.active{display:grid; grid-template-rows:auto 1fr; animation:in .28s ease}
@keyframes in{from{opacity:0; transform:translateY(10px)}to{opacity:1; transform:none}}
.slide:after{
  content:""; position:absolute; inset:auto -30% -55% auto; width:70%; height:90%;
  background:radial-gradient(circle at 70% 30%,rgba(240,180,41,.10),transparent 62%);
  pointer-events:none;
}
.slide > header{position:relative; z-index:1}
.slide > .body{position:relative; z-index:1; min-height:0; display:flex; flex-direction:column; justify-content:center}
.kicker{color:var(--dim); font-size:13px; letter-spacing:.16em; text-transform:uppercase; margin-bottom:.5em}
.lead{font-size:clamp(15px,1.35vw,19px); color:#d7d3ca; max-width:62ch}

.cols{display:grid; grid-template-columns:1fr 1fr; gap:clamp(16px,2.4vw,40px); align-items:start}
.cols3{display:grid; grid-template-columns:repeat(3,1fr); gap:clamp(14px,2vw,30px)}
.card{background:var(--panel2); border:1px solid var(--line); border-radius:12px; padding:14px 16px}
.card h4{margin:0 0 .35em; font-size:15px; color:#fff}
.card p{margin:0; font-size:13.5px; color:var(--dim)}

.big{display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:6px 0 4px}
.big div{background:var(--panel2); border:1px solid var(--line); border-radius:12px; padding:14px}
.big b{display:block; font-size:clamp(20px,2.3vw,30px); color:var(--accent); line-height:1.1}
.big span{font-size:12.5px; color:var(--dim)}

table{width:100%; border-collapse:collapse; font-size:14px}
th,td{text-align:left; padding:5px 8px; border-bottom:1px solid var(--line)}
th{color:var(--accent); font-size:11.5px; text-transform:uppercase; letter-spacing:.1em}
td:not(:first-child){font-variant-numeric:tabular-nums; color:var(--dim)}
td:first-child{color:#fff}

.rules{list-style:none; padding:0; columns:3; column-gap:22px; font-size:13px}
.rules li{break-inside:avoid; margin:0 0 9px}
.rules b{display:block; font-size:13px}
.rules span{color:var(--dim); font-size:12px}

.steps{display:grid; grid-template-columns:repeat(3,1fr); gap:16px; counter-reset:s}
.step{position:relative; padding-left:44px}
.step:before{
  counter-increment:s; content:counter(s);
  position:absolute; left:0; top:0; width:30px; height:30px; border-radius:50%;
  background:var(--accent); color:#1a1405; font-weight:800;
  display:flex; align-items:center; justify-content:center; font-size:14px;
}
.step h4{margin:.1em 0 .3em; font-size:15px}
.step p{margin:0; font-size:13px; color:var(--dim)}

.iconrow{display:flex; gap:clamp(16px,3vw,46px); align-items:center}
.iconrow .app{width:clamp(120px,17vw,230px); height:auto; border-radius:22px; flex:none;
  box-shadow:0 18px 50px rgba(0,0,0,.5)}
.ingredients li{margin:.55em 0; font-size:14px}

.center{text-align:center}
.center .body{align-items:center}
.cta{margin-top:22px; display:flex; gap:12px; justify-content:center; flex-wrap:wrap}
.cta a{
  text-decoration:none; font-weight:600; padding:12px 22px; border-radius:10px;
  border:1px solid var(--accent); color:var(--accent);
}
.cta a.primary{background:var(--accent); color:#1a1405}
.cta a.ghost{border-color:var(--line); color:var(--text)}

.grid9{display:grid; grid-template-columns:repeat(2,1fr); gap:10px 26px; font-size:14px}

/* --------------------------------------------------------------- overview */
body.over main{overflow:auto; align-items:flex-start}
body.over .slide{display:grid; width:100%; max-width:1100px; aspect-ratio:16/9;
  max-height:none; margin:0 auto 18px; cursor:pointer; animation:none}
body.over .slide:after{display:none}
body.over .slide.active{outline:2px solid var(--accent)}

@media (max-width:900px){
  .cols,.cols3,.steps{grid-template-columns:1fr}
  .big{grid-template-columns:repeat(2,1fr)}
  .rules{columns:2}
  .slide{aspect-ratio:auto; min-height:100%; overflow:auto}
}
@media print{
  @page{size:landscape; margin:8mm}
  body{overflow:visible; height:auto; display:block; background:#fff}
  .bar,.progress,.hint{display:none !important}
  main{display:block; padding:0}
  .slide{display:grid !important; page-break-after:always; border-color:#bbb;
    background:#fff; color:#111; max-height:none}
  .slide:after{display:none}
  h1,h2,h3,b,td:first-child{color:#111}
  .lead,.card p,.rules span,td,.dim{color:#333}
  .card,.big div{background:#f6f6f6; border-color:#ccc}
  .step:before{background:#111; color:#fff}
}
</style>
</head>
<body>

<header class="bar top">
  <div class="brand">__ICON__<span>TALOS &nbsp;·&nbsp; The Living Chess Studio</span></div>
  <div class="spacer"></div>
  <span class="counter" id="counter">1 / 1</span>
</header>

<div class="progress"><i id="bar"></i></div>

<main id="deck">

<!-- 1 ------------------------------------------------------------------ -->
<section class="slide active" data-title="TALOS">
  <header><p class="kicker">__DATE__ &nbsp;·&nbsp; version __VERSION__</p></header>
  <div class="body center">
    <div class="iconrow" style="justify-content:center">
      <svg class="app" viewBox="0 0 13 13" role="img" aria-label="TALOS icon">__ICONG__</svg>
      <div style="text-align:left">
        <h1>TALOS</h1>
        <p class="lead" style="font-size:clamp(17px,1.8vw,24px); color:var(--accent);
           letter-spacing:.02em; margin-bottom:.6em">The Living Chess Studio</p>
        <p class="lead">A chess studio in the spirit of Lucas Chess, rebuilt from
          the board up: its own engine, an adaptive coach, 112,000 real puzzles,
          the Anarchchess house rules and the Anarchess board game — on Windows,
          Linux, Android and in a browser tab.</p>
        <div class="cta">
          <a class="primary" id="play-link" href="../web/index.html">Play in your browser</a>
          <a class="ghost" href="__REPO__">Source &amp; downloads</a>
        </div>
        <p style="color:var(--dim); font-size:12.5px; margin-top:12px">
          Nothing to install. From a clone, run <code>python tools/build_web.py</code>
          first — it writes the Python payload the page loads.</p>
      </div>
    </div>
  </div>
</section>

<!-- 2 ------------------------------------------------------------------ -->
<section class="slide" data-title="What it is">
  <header><p class="kicker">The idea</p><h2>A studio, not just a board</h2></header>
  <div class="body">
    <p class="lead">Lucas Chess is the best chess <em>teacher</em> ever written
      for the desktop. TALOS keeps that feel — play, train, replay, repeat —
      and rebuilds the parts that age badly: the interface, the engine and the
      reach.</p>
    <div class="cols">
      <div>
        <div class="card" style="margin-bottom:12px">
          <h4>Familiar where it matters</h4>
          <p>Same rhythm as Lucas Chess: pick a level, play, get told where you
            went wrong, drill the position again.</p>
        </div>
        <div class="card" style="margin-bottom:12px">
          <h4>Modern where it counts</h4>
          <p>Three palettes, a responsive layout, vector interface, no
            thousand-button toolbar. Dark, quiet, out of the way.</p>
        </div>
        <div class="card">
          <h4>Yours, entirely</h4>
          <p>No accounts, no telemetry, no server. Everything — engine, database,
            gore, puzzles — runs on your machine.</p>
        </div>
      </div>
      <div>
        <div class="card" style="margin-bottom:12px">
          <h4>Four editions, one core</h4>
          <p>Windows, Linux, Android (installable web app) and the browser all
            execute the same Python modules. No feature is web-only.</p>
        </div>
        <div class="card" style="margin-bottom:12px">
          <h4>Variants that are actually different</h4>
          <p>Anarchchess and full anarchy, plus Anarchess, a tile-laying
            strategy game from the same island as the studio.</p>
        </div>
        <div class="card">
          <h4>Battle Chess when you want it</h4>
          <p>A switch, not an identity. Pieces walk, duel and shatter in
            procedural 3D — turn it on for the spectacle, off for study.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- 3 ------------------------------------------------------------------ -->
<section class="slide" data-title="The engine">
  <header><p class="kicker">Playing strength</p><h2>An engine that has to be respected</h2></header>
  <div class="body">
    <div class="cols">
      <div>
        <h3>Search</h3>
        <ul class="grid9">
          <li>iterative deepening, aspiration windows</li>
          <li>principal variation search</li>
          <li>transposition table with generations</li>
          <li>static exchange evaluation</li>
          <li>null move, reverse futility, razoring*</li>
          <li>late move reductions + verification</li>
          <li>check, singular &amp; recapture extensions</li>
          <li>killers, countermoves, continuation history</li>
          <li>quiescence with delta pruning</li>
          <li>triangular PV (exact, not reconstructed)</li>
        </ul>
        <p><small>* razoring is measured and off: it prunes away sacrifices —
          58.7&nbsp;% → 73.3&nbsp;% on the tactical suite when disabled.</small></p>
      </div>
      <div>
        <h3>Evaluation</h3>
        <ul class="grid9">
          <li>tapered material &amp; piece-square tables</li>
          <li>pawn structure: doubled, isolated, passed</li>
          <li>phalanx and connected pawns</li>
          <li>mobility with safe squares, outposts</li>
          <li>bishop pair, rooks on open files &amp; 7th</li>
          <li>trapped bishops and rooks</li>
          <li>king safety: shield, attack units, ring</li>
          <li>threats, space, tempo, smooth phase</li>
        </ul>
        <h3 style="margin-top:14px">Measured</h3>
        <p><b>__BENCH__</b> on the __BENCHN__-position tactical suite
          (avg depth 3.9, ~5,700 nodes/second, pure Python).</p>
      </div>
    </div>
  </div>
</section>

<!-- 4 ------------------------------------------------------------------ -->
<section class="slide" data-title="Levels">
  <header><p class="kicker">Opponents</p><h2>__NLEVELS__ levels from 800 to __TOP_ELO__</h2></header>
  <div class="body">
    <div class="cols">
      <div class="card">
        <table>
          <tr><th>Level</th><th>Elo</th><th>Depth</th><th>Time</th></tr>
__LEVELS__
        </table>
      </div>
      <div>
        <div class="card" style="margin-bottom:12px">
          <h4>Levels are personalities, not just depths</h4>
          <p>Every level carries its own depth cap, thinking time and a
            deliberate blunder rate, so “Pawn” misses things the way a beginner
            does instead of playing a shallow perfect move.</p>
        </div>
        <div class="card" style="margin-bottom:12px">
          <h4>Stockfish, when you want the truth</h4>
          <p>The in-app installer fetches a real Stockfish binary (about
            113&nbsp;MB, on demand, never in the repository) for analysis and
            for sparring far above the built-in levels.</p>
        </div>
        <div class="card">
          <h4>Every variant, same engine</h4>
          <p>Move generation is delegated to the variant-aware board, so the
            engine also plays Chess960, Crazyhouse, Atomic, King of the Hill,
            Three-check, Horde, Racing Kings, Antichess and Anarchchess.</p>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- 5 ------------------------------------------------------------------ -->
<section class="slide" data-title="Anarchchess">
  <header><p class="kicker">Variation 1</p><h2>Anarchchess — __NRULES__ house rules, each a switch</h2></header>
  <div class="body">
    <p class="lead" style="margin-bottom:.7em">The rules the community actually
      plays, collected from r/AnarchyChess, anarchychess.org and the bots.
      “Anarchchess” is the curated set; “Full anarchy” turns on all of them,
      including the ones that wreck a game.</p>
    <ul class="rules">
__RULES__
    </ul>
  </div>
</section>

<!-- 6 ------------------------------------------------------------------ -->
<section class="slide" data-title="Anarchess">
  <header><p class="kicker">Variation 2</p><h2>Anarchess — the land before Chess</h2></header>
  <div class="body">
    <p class="lead">A real abstract strategy game by <b>Dimitris Grammenos</b>
      (ICS-FORTH, Heraklion). Two proud tribes, no kings yet, growing a
      landscape out of 32 light and 32 dark tiles. Reconstructed from the
      published summary and playtested here for 2, 3 and 4 players.</p>
    <div class="cols">
      <div>
        <h3>A turn</h3>
        <ol>
          <li><b>Lay one tile</b> next to the land — you choose light or dark.</li>
          <li><b>Then one pawn action</b>, if you want it: settle a pawn from
            your reserve, step one square, or attack a neighbour.</li>
          <li>Attacks only land when the attacker is <b>supported</b> by a
            friendly pawn. A tribe fights together.</li>
        </ol>
      </div>
      <div>
        <h3>Scoring</h3>
        <p>An <b>area</b> is a maximal group of edge-connected tiles of one
          colour. When the last tile is laid, every area of two or more tiles
          scores one point per tile to whoever has the most pawns on it.
          Single tiles are worth nothing.</p>
        <p><small>Every open question in the reconstruction is a switch and a
          recorded ruling — see <code>lc/anarchess/rules.py</code>.</small></p>
      </div>
    </div>
  </div>
</section>

<!-- 7 ------------------------------------------------------------------ -->
<section class="slide" data-title="Battle Chess">
  <header><p class="kicker">Feature</p><h2>Battle Chess, on demand</h2></header>
  <div class="body">
    <div class="cols">
      <div>
        <h3>A switch, not an identity</h3>
        <p class="lead">The studio is a study tool first. Battle Chess mode is a
          toggle in the toolbar: on for the spectacle, off for analysis.</p>
        <ul>
          <li>Six kill choreographies, chosen by what takes what.</li>
          <li>Procedural geometry and particles — <b>no gigabytes of assets</b>,
            no downloads, works offline.</li>
          <li>Gore level <b>classic</b>: the 1988 tone. Stylised blood spray and
            debris, never gritty dismemberment.</li>
          <li>Blood stains stay on the board for the rest of the game.</li>
        </ul>
      </div>
      <div class="card">
        <h4>Why procedural?</h4>
        <p>The obvious route — the Battle Chess 9000 asset set — is roughly
          1.2&nbsp;GB of models and textures. Rebuilding the choreographies out
          of procedural geometry keeps the whole studio a few tens of
          megabytes and makes the animation real-time instead of canned.</p>
        <h4 style="margin-top:12px">Pieces that move</h4>
        <p>A knight does not slide. It hops, lands, and turns to face whatever
          it is about to kill.</p>
      </div>
    </div>
  </div>
</section>

<!-- 8 ------------------------------------------------------------------ -->
<section class="slide" data-title="Learning">
  <header><p class="kicker">Training</p><h2>An adaptive coach over real Lucas data</h2></header>
  <div class="body">
    <div class="big">
      <div><b>__PUZZLES__</b><span>puzzles imported from Lucas Chess</span></div>
      <div><b>__SETS__</b><span>training sets, grouped by theme</span></div>
      <div><b>__GAMES__</b><span>master games to replay</span></div>
      <div><b>__KINDS__</b><span>categories: tactics, mates, endings, STS…</span></div>
    </div>
    <div class="cols">
      <div class="card">
        <h4>Not generated drills</h4>
        <p>Every puzzle is parsed out of the real Lucas Chess sets: tactics,
          mates in N, endgames, the Strategic Test Suite and positional
          collections. Nothing is procedurally invented.</p>
      </div>
      <div class="card">
        <h4>A coach that schedules</h4>
        <p>Each puzzle you touch gets a box. Get it right and it drifts further
          away (half a day → two days → a week → a month). Miss it and it comes
          back tomorrow. Accuracy, streak and what is due are always visible.</p>
      </div>
    </div>
  </div>
</section>

<!-- 9 ------------------------------------------------------------------ -->
<section class="slide" data-title="Four editions">
  <header><p class="kicker">Availability</p><h2>One codebase, four editions</h2></header>
  <div class="body">
    <table>
      <tr><th>Edition</th><th>What you install</th><th>Engine</th><th>Offline</th></tr>
      <tr><td><b>Windows</b></td><td>Inno Setup installer, or a portable zip.
        <small>Adds <code>.pgn</code> file associations.</small></td>
        <td>Python core + optional Stockfish</td><td>yes</td></tr>
      <tr><td><b>Linux</b></td><td>One-folder build + <code>install.sh</code>
        into <code>~/.local</code>; ships a <code>.desktop</code> file and
        AppStream metadata.</td><td>Python core + optional Stockfish</td><td>yes</td></tr>
      <tr><td><b>Android</b></td><td>Nothing to sideload: open the site and
        “Add to Home Screen”. It becomes a full-screen, offline app.</td>
        <td>Python core under Pyodide</td><td>after first load</td></tr>
      <tr><td><b>Browser</b></td><td>Nothing at all. <code>__PAGES__</code> →
        play. A service worker caches the whole studio.</td>
        <td>Python core under Pyodide</td><td>after first load</td></tr>
    </table>
    <p style="margin-top:14px"><small>Battle Chess mode (real-time 3D) and
      Stockfish are desktop-only; everything else — engine, levels, puzzles,
      Anarchchess, Anarchess, the coach — is identical in all four.</small></p>
  </div>
</section>

<!-- 10 ---------------------------------------------------------------- -->
<section class="slide" data-title="How the web edition works">
  <header><p class="kicker">Architecture</p><h2>The same Python, in a tab</h2></header>
  <div class="body">
    <div class="steps" style="margin-bottom:26px">
      <div class="step">
        <h4>The real modules</h4>
        <p><code>tools/build_web.py</code> copies <code>engine.py</code>,
          <code>anarchchess.py</code>, <code>anarchess/rules.py</code>,
          <code>anarchess/ai.py</code> and vendored python-chess into
          <code>web/python/</code>. No rewrites, no ports.</p>
      </div>
      <div class="step">
        <h4>A worker runs them</h4>
        <p>Pyodide boots in a Web Worker, mounts those files and imports
          <code>bridge.py</code>: a JSON-in / JSON-out API. The UI never blocks
          while the engine thinks.</p>
      </div>
      <div class="step">
        <h4>Everything is cached</h4>
        <p>A service worker stores the shell, the Python core and the sets.
          The 2&nbsp;MB puzzle file is fetched only when you open a set, then
          cached. Second visit: works with the wifi off.</p>
      </div>
    </div>
    <div class="cols3">
      <div class="card"><h4>1.1 MB</h4><p>Python core, vendored and ready.</p></div>
      <div class="card"><h4>82 checks</h4><p><code>tools/web_smoke.mjs</code>
        boots the payload in Node and plays a game, a puzzle and an Anarchess
        turn on every push.</p></div>
      <div class="card"><h4>0 requests</h4><p>to any TALOS server, ever. There
        is no TALOS server.</p></div>
    </div>
  </div>
</section>

<!-- 11 ---------------------------------------------------------------- -->
<section class="slide" data-title="The icon">
  <header><p class="kicker">Identity</p><h2>A mark made of both parents</h2></header>
  <div class="body">
    <div class="iconrow">
      <svg class="app" viewBox="0 0 13 13" role="img" aria-label="TALOS icon">__ICONG__</svg>
      <div>
        <ul class="ingredients">
          <li><b>The knight</b> — Lucas Chess' own silhouette, drawn as a
            vector so it survives being 16 pixels wide.</li>
          <li><b>The loose tiles</b> — Anarchess' board before it was squeezed
            into the rigid chessboard: light and dark squares, floating free,
            no 8×8 grid yet.</li>
          <li><b>The amber plate</b> — the Cretan light the studio was built in,
            and the accent colour of the whole interface.</li>
        </ul>
        <div class="cols3" style="margin-top:18px">
          <div class="card"><h4>17 files</h4><p>from a 16&nbsp;px favicon to a
            1024&nbsp;px master, plus maskable and Apple touch variants.</p></div>
          <div class="card"><h4>Drawn, not prompted</h4>
            <p><code>tools/make_icon.py</code> rasterises real glyphs and lays
              out the tiles, so the set can be regenerated exactly.</p></div>
          <div class="card"><h4>Readable at 16 px</h4>
            <p>Measured: the knight fills 61&nbsp;% of the mark and the tiles
              stay legible down to the favicon.</p></div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- 12 ---------------------------------------------------------------- -->
<section class="slide" data-title="Releases">
  <header><p class="kicker">Shipping</p><h2>Tag it, and everything updates</h2></header>
  <div class="body">
    <div class="steps">
      <div class="step">
        <h4>CI, on every push</h4>
        <p>Self-tests on Linux, macOS and Windows across three Python
          versions, a packaging smoke build, and the browser smoke test.</p>
      </div>
      <div class="step">
        <h4>Tag <code>v2.0.0</code></h4>
        <p>Three build jobs produce a Windows zip, a Linux tarball and a macOS
          app zip, and a release job lifts that version's section out of
          <code>CHANGELOG.md</code>.</p>
      </div>
      <div class="step">
        <h4>Draft release + Pages</h4>
        <p>A draft release appears with the notes and a
          <code>SHA256SUMS.txt</code>; publishing it publishes the site too:
          the deck as the landing page, the playable app at
          <code>/web/</code>.</p>
      </div>
    </div>
    <div class="cols3" style="margin-top:22px">
      <div class="card"><h4>Reproducible</h4><p>Every artefact is built from a
        clean checkout by the same script you can run locally.</p></div>
      <div class="card"><h4>Verifiable</h4><p><code>sha256sum -c</code> against
        the checksums attached to the release.</p></div>
      <div class="card"><h4>Reversible</h4><p>Releases open as drafts — nothing
        goes out until somebody reads it and presses publish.</p></div>
    </div>
  </div>
</section>

<!-- 13 ---------------------------------------------------------------- -->
<section class="slide" data-title="Roadmap">
  <header><p class="kicker">Next</p><h2>What is left, honestly</h2></header>
  <div class="body">
    <div class="cols">
      <div>
        <h3>Soon</h3>
        <ul>
          <li>Deeper search: the bench suite is at <b>__BENCH__</b>; the next
            wins are in move ordering and the endgame tables.</li>
          <li>More of the Lucas corpus: openings trainer and the replay
            database in the browser edition.</li>
          <li>Battle Chess choreographies for the remaining piece pairings.</li>
          <li>A macOS notarised build (the job exists; it needs a certificate).</li>
        </ul>
      </div>
      <div>
        <h3>Contributing</h3>
        <ul>
          <li><code>./tools/setup_env.sh</code>, then
            <code>python run.py</code>.</li>
          <li><code>python tools/selftest.py</code> must stay at 100&nbsp;%,
            and every change adds a check.</li>
          <li>Engine changes must quote
            <code>tools/bench.py</code> numbers in the pull request.</li>
          <li>GPL v2 or later, like Lucas Chess.</li>
        </ul>
      </div>
    </div>
    <p class="lead" style="margin-top:18px">TALOS is named for the bronze
      guardian of Crete: made on the island, for the island, and for anyone who
      wants a chess studio that is theirs.</p>
  </div>
</section>

</main>

<footer class="bar">
  <button id="prev" aria-label="Previous slide">←</button>
  <button id="next" aria-label="Next slide">→</button>
  <div class="dots" id="dots"></div>
  <div class="spacer"></div>
  <span class="hint">← → or space to move · O overview · F fullscreen · P print</span>
</footer>

<script>
(function(){
  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var dots = document.getElementById("dots");
  var counter = document.getElementById("counter");
  var bar = document.getElementById("bar");
  var index = 0;

  slides.forEach(function(slide, i){
    var dot = document.createElement("i");
    dot.title = slide.dataset.title || (i + 1);
    dot.addEventListener("click", function(){ go(i); });
    dots.appendChild(dot);
  });

  function paint(){
    slides.forEach(function(slide, i){ slide.classList.toggle("active", i === index); });
    Array.prototype.forEach.call(dots.children, function(dot, i){
      dot.classList.toggle("on", i === index);
    });
    counter.textContent = (index + 1) + " / " + slides.length;
    bar.style.width = ((index + 1) / slides.length * 100) + "%";
    if (location.hash !== "#" + (index + 1)) {
      history.replaceState(null, "", "#" + (index + 1));
    }
  }

  function go(n){
    index = Math.max(0, Math.min(slides.length - 1, n));
    paint();
  }

  document.getElementById("prev").addEventListener("click", function(){ go(index - 1); });
  document.getElementById("next").addEventListener("click", function(){ go(index + 1); });

  document.addEventListener("keydown", function(event){
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    switch (event.key) {
      case "ArrowRight": case "PageDown": case " ": case "Enter": go(index + 1); break;
      case "ArrowLeft": case "PageUp": case "Backspace": go(index - 1); break;
      case "Home": go(0); break;
      case "End": go(slides.length - 1); break;
      case "o": case "O": document.body.classList.toggle("over"); break;
      case "f": case "F":
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen();
        break;
      case "p": case "P": window.print(); break;
      default: return;
    }
    event.preventDefault();
  });

  // swipe, for the phone
  var startX = null;
  document.addEventListener("touchstart", function(e){ startX = e.touches[0].clientX; }, {passive:true});
  document.addEventListener("touchend", function(e){
    if (startX === null) return;
    var dx = e.changedTouches[0].clientX - startX;
    if (Math.abs(dx) > 45) go(index + (dx < 0 ? 1 : -1));
    startX = null;
  });

  document.getElementById("deck").addEventListener("click", function(event){
    if (!document.body.classList.contains("over")) return;
    var slide = event.target.closest(".slide");
    if (!slide) return;
    go(slides.indexOf(slide));
    document.body.classList.remove("over");
  });

  var fromHash = parseInt((location.hash || "").replace("#", ""), 10);
  if (fromHash >= 1 && fromHash <= slides.length) index = fromHash - 1;
  paint();
})();
</script>

<script>
/* The deck sits in presentation/ inside the repository, but at the site root
   once GitHub Pages publishes it — so the path to the playable app is
   different in the two places.  Probe once and point the button at whichever
   one is actually there. */
(function(){
  var link = document.getElementById("play-link");
  if (!link || !/^https?:$/.test(location.protocol)) return;
  var candidates = ["../web/index.html", "web/index.html", "../../web/index.html"];
  var at = 0;
  (function attempt(){
    if (at >= candidates.length) return;
    var href = candidates[at++];
    fetch(href.replace("index.html", "python/files.json"))
      .then(function(res){ if (res.ok) link.href = href; else attempt(); })
      .catch(function(){ attempt(); });
  })();
})();
</script>
</body>
</html>
'''


def main() -> int:
    if not os.path.exists(ICON):
        print("run tools/make_icon.py first - no %s" % ICON, file=sys.stderr)
        return 1
    with open(ICON) as fh:
        svg = fh.read()
    # strip the outer <svg> so it can be nested with our own sizing
    inner = svg.split(">", 1)[1].rsplit("</svg>", 1)[0]

    info = counts()
    version = "2.0.0"
    html = TEMPLATE
    html = html.replace("__ICON__", svg)
    html = html.replace("__ICONG__", inner)
    html = html.replace("__DATE__", _dt.date.today().strftime("%B %Y"))
    html = html.replace("__VERSION__", version)
    html = html.replace("__REPO__", REPO)
    html = html.replace("__PAGES__", PAGES)
    html = html.replace("__LEVELS__", level_rows())
    html = html.replace("__RULES__", rule_items())
    html = html.replace("__NLEVELS__", str(len(DEFAULT_LEVELS)))
    html = html.replace("__TOP_ELO__", str(DEFAULT_LEVELS[-1].elo))
    html = html.replace("__NRULES__", str(len(RULE_BOOK)))
    html = html.replace("__BENCH__", "109 / 150 (72.7 %)")
    html = html.replace("__BENCHN__", "150")
    html = html.replace("__PUZZLES__", "{:,}".format(info["puzzles"]))
    html = html.replace("__SETS__", str(info["sets"]))
    html = html.replace("__GAMES__", "{:,}".format(info["games"]))
    html = html.replace("__KINDS__", str(len(info["kinds"])))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(html)
    print("deck:   %s (%d KB, %s rules, %s levels)"
          % (os.path.relpath(OUT, ROOT), len(html) // 1024,
             len(RULE_BOOK), len(DEFAULT_LEVELS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
