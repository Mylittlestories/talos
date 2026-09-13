"""
Battle Chess 3D board.

An OpenGL widget that mirrors the game position and, on every capture, stages
a small fight: the attacker closes in, strikes, and the defender is destroyed
in a shower of physically simulated shards.  Everything (geometry, choreography,
particles) is generated at runtime - no art assets, no network.

The widget is a drop-in replacement for the 2D BoardView: it emits
`moveRequested` and is fed by `sync_position()` / `play_move()`.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import chess

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QFont, QPainter, QColor
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from . import meshes
from .physics import PhysicsWorld

try:
    from OpenGL import GL
    from OpenGL.GL import glCallList, glGenLists
    OPENGL_OK = True
except Exception as exc:                                   # pragma: no cover
    OPENGL_OK = False
    OPENGL_ERROR = str(exc)

from . import glmat


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def board_from_fen(fen: str) -> chess.Board:
    """Variant aware FEN parsing (crazyhouse FENs carry pocket information)."""
    if "[" in fen:
        import chess.variant
        try:
            return chess.variant.CrazyhouseBoard(fen)
        except Exception:
            pass
    try:
        return chess.Board(fen)
    except Exception:
        import chess.variant
        for name in ("CrazyhouseBoard", "AtomicBoard", "ThreeCheckBoard", "KingOfTheHillBoard",
                     "HordeBoard", "RacingKingsBoard", "AntichessBoard", "GiveawayBoard",
                     "SuicideBoard"):
            try:
                return getattr(chess.variant, name)(fen)
            except Exception:
                continue
        return chess.Board()


def square_to_xz(square: chess.Square, flipped: bool = False) -> Tuple[float, float]:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    if flipped:
        file, rank = 7 - file, 7 - rank
    return (file - 3.5, 3.5 - rank)


def xz_to_square(x: float, z: float, flipped: bool = False) -> Optional[chess.Square]:
    file = int(math.floor(x + 4.0))
    rank = int(math.floor(4.0 - z))
    if flipped:
        file, rank = 7 - file, 7 - rank
    if not (0 <= file < 8 and 0 <= rank < 8):
        return None
    return chess.square(file, rank)


PIECE_NAMES = {chess.PAWN: "pawn", chess.ROOK: "rook", chess.KNIGHT: "knight",
               chess.BISHOP: "bishop", chess.QUEEN: "queen", chess.KING: "king"}

WHITE_COLOR = (0.94, 0.91, 0.83)
BLACK_COLOR = (0.20, 0.21, 0.25)
WHITE_ACCENT = (0.85, 0.72, 0.42)
BLACK_ACCENT = (0.55, 0.20, 0.18)


# --------------------------------------------------------------------------
# animated piece
# --------------------------------------------------------------------------

@dataclass
class Piece3D:
    piece: chess.Piece
    square: chess.Square
    x: float = 0.0
    z: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    scale: float = 1.0
    sy: float = 1.0               # vertical squash (crushed pieces)
    alive: bool = True
    fade: float = 1.0
    wobble: float = 0.0


@dataclass
class Fight:
    """One capture, stage by stage."""
    attacker: Piece3D
    victim: chess.Piece
    victim_square: chess.Square
    victim_x: float
    victim_z: float
    to_square: chess.Square
    move: chess.Move
    t: float = 0.0
    duration: float = 1.65
    style: str = "smash"
    stage: str = "approach"
    impacted: bool = False
    finished: bool = False
    slide_from: Tuple[float, float] = (0.0, 0.0)
    is_ep: bool = False
    promotion: Optional[int] = None
    victim_ref: Optional[object] = None    # the Piece3D being killed
    choreo: str = "shatter"
    impact_time: float = 0.0
    gore: bool = True
    dir_x: float = 0.0
    dir_z: float = 1.0


@dataclass
class Walk:
    piece_ref: Piece3D
    from_x: float
    from_z: float
    to_x: float
    to_z: float
    to_square: chess.Square
    move: chess.Move
    t: float = 0.0
    duration: float = 0.42
    hop: float = 0.55
    promotion: Optional[int] = None
    finished: bool = False


# --------------------------------------------------------------------------
# widget
# --------------------------------------------------------------------------

class BattleBoardWidget(QOpenGLWidget):
    moveRequested = pyqtSignal(object)
    #: Emitted once, the first time drawing fails, with the reason.
    glFailed = pyqtSignal(str)

    # distances are tuned for a 42 degree vertical field of view: the whole
    # board (9.1 units including the frame) has to fit with a small margin
    CAMERAS = {
        "Classic": dict(yaw=0.0, pitch=0.95, dist=15.6),
        "Cinematic": dict(yaw=0.45, pitch=0.70, dist=14.6),
        "Top-down": dict(yaw=0.0, pitch=1.38, dist=14.2),
    }

    def __init__(self, parent: Optional[QWidget] = None, settings: Optional[Dict] = None,
                 sounds=None):
        if not OPENGL_OK:
            raise RuntimeError(f"PyOpenGL is not available ({OPENGL_ERROR})")
        super().__init__(parent)
        self.settings = dict(settings or {})
        self.sounds = sounds
        self.rng = random.Random(20240)
        self.pieces: Dict[chess.Square, Piece3D] = {}
        self.board = chess.Board()
        self.flipped = False
        self.selected: Optional[chess.Square] = None
        self.last_move: Optional[chess.Move] = None
        self.hover: Optional[chess.Square] = None
        self.fights: List[Fight] = []
        self.walks: List[Walk] = []
        self.physics = PhysicsWorld(self.rng)
        self.quality = self.settings.get("battle_quality", "High")
        gore = self.settings.get("battle_gore", "Classic")
        if gore is True:
            gore = "Classic"
        elif gore is False:
            gore = "Arcade"
        self.gore = gore if gore in ("Classic", "Arcade") else "Classic"
        self.camera_mode = self.settings.get("battle_camera", "Cinematic")
        cam = self.CAMERAS.get(self.camera_mode, self.CAMERAS["Cinematic"])
        self.yaw = cam["yaw"]
        self.pitch = cam["pitch"]
        self.distance = cam["dist"]
        self.target_yaw = self.yaw
        self.target_pitch = self.pitch
        self.shake = 0.0
        self.target = (0.0, -0.75, 0.0)     # camera look-at point (centres the board)
        self.time = 0.0
        self._lists: Dict[str, int] = {}
        self._ready = False
        self._painted = False        # flips true on the first good frame
        self._orbiting = False
        self._last_pos = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(360, 360)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.setAutoFillBackground(False)

    # -- settings ---------------------------------------------------------
    def apply_settings(self, settings: Dict) -> None:
        self.settings = dict(settings)
        quality = self.settings.get("battle_quality", "High")
        if quality != self.quality:
            self.quality = quality
            if self._ready:
                self._build_lists()
        self.gore = self.settings.get("battle_gore", self.gore)
        self.set_camera_mode(self.settings.get("battle_camera", "Cinematic"))

    def set_camera_mode(self, mode: str) -> None:
        if mode in self.CAMERAS:
            self.camera_mode = mode
            cam = self.CAMERAS[mode]
            self.target_yaw = cam["yaw"]
            self.target_pitch = cam["pitch"]
            self.distance = cam["dist"]

    # -- position sync -----------------------------------------------------
    def sync_position(self, board: chess.Board, animate: bool = False,
                      clear_effects: bool = True) -> None:
        self.board = board.copy(stack=False)
        self.pieces = {}
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece is None:
                continue
            x, z = square_to_xz(square, self.flipped)
            self.pieces[square] = Piece3D(piece=piece, square=square, x=x, z=z)
        if clear_effects:
            self.fights.clear()
            self.walks.clear()
            self.physics.clear()
        self.update()

    def play_move(self, record) -> None:
        """Animate a move that already happened in the game model."""
        move = record.move
        board_before = board_from_fen(record.fen_before)
        piece = board_before.piece_at(move.from_square)
        if piece is None:
            self.sync_position(chess.Board(record.fen_after))
            return
        attacker = self.pieces.pop(move.from_square, None)
        if attacker is None:
            x, z = square_to_xz(move.from_square, self.flipped)
            attacker = Piece3D(piece=piece, square=move.from_square, x=x, z=z)
        self.selected = None
        self.last_move = move

        captured: Optional[chess.Piece] = None
        captured_square: Optional[chess.Square] = None
        if record.capture is not None:
            captured = record.capture
            captured_square = record.captured_square or move.to_square

        if captured is not None and self.settings.get("battle_captures", True):
            victim = self.pieces.pop(captured_square, None)
            vx, vz = square_to_xz(captured_square, self.flipped)
            if victim is None:
                victim = Piece3D(piece=captured, square=captured_square, x=vx, z=vz)
            fight = Fight(attacker=attacker, victim=captured, victim_square=captured_square,
                          victim_x=vx, victim_z=vz, to_square=move.to_square, move=move,
                          style=self._style_for(piece, captured),
                          slide_from=(attacker.x, attacker.z),
                          is_ep=record.is_en_passant, promotion=move.promotion,
                          victim_ref=victim, choreo=self._choreography(piece, captured),
                          gore=self.gore != "Arcade")
            dx = vx - attacker.x
            dz = vz - attacker.z
            length = math.hypot(dx, dz) or 1.0
            fight.dir_x, fight.dir_z = dx / length, dz / length
            self.fights.append(fight)
        else:
            tx, tz = square_to_xz(move.to_square, self.flipped)
            walk = Walk(piece_ref=attacker, from_x=attacker.x, from_z=attacker.z,
                        to_x=tx, to_z=tz,
                        to_square=move.to_square, move=move,
                        promotion=move.promotion,
                        hop=1.15 if piece.piece_type == chess.KNIGHT else 0.28,
                        duration=0.52 if piece.piece_type == chess.KNIGHT else 0.40)
            self.walks.append(walk)
        self.board = board_from_fen(record.fen_after)
        # castling also moves the rook
        if record.is_castle:
            if move.to_square > move.from_square:
                rook_from, rook_to = move.to_square + 1, move.to_square - 1
            else:
                rook_from, rook_to = move.to_square - 2, move.to_square + 1
            rook = self.pieces.pop(rook_from, None)
            if rook is not None and rook_from in chess.SQUARES:
                rx, rz = square_to_xz(rook_to, self.flipped)
                walk = Walk(piece_ref=rook, from_x=rook.x, from_z=rook.z,
                            to_x=rx, to_z=rz,
                            to_square=rook_to, move=chess.Move(rook_from, rook_to),
                            hop=0.2, duration=0.6)
                self.walks.append(walk)
        self.update()

    @staticmethod
    def _style_for(attacker: chess.Piece, victim: chess.Piece) -> str:
        table = {
            chess.PAWN: "stab", chess.KNIGHT: "slash", chess.BISHOP: "beam",
            chess.ROOK: "smash", chess.QUEEN: "shock", chess.KING: "hammer",
        }
        return table.get(attacker.piece_type, "smash")

    @staticmethod
    def _choreography(attacker: chess.Piece, victim: chess.Piece) -> str:
        """What actually happens to the losing piece.

        The 1988 original gave every capture its own little murder, and the
        victim decided a lot of it: kings lose their heads, pawns get knocked
        over like skittles, and anything the bishop touches is simply gone.
        """
        if victim.piece_type == chess.KING:
            return "behead"
        if victim.piece_type == chess.PAWN:
            return "topple"
        table = {
            chess.PAWN: "impale", chess.KNIGHT: "behead", chess.BISHOP: "disintegrate",
            chess.ROOK: "flatten", chess.QUEEN: "shatter", chess.KING: "flatten",
        }
        return table.get(attacker.piece_type, "shatter")

    # -- animation ---------------------------------------------------------
    def _tick(self) -> None:
        try:
            self._step(0.016)
        except Exception as exc:                            # pragma: no cover
            self._gl_fail(exc)

    def _step(self, dt: float) -> None:
        self.time += dt
        self.yaw += (self.target_yaw - self.yaw) * 0.08
        self.pitch += (self.target_pitch - self.pitch) * 0.08
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt * 2.4)
        self.physics.step(dt)
        busy = False

        for walk in list(self.walks):
            walk.t += dt
            progress = min(1.0, walk.t / walk.duration)
            eased = progress * progress * (3 - 2 * progress)
            ref = walk.piece_ref
            ref.x = walk.from_x + (walk.to_x - walk.from_x) * eased
            ref.z = walk.from_z + (walk.to_z - walk.from_z) * eased
            ref.y = math.sin(math.pi * progress) * walk.hop * 0.35
            ref.yaw = math.sin(progress * math.tau) * 0.12
            if progress >= 1.0:
                ref.y = 0.0
                ref.yaw = 0.0
                if walk.promotion:
                    ref.piece = chess.Piece(walk.promotion, ref.piece.color)
                    head = [walk.to_x, 0.8, walk.to_z]
                    self.physics.burst(head, (1.0, 0.9, 0.5), count=30, power=2.0)
                ref.square = walk.to_square
                self.pieces[walk.to_square] = ref
                self.walks.remove(walk)
                self._after_animation()
            busy = True

        for fight in list(self.fights):
            self._step_fight(fight, dt)
            busy = True
            if fight.finished:
                self.fights.remove(fight)
                self._after_animation()

        if busy or self.physics.shards or self.physics.sparks or self.shake > 0:
            self.update()

    def _after_animation(self) -> None:
        """Re-sync once all animations are done so the scene matches the model."""
        if self.walks or self.fights:
            return
        try:
            self.sync_position(self.board, clear_effects=False)
        except Exception:
            pass

    def _step_fight(self, fight: Fight, dt: float) -> None:
        fight.t += dt
        a = fight.attacker
        # positions
        start_x, start_z = fight.slide_from
        tx, tz = square_to_xz(fight.to_square, self.flipped)
        dx, dz = fight.victim_x - start_x, fight.victim_z - start_z
        dist = math.hypot(dx, dz) or 1.0
        ux, uz = dx / dist, dz / dist
        face = math.atan2(uz, ux)

        APPROACH, STRIKE, IMPACT, RETURN = 0.42, 0.34, 0.14, 0.42
        total = APPROACH + STRIKE + IMPACT + RETURN
        p = fight.t

        if p < APPROACH:
            k = p / APPROACH
            eased = k * k
            a.yaw = face
            a.x = start_x + (fight.victim_x - ux * 1.15 - start_x) * eased
            a.z = start_z + (fight.victim_z - uz * 1.15 - start_z) * eased
            a.y = abs(math.sin(k * math.pi * 3)) * 0.06
            fight.stage = "approach"
        elif p < APPROACH + STRIKE:
            k = (p - APPROACH) / STRIKE
            a.yaw = face
            a.x = fight.victim_x - ux * 1.15
            a.z = fight.victim_z - uz * 1.15
            if fight.style == "smash":
                a.y = math.sin(k * math.pi) * 0.9
                a.pitch = -k * 0.9
            elif fight.style == "hammer":
                a.y = 0.05 + math.sin(min(1.0, k * 1.6) * math.pi * 0.5) * 0.35
                a.pitch = -math.sin(min(1.0, k * 1.6) * math.pi * 0.5) * 1.2
            elif fight.style == "slash":
                a.yaw = face + math.sin(k * math.pi) * 1.5
                a.y = 0.12 + math.sin(k * math.pi) * 0.22
            elif fight.style == "stab":
                a.pitch = math.sin(k * math.pi) * 0.35
                a.x += ux * math.sin(k * math.pi) * 0.25
                a.z += uz * math.sin(k * math.pi) * 0.25
            elif fight.style == "beam":
                a.y = 0.05 + k * 0.12
                a.pitch = -k * 0.25
            else:      # shock
                a.yaw = face + k * math.tau
                a.y = math.sin(k * math.pi) * 0.55
            fight.stage = "strike"
        elif p < APPROACH + STRIKE + IMPACT:
            if not fight.impacted:
                fight.impact_time = fight.t
                self._impact(fight)
                fight.impacted = True
            fight.stage = "impact"
            self._step_victim(fight, dt)
        else:
            k = (p - APPROACH - STRIKE - IMPACT) / RETURN
            eased = 1 - (1 - k) ** 2
            self._step_victim(fight, dt)
            a.x = (fight.victim_x - ux * 1.15) + (tx - (fight.victim_x - ux * 1.15)) * eased
            a.z = (fight.victim_z - uz * 1.15) + (tz - (fight.victim_z - uz * 1.15)) * eased
            a.y = math.sin(eased * math.pi) * 0.12
            a.pitch *= 0.8
            a.roll *= 0.8
            a.yaw = face * (1 - eased)
            fight.stage = "return"
            if k >= 1.0:
                a.x, a.z, a.y, a.yaw, a.pitch, a.roll = tx, tz, 0.0, 0.0, 0.0, 0.0
                if fight.promotion:
                    a.piece = chess.Piece(fight.promotion, a.piece.color)
                    self.physics.burst([tx, 0.8, tz], (1.0, 0.9, 0.5), count=30, power=2.0)
                a.square = fight.to_square
                self.pieces[fight.to_square] = a
                fight.finished = True

    # -- gore ------------------------------------------------------------
    # The victim keeps standing while the attacker winds up, then dies in the
    # way its killer and its own rank deserve.  Everything here is procedural:
    # there is no animation library, just a few curves per choreography.
    BLOOD = (0.52, 0.03, 0.04)
    DUST = (0.72, 0.68, 0.60)

    def _step_victim(self, fight: Fight, dt: float) -> None:
        v = fight.victim_ref
        if v is None or not v.alive:
            return
        g = fight.t - fight.impact_time          # seconds since the blow landed
        if fight.choreo == "behead":
            # the body tips over where it stands and is gone in half a second
            k = min(1.0, g / 0.55)
            v.pitch = -1.55 * (k * k)
            v.y = -0.22 * k
            v.scale = max(0.001, 1.0 - max(0.0, (g - 0.45) / 0.35))
            if v.scale <= 0.01:
                v.alive = False
        elif fight.choreo == "flatten":
            k = min(1.0, g / 0.22)
            v.sy = 1.0 - 0.86 * k
            v.scale = 1.0 + 0.30 * k
            if g > 0.30:
                v.scale = max(0.001, v.scale - dt * 4.0)
                if v.scale <= 0.02:
                    v.alive = False
                    self.physics.shatter([v.x, 0.05, v.z], self._victim_colour(fight),
                                         count=10 if self.gore != "Arcade" else 14,
                                         power=0.8)
        elif fight.choreo == "impale":
            k = min(1.0, g / 0.85)
            v.y = 1.05 * math.sin(min(1.0, g / 0.5) * math.pi * 0.5)
            v.x += fight.dir_x * dt * 3.4 * (1.0 - k * 0.4)
            v.z += fight.dir_z * dt * 3.4 * (1.0 - k * 0.4)
            v.y = max(0.0, v.y - max(0.0, g - 0.5) * 5.2)
            v.pitch = -k * 3.2
            v.scale = max(0.001, 1.0 - max(0.0, (g - 0.55) / 0.30))
            if v.scale <= 0.01:
                v.alive = False
        elif fight.choreo == "disintegrate":
            k = min(1.0, g / 0.6)
            v.y = -0.42 * k
            v.scale = max(0.001, 1.0 - k)
            v.yaw += dt * 5.0 * (1.0 - k)
            if v.scale <= 0.01:
                v.alive = False
        elif fight.choreo == "topple":
            k = min(1.0, g / 0.4)
            v.roll = 1.62 * (k * k)
            v.y = 0.06 * math.sin(k * math.pi)
            if g > 0.55:
                v.scale = max(0.001, v.scale - dt * 3.4)
                if v.scale <= 0.02:
                    v.alive = False
        else:                                    # shatter - gone on contact
            v.scale = max(0.001, 1.0 - (g / 0.12))
            if v.scale <= 0.01:
                v.alive = False

    def _victim_colour(self, fight: Fight):
        return (WHITE_COLOR if fight.victim.color == chess.WHITE else BLACK_COLOR)

    def _impact(self, fight: Fight) -> None:
        a = fight.attacker
        colour = WHITE_COLOR if fight.victim.color == chess.WHITE else BLACK_COLOR
        gruesome = fight.gore and self.gore != "Arcade"
        shards = 22 if self.quality in ("High", "Ultra") else 12
        if fight.choreo in ("topple", "flatten"):
            shards = max(6, shards // 3)
        if fight.choreo == "disintegrate":
            shards = max(8, shards // 2)
        self.physics.shatter([fight.victim_x, 0.05, fight.victim_z], colour,
                             count=shards,
                             power=1.0 + (0.25 if self.quality == "Ultra" else 0.0))
        mid = [(a.x + fight.victim_x) / 2, 0.62, (a.z + fight.victim_z) / 2]
        if fight.style == "slash":
            angle = math.atan2(fight.victim_z - a.z, fight.victim_x - a.x)
            self.physics.slash(mid, angle)
            self._sound("sword")
        elif fight.style == "beam":
            self.physics.burst(mid, (0.65, 0.5, 1.0), count=40, power=2.6, spread=0.6)
            self._sound("clash")
        elif fight.style in ("smash", "hammer"):
            self.physics.burst(mid, (1.0, 0.8, 0.35), count=34, power=3.0)
            self.physics.wave([fight.victim_x, 0.2, fight.victim_z])
            self.shake = 1.0
            self._sound("clash")
        elif fight.style == "shock":
            self.physics.wave([fight.victim_x, 0.15, fight.victim_z], speed=9.0)
            self.physics.burst(mid, (1.0, 0.55, 0.85), count=46, power=3.4)
            self.shake = 0.85
            self._sound("clash")
        else:
            self.physics.burst(mid, (1.0, 0.9, 0.6), count=22, power=1.8)
            self._sound("clash")
        self._sound("shatter")
        self.shake = max(self.shake, 0.55)

        # ---- and now the mess -------------------------------------------
        head = [fight.victim_x, 1.02, fight.victim_z]
        if fight.choreo == "behead":
            if gruesome:
                self.physics.blood(head, count=42, power=1.5, upward=1.25)
                self.physics.stain(fight.victim_x, fight.victim_z,
                                   radius=0.30, color=self.BLOOD, life=8.0)
                self.physics.limb([fight.victim_x, 1.15, fight.victim_z], "head",
                                  colour, power=1.25, scale=0.42)
                self.physics.limb([fight.victim_x, 0.55, fight.victim_z], "limb",
                                  colour, power=0.85, scale=0.26)
            else:
                self.physics.burst(head, (0.95, 0.92, 0.72), count=26, power=2.0)
            self.shake = max(self.shake, 0.8)
            self._sound("shatter")
        elif fight.choreo == "impale":
            if gruesome:
                self.physics.blood([fight.victim_x, 0.75, fight.victim_z],
                                   count=34, power=1.2, spread=0.7)
                for _ in range(2):
                    self.physics.limb([fight.victim_x, 0.7, fight.victim_z], "chunk",
                                      colour, power=0.9, scale=0.22)
            self.shake = max(self.shake, 0.55)
        elif fight.choreo == "flatten":
            if gruesome:
                self.physics.blood([fight.victim_x, 0.30, fight.victim_z],
                                   count=22, power=0.7, spread=1.6, upward=0.5)
                self.physics.stain(fight.victim_x, fight.victim_z,
                                   radius=0.26, color=self.BLOOD, life=7.0)
            self.physics.wave([fight.victim_x, 0.12, fight.victim_z], speed=7.5)
            self.shake = max(self.shake, 0.9)
        elif fight.choreo == "shatter":
            if gruesome:
                self.physics.blood([fight.victim_x, 0.65, fight.victim_z],
                                   count=46, power=1.7, spread=1.3)
                self.physics.stain(fight.victim_x, fight.victim_z,
                                   radius=0.34, color=self.BLOOD, life=8.5)
                for _ in range(3):
                    self.physics.limb([fight.victim_x, 0.8, fight.victim_z], "chunk",
                                      colour, power=1.1, scale=0.24)
            self.shake = max(self.shake, 1.0)
        elif fight.choreo == "topple":
            self.physics.burst([fight.victim_x, 0.35, fight.victim_z], self.DUST,
                               count=18, power=1.1, spread=1.4)
            if gruesome:
                self.physics.blood([fight.victim_x, 0.45, fight.victim_z],
                                   count=12, power=0.8, spread=0.9, upward=0.7)
        elif fight.choreo == "disintegrate":
            self.physics.burst([fight.victim_x, 0.7, fight.victim_z], (0.65, 0.55, 0.85),
                               count=44, power=1.6, spread=0.8)

    def _sound(self, name: str) -> None:
        if self.sounds is not None:
            try:
                self.sounds.play(name)
            except Exception:
                pass

    def is_animating(self) -> bool:
        return bool(self.fights or self.walks)

    # -- OpenGL ------------------------------------------------------------
    def initializeGL(self) -> None:  # noqa: N802
        try:
            GL.glClearColor(0.07, 0.08, 0.11, 1.0)
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_LIGHTING)
            GL.glEnable(GL.GL_LIGHT0)
            GL.glEnable(GL.GL_LIGHT1)
            GL.glEnable(GL.GL_NORMALIZE)
            # no face culling: the generated meshes are not guaranteed to have
            # a consistent winding order and every piece is closed anyway
            GL.glDisable(GL.GL_CULL_FACE)
            GL.glShadeModel(GL.GL_SMOOTH)
            GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (6.0, 12.0, 6.0, 1.0))
            GL.glLightfv(GL.GL_LIGHT0, GL.GL_DIFFUSE, (1.0, 0.97, 0.90, 1.0))
            GL.glLightfv(GL.GL_LIGHT0, GL.GL_SPECULAR, (0.9, 0.9, 0.85, 1.0))
            GL.glLightfv(GL.GL_LIGHT1, GL.GL_POSITION, (-7.0, 5.0, -6.0, 1.0))
            GL.glLightfv(GL.GL_LIGHT1, GL.GL_DIFFUSE, (0.35, 0.38, 0.48, 1.0))
            GL.glLightfv(GL.GL_LIGHT1, GL.GL_SPECULAR, (0.1, 0.1, 0.15, 1.0))
            GL.glMaterialfv(GL.GL_FRONT, GL.GL_SPECULAR, (0.7, 0.7, 0.7, 1.0))
            self._build_lists()
            self._ready = True
        except Exception as exc:                            # pragma: no cover
            # No usable context or no usable lists: report it once, let the
            # window fall back to the flat board, and stop trying to draw.
            self._gl_fail(exc)

    def _build_lists(self) -> None:
        for key, lst in self._lists.items():
            try:
                GL.glDeleteLists(lst, 1)
            except Exception:
                pass
        self._lists.clear()
        for piece_type, name in PIECE_NAMES.items():
            mesh = meshes.piece_mesh(piece_type, self.quality)
            self._lists[f"piece_{name}"] = self._compile(mesh)
        self._lists["board"] = self._compile(meshes.board_mesh())
        self._lists["square"] = self._compile(meshes.square_overlay_mesh())
        self._lists["shard"] = self._compile(meshes.shard_mesh(self.rng, 10, 0.2))

    @staticmethod
    def _compile(mesh: meshes.Mesh) -> int:
        lst = glGenLists(1)
        GL.glNewList(lst, GL.GL_COMPILE)
        GL.glBegin(GL.GL_TRIANGLES)
        for i in range(0, len(mesh.vertices), 9):
            for k in range(3):
                GL.glNormal3f(mesh.normals[i + k * 3], mesh.normals[i + k * 3 + 1],
                              mesh.normals[i + k * 3 + 2])
                GL.glVertex3f(mesh.vertices[i + k * 3], mesh.vertices[i + k * 3 + 1],
                              mesh.vertices[i + k * 3 + 2])
        GL.glEnd()
        GL.glEndList()
        return lst

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        try:
            GL.glViewport(0, 0, max(1, w), max(1, h))
        except Exception as exc:                            # pragma: no cover
            self._gl_fail(exc)

    def _gl_fail(self, exc: BaseException) -> None:
        """Stop trying to draw, and tell the window to fall back to 2D."""
        import traceback

        self._ready = False
        self._gl_error = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__))
        try:
            self.timer.stop()
        except Exception:
            pass
        self.glFailed.emit(self._gl_error)

    def paintGL(self) -> None:  # noqa: N802
        if not self._ready:
            self._paint_fallback_text()
            return
        try:
            self._paint_scene()
            self._painted = True
        except Exception as exc:                            # pragma: no cover
            # An unguarded exception here fires once per frame: at 60 fps that
            # is sixty error dialogs a second, which is what "battle mode
            # crashes" looks like from the outside. Fail once, say why, stop.
            self._gl_fail(exc)
            self._paint_fallback_text()

    def _paint_scene(self) -> None:
        w, h = self.width(), self.height()
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        aspect = max(0.2, w / max(1, h))
        self._projection = glmat.perspective(42.0, aspect, 0.1, 120.0)
        GL.glLoadMatrixf(self._projection)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        shake_x = math.sin(self.time * 47.0) * self.shake * 0.10
        shake_y = math.cos(self.time * 61.0) * self.shake * 0.10
        # portrait windows need to stand further back to keep the board in view
        distance = self.distance * max(1.0, 1.0 / aspect)
        eye_y = math.sin(self.pitch) * distance
        horiz = math.cos(self.pitch) * distance
        eye_x = math.sin(self.yaw) * horiz + shake_x
        eye_z = math.cos(self.yaw) * horiz + shake_y
        self._modelview = glmat.look_at((eye_x, eye_y, eye_z), self.target,
                                        (0.0, 1.0, 0.0))
        GL.glMultMatrixf(self._modelview)

        self._draw_board()
        self._draw_highlights()
        self._draw_pieces()
        self._draw_effects()

    def _paint_fallback_text(self) -> None:  # pragma: no cover
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#141821"))
            painter.setPen(QColor("#e5e7eb"))
            painter.setFont(QFont("Sans", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "3D acceleration unavailable:\n" +
                             getattr(self, "_gl_error", "unknown error"))
        finally:
            painter.end()

    def _material(self, color: Tuple[float, float, float], accent: Tuple[float, float, float],
                  alpha: float = 1.0) -> None:
        GL.glColor4f(color[0], color[1], color[2], alpha)
        GL.glMaterialfv(GL.GL_FRONT, GL.GL_AMBIENT_AND_DIFFUSE,
                        (color[0] * 0.85, color[1] * 0.85, color[2] * 0.85, alpha))
        GL.glMaterialfv(GL.GL_FRONT, GL.GL_SPECULAR, (accent[0], accent[1], accent[2], 1.0))
        GL.glMaterialf(GL.GL_FRONT, GL.GL_SHININESS, 42.0)

    def _draw_board(self) -> None:
        GL.glEnable(GL.GL_LIGHTING)
        self._material((0.46, 0.33, 0.21), (0.25, 0.25, 0.25))
        GL.glPushMatrix()
        glCallList(self._lists["board"])
        GL.glPopMatrix()
        # squares
        GL.glDisable(GL.GL_LIGHTING)
        for square in chess.SQUARES:
            file = chess.square_file(square)
            rank = chess.square_rank(square)
            light = (file + rank) % 2 == 1
            if light:
                GL.glColor3f(0.86, 0.78, 0.60)
            else:
                GL.glColor3f(0.33, 0.24, 0.17)
            x, z = square_to_xz(square, self.flipped)
            GL.glPushMatrix()
            GL.glTranslatef(x, 0.0, z)
            glCallList(self._lists["square"])
            GL.glPopMatrix()
        GL.glEnable(GL.GL_LIGHTING)

    def _draw_highlights(self) -> None:
        GL.glDisable(GL.GL_LIGHTING)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        def quad(square, color, alpha, inset: float = 0.06):
            x, z = square_to_xz(square, self.flipped)
            GL.glColor4f(color[0], color[1], color[2], alpha)
            GL.glPushMatrix()
            GL.glTranslatef(x + inset, 0.02, z + inset)
            GL.glScalef(1 - inset * 2, 1.0, 1 - inset * 2)
            glCallList(self._lists["square"])
            GL.glPopMatrix()
        if self.last_move is not None:
            for sq in (self.last_move.from_square, self.last_move.to_square):
                quad(sq, (0.95, 0.88, 0.35), 0.30)
        if self.selected is not None:
            quad(self.selected, (0.30, 0.65, 1.0), 0.42)
            for mv in self.board.legal_moves:
                if mv.from_square == self.selected:
                    target = self.board.piece_at(mv.to_square)
                    quad(mv.to_square, (1.0, 0.35, 0.30) if target else (0.35, 0.85, 0.45),
                         0.55 if target else 0.32)
        if self.hover is not None:
            quad(self.hover, (1.0, 1.0, 1.0), 0.14)
        GL.glDisable(GL.GL_BLEND)
        GL.glEnable(GL.GL_LIGHTING)

    def _draw_pieces(self) -> None:
        for square, piece in list(self.pieces.items()):
            self._draw_piece(piece)
        # a dying piece is not drawn by the square map any more, so it is
        # drawn here for as long as it still has a body
        for fight in self.fights:
            v = fight.victim_ref
            if v is not None and v.alive and v.scale > 0.02:
                self._draw_piece(v)
        for fight in self.fights:
            a = fight.attacker
            if fight.stage in ("approach", "strike"):
                self._draw_piece(a)
            elif fight.stage in ("impact", "return"):
                self._draw_piece(a)
        for walk in self.walks:
            self._draw_piece(walk.piece_ref)

    def _draw_piece(self, piece: Piece3D) -> None:
        name = PIECE_NAMES.get(piece.piece.piece_type)
        lst = self._lists.get(f"piece_{name}")
        if lst is None:
            return
        white = piece.piece.color == chess.WHITE
        self._material(WHITE_COLOR if white else BLACK_COLOR,
                       WHITE_ACCENT if white else BLACK_ACCENT)
        GL.glPushMatrix()
        GL.glTranslatef(piece.x, piece.y, piece.z)
        if piece.piece.color == chess.BLACK:
            GL.glRotatef(180.0, 0.0, 1.0, 0.0)
        if piece.yaw:
            GL.glRotatef(math.degrees(piece.yaw), 0.0, 1.0, 0.0)
        if piece.pitch:
            GL.glRotatef(math.degrees(piece.pitch), 1.0, 0.0, 0.0)
        if piece.roll:
            GL.glRotatef(math.degrees(piece.roll), 0.0, 0.0, 1.0)
        scale = piece.scale * (0.92 if piece.piece.piece_type == chess.PAWN else 1.0)
        GL.glScalef(scale, scale * piece.sy, scale)
        glCallList(lst)
        GL.glPopMatrix()

    def _draw_effects(self) -> None:
        GL.glDisable(GL.GL_LIGHTING)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        lst = self._lists.get("shard")
        for shard in self.physics.shards:
            fade = shard.fade
            GL.glColor4f(shard.color[0], shard.color[1], shard.color[2], min(1.0, fade))
            GL.glPushMatrix()
            GL.glTranslatef(shard.pos[0], shard.pos[1], shard.pos[2])
            GL.glRotatef(math.degrees(shard.rot[0]), 1, 0, 0)
            GL.glRotatef(math.degrees(shard.rot[1]), 0, 1, 0)
            GL.glRotatef(math.degrees(shard.rot[2]), 0, 0, 1)
            if shard.kind == "head":
                GL.glScalef(shard.scale * 1.35, shard.scale * 1.35, shard.scale * 1.35)
            else:
                GL.glScalef(shard.scale, shard.scale, shard.scale)
            if lst:
                glCallList(lst)
            GL.glPopMatrix()
        # sparks, in two passes so droplets can be drawn fatter than embers
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
        for size, bucket in ((2.0, False), (5.0, True)):
            GL.glPointSize(size)
            GL.glBegin(GL.GL_POINTS)
            for spark in self.physics.sparks:
                if (spark.size >= 2.6) != bucket:
                    continue
                life = max(0.0, spark.life / spark.max_life)
                GL.glColor4f(spark.color[0], spark.color[1], spark.color[2],
                             min(1.0, life * 1.35))
                GL.glVertex3f(spark.pos[0], spark.pos[1], spark.pos[2])
            GL.glEnd()
        # blood stains lying flat on the board
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        for decal in self.physics.decals:
            alpha = 0.78 * decal.fade
            r, g, b = decal.color
            GL.glColor4f(r, g, b, alpha)
            radius = decal.radius * (0.35 + 0.65 * decal.spread)
            GL.glBegin(GL.GL_TRIANGLE_FAN)
            GL.glVertex3f(decal.x, 0.012, decal.z)
            steps = len(decal.edges)
            for i in range(steps + 1):
                ang = math.tau * (i % steps) / steps
                rr = radius * decal.edges[i % steps]
                GL.glVertex3f(decal.x + math.cos(ang) * rr, 0.012,
                              decal.z + math.sin(ang) * rr)
            GL.glEnd()
        # shockwaves
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        for wave in self.physics.waves:
            life = max(0.0, wave.life / wave.max_life)
            GL.glColor4f(wave.color[0], wave.color[1], wave.color[2], life * 0.55)
            GL.glBegin(GL.GL_LINE_LOOP)
            steps = 40
            for i in range(steps):
                a = math.tau * i / steps
                GL.glVertex3f(wave.pos[0] + math.cos(a) * wave.radius,
                              0.08,
                              wave.pos[2] + math.sin(a) * wave.radius)
            GL.glEnd()
        GL.glDisable(GL.GL_BLEND)
        GL.glEnable(GL.GL_LIGHTING)

    # -- interaction -------------------------------------------------------
    def _pick(self, pos) -> Optional[chess.Square]:
        """Intersect the mouse ray with the board plane (y = 0)."""
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        viewport = (0, 0, w, h)
        model = getattr(self, "_modelview", None)
        proj = getattr(self, "_projection", None)
        if model is None or proj is None:
            return None
        try:
            near = glmat.unproject(x, h - y, 0.0, model, proj, viewport)
            far = glmat.unproject(x, h - y, 1.0, model, proj, viewport)
        except Exception:
            return None
        if near is None or far is None:
            return None
        ox, oy, oz = near
        dx, dy, dz = (far[0] - ox, far[1] - oy, far[2] - oz)
        if abs(dy) < 1e-6:
            return None
        t = -oy / dy
        if t < 0:
            return None
        return xz_to_square(ox + dx * t, oz + dz * t, self.flipped)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.button() == Qt.MouseButton.RightButton:
            self._orbiting = True
            self._last_pos = pos
            return
        square = self._pick(pos)
        if square is None:
            return
        piece = self.board.piece_at(square)
        if self.selected is not None and square != self.selected:
            move = self._move_for(self.selected, square)
            if move is not None:
                self.selected = None
                self.moveRequested.emit(move)
                return
        if piece is not None and piece.color == self.board.turn:
            self.selected = square
        else:
            self.selected = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if self._orbiting and self._last_pos is not None:
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            self.target_yaw -= dx * 0.008
            self.target_pitch = max(0.15, min(1.5, self.target_pitch + dy * 0.006))
            self._last_pos = pos
            self.update()
            return
        self.hover = self._pick(pos)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._orbiting = False
            self._last_pos = None

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
        self.distance = max(6.0, min(26.0, self.distance - delta * 0.012))
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_F:
            self.flipped = not self.flipped
            self.sync_position(self.board)
        elif event.key() == Qt.Key.Key_R:
            self.set_camera_mode("Cinematic")
        else:
            super().keyPressEvent(event)
