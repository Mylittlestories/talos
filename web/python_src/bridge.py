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
from typing import Any, Dict, Optional

import chess

from lc.anarchess.ai import AnarchessBot
from lc.anarchess.rules import (SOLO_PERFECT_SCORE, AnarchessAction,
                            AnarchessGame, AnarchessRules)
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
# The dials a browser client is allowed to set.  ``random_colour`` and
# ``attack_needs_support`` survive as read-only properties for old callers, so
# the guard below skips anything that cannot be assigned.
ANARCHESS_RULE_FIELDS = (
    "tiles_per_colour", "draw_tile_colour", "single_touch_opposite",
    "diagonal_attack", "captives_return", "pawn_action_on_last_tile",
    "protect_last_move", "tax_largest_area", "same_colour_bonus",
    "reserve_penalty", "min_area", "solo", "checkers")


def _rules_from(data: Any) -> AnarchessRules:
    rules = AnarchessRules()
    payload = dict(_loads(data) or {})
    mode = payload.pop("mode", None)
    for key, value in payload.items():
        if key not in ANARCHESS_RULE_FIELDS:
            continue
        if isinstance(getattr(type(rules), key, None), property):
            continue                       # a compatibility alias, not a dial
        setattr(rules, key, value)
    if mode == "solo":
        rules.solo, rules.checkers = True, False
    elif mode == "checkers":
        rules.solo, rules.checkers = False, True
    return rules


def _snapshot(game: AnarchessGame) -> Dict[str, Any]:
    areas = []
    largest = max((len(g) for g in game.areas()), default=0)
    for group in game.areas():
        owner = game.area_control(group)
        areas.append({"size": len(group),
                      "owner": owner,
                      "rate": game.area_tile_rate(
                          group, game.current if owner is None else owner,
                          largest),
                      "taxed": bool(game.rules.tax_largest_area
                                    and len(group) == largest),
                      "cells": [list(cell) for cell in group]})
    return {
        "players": game.players,
        "names": list(game.names),
        "rules": {k: getattr(game.rules, k) for k in ANARCHESS_RULE_FIELDS},
        "largest": largest,
        "target": SOLO_PERFECT_SCORE if game.rules.solo else None,
        "solo_score": game.solo_score() if game.rules.solo else None,
        "tiles": [[x, y, 1 if colour else 0] for (x, y), colour in game.tiles.items()],
        "pawns": [[x, y, owner] for (x, y), owner in game.pawns.items()],
        "current": game.current,
        # In SOLO the person controls both tribes, but the pawn action belongs
        # to the tribe opposite the tile just laid. Make that actor explicit
        # so browser controls never guess from the turn owner.
        "pawn_player": (game.acting_pawn_player() if game.placed_tile
                        else game.current),
        "turn": game.turn_number,
        "placed": game.placed_tile,
        "last_tile": list(game.last_tile) if game.last_tile else None,
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
    # AnarchessGame normalises SOLO to its two original tribes.  Trim old
    # snapshots too: an early browser build could save a solo game with 3–4
    # reserves, which would distort its score when restored.
    requested_players = int(state.get("players", 2))
    players = 2 if rules.solo else max(2, min(4, requested_players))
    names = state.get("names")
    game = AnarchessGame(players, rules,
                         names=None if names is None else list(names)[:players])
    game.tiles = {(int(x), int(y)): bool(colour)
                  for x, y, colour in state.get("tiles", [])}
    game.pawns = {(int(x), int(y)): int(owner)
                  for x, y, owner in state.get("pawns", [])
                  if 0 <= int(owner) < game.players}
    game.supply = {True: int(state.get("supply", {}).get("light", 32)),
                   False: int(state.get("supply", {}).get("dark", 32))}
    saved_reserve = list(state.get("reserve", game.reserve))
    game.reserve = [int(saved_reserve[i]) if i < len(saved_reserve)
                    else game.reserve[i] for i in range(game.players)]
    game.current = int(state.get("current", 0)) % game.players
    game.turn_number = int(state.get("turn", 1))
    game.placed_tile = bool(state.get("placed", False))
    last = state.get("last_tile")
    # A pawn may only be settled onto the tile that was just laid, so a
    # snapshot that forgets it comes back unable to settle at all.
    game.last_tile = (int(last[0]), int(last[1])) if last else None
    game.used_pawn_action = bool(state.get("used", False))
    game.finished = bool(state.get("finished", False))
    if state.get("final"):
        final = [int(v) for v in state["final"]]
        game.scores = (final + [0] * game.players)[:game.players]
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
    parsed_rules = _rules_from(rules)
    players = 2 if parsed_rules.solo else max(2, min(4, int(players)))
    game = AnarchessGame(players, parsed_rules, seed=seed)
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
