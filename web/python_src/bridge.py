"""
bridge.py — the JSON API the browser talks to.

This is the only file in the web build that is written for the web. Everything
it calls is the real, unmodified TALOS code: the same engine that plays on the
desktop, the same Anarchchess board class, the same Anarchess rules and bot.

The calling convention is deliberately boring: JSON in, JSON out. The worker
in js/engine.worker.js calls these functions and posts the result back.

    analyse(fen, level, movetime_ms, variant, rules)  -> a move and its score
    position(fen, variant, rules)                     -> what is legal now
    levels()                                          -> the strength ladder
    anarch_rules()                                    -> the Anarchchess switches
    anarchess_new / _legal / _apply / _bot            -> the land before Chess
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import chess

from lc.anarchess.ai import AnarchessBot
from lc.anarchess.rules import (AnarchessAction, AnarchessGame, AnarchessRules,
                               LIGHT)
from lc.core.engine import DEFAULT_LEVELS, LCEngine, Level, level_by_name
from lc.variants.anarchchess import AnarchBoard, AnarchRules, RULE_BOOK

_ENGINE: Optional[LCEngine] = None


def _loads(value: Any) -> Optional[Dict[str, Any]]:
    """Accept a dict or a JSON string - the worker always sends strings."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


# --------------------------------------------------------------------------
# chess
# --------------------------------------------------------------------------
def _board(fen: str, variant: str = "standard",
           rules: Any = None) -> chess.Board:
    rules = _loads(rules)
    if variant in ("anarchchess", "anarchy"):
        base = AnarchRules()
        for key, value in (rules or {}).items():
            if hasattr(base, key):
                setattr(base, key, bool(value))
        return AnarchBoard(fen or chess.STARTING_FEN, rules=base)
    return chess.Board(fen or chess.STARTING_FEN)


def _engine_for(level_name: str, movetime_ms: int) -> LCEngine:
    global _ENGINE
    level = level_by_name(level_name)
    level = Level(level.name, level.elo, max_depth=level.max_depth,
                  movetime_ms=movetime_ms, blunder=getattr(level, "blunder", 0.0),
                  inaccuracy=getattr(level, "inaccuracy", 0.0),
                  noise=getattr(level, "noise", 0),
                  skill=getattr(level, "skill", 20))
    if _ENGINE is None:
        _ENGINE = LCEngine(level, seed=1)
    else:
        _ENGINE.level = level
    return _ENGINE


def _app_version() -> str:
    """The version this build was stamped with.

    ``tools/build_web.py`` copies this file into the browser bundle and
    replaces the placeholder with the real version, because ``lc/__init__.py``
    is not part of the bundle. Running from source, ask the package instead.
    """
    try:
        from lc import APP_VERSION
        return APP_VERSION
    except Exception:
        return "__APP_VERSION__"


def about() -> str:
    """What the page shows in the Rules tab and the footer."""
    return json.dumps({
        "app": "TALOS",
        "version": _app_version(),
        "python": sys.version.split()[0],
        "pyodide": sys.platform,
        "chess": getattr(chess, "__version__", "unknown"),
        "levels": len(DEFAULT_LEVELS),
        "rules": len(RULE_BOOK),
    })


def levels() -> str:
    return json.dumps([{"name": lv.name, "elo": lv.elo,
                        "movetime": lv.movetime_ms}
                       for lv in DEFAULT_LEVELS])


def position(fen: str, variant: str = "standard", rules: Any = None) -> str:
    """Everything the UI needs to draw the position and take a move."""
    board = _board(fen, variant, rules)
    moves = []
    sans = {}
    for move in board.legal_moves:
        uci = move.uci()
        moves.append(uci)
        try:
            sans[uci] = board.san(move)
        except Exception:
            sans[uci] = uci
    check = board.is_check()
    king = board.king(board.turn)
    return json.dumps({
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "moves": moves,
        "san": sans,
        "check": check,
        "check_square": king if check else None,
        "over": board.is_game_over(),
        "result": board.result() if board.is_game_over() else "*",
        "material": _material(board),
        "knooks": sorted(getattr(board, "knooks", []) or []),
        "status": getattr(board, "status_line", lambda: "")(),
    })


def push(fen: str, uci: str, variant: str = "standard", rules: Any = None) -> str:
    """Play a move and return the new position. Keeps the UI honest: the
    browser never has to re-implement move generation."""
    try:
        board = _board(fen, variant, rules)
        move = chess.Move.from_uci(str(uci))
        if move not in board.legal_moves:
            # a bare "e7e8" promotion click falls back to the queen
            for candidate in board.legal_moves:
                if (candidate.from_square == move.from_square
                        and candidate.to_square == move.to_square):
                    move = candidate
                    break
        if move not in board.legal_moves:
            return json.dumps({"ok": False, "error": "illegal move"})
        san = board.san(move)
        board.push(move)
        data = json.loads(position(board.fen(), variant, rules))
        data["ok"] = True
        data["played"] = move.uci()
        data["played_san"] = san
        return json.dumps(data)
    except Exception as exc:                                  # pragma: no cover
        return json.dumps({"ok": False, "error": str(exc)})


def _material(board: chess.Board) -> Dict[str, int]:
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
              chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    out = {"white": 0, "black": 0}
    for square, piece in board.piece_map().items():
        out["white" if piece.color == chess.WHITE else "black"] += values.get(
            piece.piece_type, 0)
    return out


def analyse(fen: str, level: str = "Club", movetime_ms: int = 900,
            variant: str = "standard", rules: Any = None) -> str:
    """Search the position and describe the best move."""
    board = _board(fen, variant, rules)
    if board.is_game_over():
        return json.dumps({"bestmove": None, "over": True,
                           "result": board.result()})
    engine = _engine_for(level, movetime_ms)
    try:
        result = engine.search(board, movetime_ms=movetime_ms, max_depth=64)
    except Exception as exc:                      # never break the page
        return json.dumps({"error": str(exc)})
    move = result.bestmove
    if move is None:
        return json.dumps({"bestmove": None, "over": True,
                           "result": board.result()})
    try:
        san = board.san(move)
    except Exception:
        san = move.uci()
    pv = []
    try:
        probe = board.copy(stack=False)
        for pv_move in result.pv[:8]:
            pv.append(probe.san(pv_move))
            probe.push(pv_move)
    except Exception:
        pv = []
    return json.dumps({
        "bestmove": move.uci(),
        "san": san,
        "score": result.score,
        "mate": result.mate,
        "depth": result.depth,
        "nodes": result.nodes,
        "time_ms": result.time_ms,
        "pv": pv,
        "knooks": sorted(getattr(board, "knooks", []) or []),
    })


def anarch_rules() -> str:
    """The Anarchchess switches, for the rule editor."""
    curated = AnarchRules()
    anarchy = AnarchRules(omnipotent_pawn=True, promotion_roulette=True,
                          bongcloud_wins=True, random_events=True)
    return json.dumps({
        "rules": [{"key": key, "title": title, "tip": tip}
                  for key, title, tip in RULE_BOOK],
        "presets": {"anarchchess": curated.as_dict() if hasattr(curated, "as_dict")
                    else vars(curated),
                    "anarchy": anarchy.as_dict() if hasattr(anarchy, "as_dict")
                    else vars(anarchy)},
    })


# --------------------------------------------------------------------------
# Anarchess
# --------------------------------------------------------------------------
def _rules_from(data: Any) -> AnarchessRules:
    rules = AnarchessRules()
    for key, value in (_loads(data) or {}).items():
        if hasattr(rules, key):
            setattr(rules, key, value)
    return rules


def _snapshot(game: AnarchessGame) -> Dict[str, Any]:
    areas = []
    for group in game.areas():
        areas.append({"size": len(group),
                      "owner": game.area_control(group),
                      "cells": [list(cell) for cell in group]})
    return {
        "players": game.players,
        "names": list(game.names),
        "rules": {k: getattr(game.rules, k) for k in
                  ("random_colour", "captives_return", "attack_needs_support",
                   "score_per_tile", "final_tile_ends_game")},
        "tiles": [[x, y, 1 if colour else 0] for (x, y), colour in game.tiles.items()],
        "pawns": [[x, y, owner] for (x, y), owner in game.pawns.items()],
        "current": game.current,
        "turn": game.turn_number,
        "placed": game.placed_tile,
        "used": game.used_pawn_action,
        "finished": game.finished,
        "drawn": game.drawn,
        "reserve": list(game.reserve),
        "supply": {"light": game.supply.get(True, 0), "dark": game.supply.get(False, 0)},
        "left": game.tiles_left(),
        "scores": game.live_scores(),
        "final": list(game.scores) if game.finished else None,
        "winner": game.winner(),
        "areas": areas,
        "status": game.status(),
    }


def _restore(state: Any) -> AnarchessGame:
    state = _loads(state) or {}
    rules = _rules_from(state.get("rules"))
    game = AnarchessGame(int(state.get("players", 2)), rules,
                         names=state.get("names"))
    game.tiles = {(int(x), int(y)): bool(colour)
                  for x, y, colour in state.get("tiles", [])}
    game.pawns = {(int(x), int(y)): int(owner)
                  for x, y, owner in state.get("pawns", [])}
    game.supply = {True: int(state.get("supply", {}).get("light", 32)),
                   False: int(state.get("supply", {}).get("dark", 32))}
    game.reserve = list(state.get("reserve", game.reserve))
    game.current = int(state.get("current", 0))
    game.turn_number = int(state.get("turn", 1))
    game.placed_tile = bool(state.get("placed", False))
    game.used_pawn_action = bool(state.get("used", False))
    game.finished = bool(state.get("finished", False))
    game.drawn = state.get("drawn", None)
    return game


def _action_from(data: Any) -> AnarchessAction:
    data = _loads(data) or {}
    kind = data.get("kind", "pass")
    if kind == "tile":
        return AnarchessAction("tile", cell=(int(data["x"]), int(data["y"])),
                               colour=bool(data.get("colour", True)))
    if kind in ("settle", "move", "attack"):
        source = data.get("fx")
        return AnarchessAction(
            kind, cell=(int(data["x"]), int(data["y"])),
            source=None if source is None else (int(source), int(data["fy"])))
    return AnarchessAction("pass")


def anarchess_new(players: int = 2, rules: Any = None,
                  seed: Optional[int] = None) -> str:
    game = AnarchessGame(max(2, min(4, int(players))), _rules_from(rules),
                         seed=seed)
    return json.dumps(_snapshot(game))


def anarchess_legal(state: Any) -> str:
    game = _restore(state)
    tiles, pawns, can_pass = [], [], False
    for action in game.legal_actions():
        if action.kind == "tile" and action.cell is not None:
            tiles.append({"x": action.cell[0], "y": action.cell[1],
                          "colour": 1 if action.colour else 0})
        elif action.kind == "settle" and action.cell is not None:
            pawns.append({"kind": "settle", "x": action.cell[0],
                          "y": action.cell[1], "fx": None, "fy": None})
        elif action.cell is not None and action.source is not None:
            pawns.append({"kind": action.kind, "x": action.cell[0],
                          "y": action.cell[1], "fx": action.source[0],
                          "fy": action.source[1]})
        elif action.kind == "pass":
            can_pass = True
    return json.dumps({"tiles": tiles, "pawns": pawns, "can_pass": can_pass})


def anarchess_apply(state: Any, action: Any) -> str:
    game = _restore(state)
    ok = game.apply(_action_from(action))
    return json.dumps({"ok": ok, "state": _snapshot(game)})


def anarchess_bot(state: Any, level: int = 2, seed: Optional[int] = None) -> str:
    """Ask the built-in bot for this turn's actions (tile, then pawn action)."""
    game = _restore(state)
    if game.finished:
        return json.dumps({"actions": []})
    bot = AnarchessBot(game.current, max(1, min(3, int(level))), seed=seed)
    actions = []
    try:
        for action in bot.choose(game):
            if action.kind == "tile" and action.cell is not None:
                actions.append({"kind": "tile", "x": action.cell[0],
                                "y": action.cell[1],
                                "colour": 1 if action.colour else 0})
            elif action.cell is not None:
                source = action.source
                actions.append({"kind": action.kind, "x": action.cell[0],
                                "y": action.cell[1],
                                "fx": None if source is None else source[0],
                                "fy": None if source is None else source[1]})
            else:
                actions.append({"kind": "pass"})
    except Exception as exc:
        return json.dumps({"error": str(exc), "actions": []})
    return json.dumps({"actions": actions})
