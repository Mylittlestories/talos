#!/usr/bin/env python3
"""
Benchmark / regression harness for the built-in engine.

It measures three things on real Lucas data (no network, no Stockfish):

    tactics   how many puzzle first-moves the engine finds, per time budget
    mates     forced mates found in the mate-in-N collections
    speed     nodes/second and depth reached on a few positions

    python tools/bench.py                 # quick run
    python tools/bench.py --count 400 --ms 800
    python tools/bench.py --suite mates
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess  # noqa: E402

from lc.core.engine import LCEngine, Level  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "data", "lucas.db")


def load(kind: str, count: int, seed: int = 7):
    """Pull (fen, expected_first_move_uci, label) rows out of the database."""
    if not os.path.exists(DB):
        return []
    conn = sqlite3.connect(DB)
    rows = []
    if kind == "mates":
        sql = ("SELECT fen, solution, category FROM puzzles "
               "WHERE category LIKE '%Mate%' AND solution != ''")
    elif kind == "tactics":
        sql = ("SELECT fen, solution, category FROM puzzles "
               "WHERE category NOT LIKE '%Mate%' AND solution != ''")
    else:
        sql = "SELECT fen, solution, category FROM puzzles WHERE solution != ''"
    try:
        allrows = conn.execute(sql).fetchall()
    except sqlite3.Error:
        return []
    rng = random.Random(seed)
    rng.shuffle(allrows)
    for fen, solution, category in allrows:
        if not fen or not solution:
            continue
        first = solution.split()[0]
        try:
            board = chess.Board(fen)
            move = chess.Move.from_uci(first)
        except Exception:
            continue
        if move not in board.legal_moves:
            # some Lucas lines start with the opponent's move: skip one ply
            try:
                board.push(move)
                second = solution.split()[1]
                move = chess.Move.from_uci(second)
                fen = board.fen()
                if move not in board.legal_moves:
                    continue
            except Exception:
                continue
        rows.append((fen, move.uci(), (category or "")[:34]))
        if len(rows) >= count:
            break
    return rows


def run(rows, ms: int, depth: int, label: str) -> dict:
    level = Level("bench", 2200, max_depth=depth, movetime_ms=ms,
                  blunder=0.0, inaccuracy=0.0, noise=0)
    hits = 0
    nodes = 0
    depths = 0
    started = time.time()
    for fen, want, _cat in rows:
        engine = LCEngine(level, seed=1)
        res = engine.search(chess.Board(fen), movetime_ms=ms, max_depth=depth)
        nodes += res.nodes
        depths += res.depth
        if res.bestmove is not None and res.bestmove.uci() == want:
            hits += 1
    elapsed = time.time() - started
    n = max(1, len(rows))
    return {
        "label": label,
        "n": len(rows),
        "hits": hits,
        "rate": hits / n,
        "nodes": nodes,
        "nps": int(nodes / max(elapsed, 1e-9)),
        "avg_depth": depths / n,
        "seconds": elapsed,
    }


def speed_test(ms: int = 2000, depth: int = 64) -> None:
    positions = [
        ("startpos", chess.STARTING_FEN),
        ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
        ("endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
        ("middlegame", "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P1B2/2PBPN2/PP1N1PPP/R2Q1RK1 w - - 0 1"),
    ]
    for name, fen in positions:
        engine = LCEngine(Level("bench", 2200, max_depth=depth, movetime_ms=ms,
                                noise=0), seed=2)
        res = engine.search(chess.Board(fen), movetime_ms=ms, max_depth=depth)
        print(f"  {name:12s} d{res.depth:<3d} {res.nodes:7d} nodes  "
              f"{int(res.nodes / max(res.time_ms / 1000, 1e-9)):6d} nps  "
              f"{res.score_text:>8s}  {res.time_ms / 1000:.2f}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--ms", type=int, default=400)
    ap.add_argument("--depth", type=int, default=64)
    ap.add_argument("--suite", default="mix",
                    choices=["mix", "mates", "tactics"])
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rows = load(args.suite, args.count, args.seed)
    if not rows:
        print("no puzzle data available (data/lucas.db missing) - speed test only")
    else:
        print(f"TALOS engine benchmark - {len(rows)} puzzles, "
              f"{args.ms} ms/move, suite={args.suite}")
        for ms in (args.ms,):
            r = run(rows, ms, args.depth, f"{ms}ms")
            print(f"  solved {r['hits']}/{r['n']}  ({r['rate'] * 100:.1f}%)  "
                  f"avg depth {r['avg_depth']:.1f}  {r['nps']} nps  "
                  f"{r['seconds']:.1f}s")
    print("Speed:")
    speed_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
