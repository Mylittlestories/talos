#!/usr/bin/env python3
"""
A minimal UCI engine used to test the UCI driver without Stockfish.

Speaks just enough of the protocol (uci / isready / setoption / position /
go / stop / quit) and answers with a random legal move plus a plausible info
line, exactly like a real engine would.

    python tools/fake_uci_engine.py
"""

from __future__ import annotations

import random
import sys

import chess


def main() -> int:
    board = chess.Board()
    searching = False
    rng = random.Random()
    # readline() rather than `for line in sys.stdin`: iterating a text stream
    # uses read-ahead buffering, which delays commands in a pipe
    while True:
        raw = sys.stdin.readline()
        if not raw:
            break
        command = raw.strip()
        if not command:
            continue
        if command == "uci":
            print("id name FakeUCI 0.1")
            print("id author Lucas Chess NX self test")
            print("option name MultiPV type spin default 1 min 1 max 8")
            print("option name Skill Level type spin default 20 min 0 max 20")
            print("option name UCI_Elo type spin default 3190 min 1320 max 3190")
            print("option name UCI_LimitStrength type check default false")
            print("option name Threads type spin default 1 min 1 max 16")
            print("uciok")
        elif command == "isready":
            print("readyok")
        elif command.startswith("setoption"):
            pass
        elif command == "ucinewgame":
            board = chess.Board()
        elif command.startswith("position"):
            tokens = command.split()
            if "fen" in tokens:
                index = tokens.index("fen") + 1
                fen = " ".join(tokens[index:index + 6])
                board = chess.Board(fen)
                rest = tokens[index + 6:]
            else:
                board = chess.Board()
                rest = tokens[1:]
            if rest and rest[0] == "moves":
                rest = rest[1:]
            for uci in rest:
                try:
                    board.push(chess.Move.from_uci(uci))
                except Exception:
                    break
        elif command.startswith("go"):
            searching = True
            moves = list(board.legal_moves)
            if not moves:
                print("bestmove 0000")
            else:
                move = rng.choice(moves)
                score = rng.randint(-80, 80)
                print(f"info depth 3 score cp {score} nodes 1234 time 20 pv {move.uci()}")
                searching = False
                print(f"bestmove {move.uci()}")
        elif command == "stop":
            # like a real engine: only answer when a search is running
            if searching:
                searching = False
                moves = list(board.legal_moves)
                print(f"bestmove {moves[0].uci()}" if moves else "bestmove 0000")
        elif command == "quit":
            break
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
