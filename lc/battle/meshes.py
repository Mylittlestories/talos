"""
Procedural 3D geometry for the Battle Chess board.

Nothing is loaded from disk: every piece is a surface of revolution (a lathe)
built from a profile curve, plus a few primitives for the knight.  The meshes
are compiled into OpenGL display lists once, then drawn with a transform per
piece, which keeps the frame rate high even in pure Python.
"""

from __future__ import annotations

import math
import random
from typing import List, Sequence, Tuple

Vec3 = Tuple[float, float, float]


# --------------------------------------------------------------------------
# mesh container
# --------------------------------------------------------------------------

class Mesh:
    def __init__(self):
        self.vertices: List[float] = []
        self.normals: List[float] = []
        self.triangles: int = 0

    def add_triangle(self, a: Vec3, b: Vec3, c: Vec3) -> None:
        n = _normal(a, b, c)
        for v in (a, b, c):
            self.vertices.extend(v)
            self.normals.extend(n)
        self.triangles += 1

    def add_quad(self, a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> None:
        self.add_triangle(a, b, c)
        self.add_triangle(a, c, d)

    def extend(self, other: "Mesh", offset: Vec3 = (0, 0, 0),
               scale: float = 1.0, rot_y: float = 0.0) -> None:
        cos, sin = math.cos(rot_y), math.sin(rot_y)
        for i in range(0, len(other.vertices), 3):
            x, y, z = other.vertices[i:i + 3]
            x, y, z = x * scale, y * scale, z * scale
            nx, ny, nz = other.normals[i:i + 3]
            self.vertices.append(round(x * cos + z * sin + offset[0], 5))
            self.vertices.append(y + offset[1])
            self.vertices.append(round(-x * sin + z * cos + offset[2], 5))
            self.normals.append(nx * cos + nz * sin)
            self.normals.append(ny)
            self.normals.append(-nx * sin + nz * cos)
        self.triangles += other.triangles

    def bounds(self) -> Tuple[Vec3, Vec3]:
        if not self.vertices:
            return (0, 0, 0), (0, 0, 0)
        xs = self.vertices[0::3]
        ys = self.vertices[1::3]
        zs = self.vertices[2::3]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / length, ny / length, nz / length)


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------

def lathe(profile: Sequence[Tuple[float, float]], segments: int = 24,
          close_bottom: bool = True, close_top: bool = False) -> Mesh:
    """Revolve a (radius, height) profile around the Y axis."""
    mesh = Mesh()
    pts = [(float(r), float(y)) for r, y in profile]
    for i in range(len(pts) - 1):
        r0, y0 = pts[i]
        r1, y1 = pts[i + 1]
        if r0 < 1e-6 and r1 < 1e-6:
            continue
        for s in range(segments):
            a0 = 2 * math.pi * s / segments
            a1 = 2 * math.pi * (s + 1) / segments
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            p0 = (r0 * c0, y0, r0 * s0)
            p1 = (r1 * c0, y1, r1 * s0)
            p2 = (r1 * c1, y1, r1 * s1)
            p3 = (r0 * c1, y0, r0 * s1)
            if r0 > 1e-6 and r1 > 1e-6:
                mesh.add_quad(p0, p1, p2, p3)
            elif r1 > 1e-6:                     # bottom point -> cone (faces down)
                mesh.add_triangle(p0, p1, p2)
            else:                                # top point -> cone
                mesh.add_triangle(p0, p1, p3)
    if close_bottom:
        r0, y0 = pts[0]
        if r0 > 1e-6:
            centre = (0.0, y0, 0.0)
            for s in range(segments):
                a0 = 2 * math.pi * s / segments
                a1 = 2 * math.pi * (s + 1) / segments
                mesh.add_triangle(centre,
                                  (r0 * math.cos(a0), y0, r0 * math.sin(a0)),
                                  (r0 * math.cos(a1), y0, r0 * math.sin(a1)))   # bottom, facing down
    if close_top:
        r0, y0 = pts[-1]
        if r0 > 1e-6:
            centre = (0.0, y0, 0.0)
            for s in range(segments):
                a0 = 2 * math.pi * s / segments
                a1 = 2 * math.pi * (s + 1) / segments
                mesh.add_triangle(centre,
                                  (r0 * math.cos(a1), y0, r0 * math.sin(a1)),
                                  (r0 * math.cos(a0), y0, r0 * math.sin(a0)))
    return mesh


def box(width: float, height: float, depth: float,
        centre: Vec3 = (0, 0, 0)) -> Mesh:
    mesh = Mesh()
    x, y, z = centre
    hw, hh, hd = width / 2, height / 2, depth / 2
    corners = [
        (x - hw, y - hh, z - hd), (x + hw, y - hh, z - hd),
        (x + hw, y + hh, z - hd), (x - hw, y + hh, z - hd),
        (x - hw, y - hh, z + hd), (x + hw, y - hh, z + hd),
        (x + hw, y + hh, z + hd), (x - hw, y + hh, z + hd),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3),
             (1, 2, 6, 5), (2, 3, 7, 6), (1, 5, 4, 0)]
    for a, b, c, d in faces:
        mesh.add_quad(corners[a], corners[b], corners[c], corners[d])
    return mesh


def sphere(radius: float, centre: Vec3 = (0, 0, 0), rings: int = 10,
           sectors: int = 16) -> Mesh:
    mesh = Mesh()
    cx, cy, cz = centre
    for r in range(rings):
        phi0 = math.pi * r / rings
        phi1 = math.pi * (r + 1) / rings
        for s in range(sectors):
            t0 = 2 * math.pi * s / sectors
            t1 = 2 * math.pi * (s + 1) / sectors
            p = []
            for phi, theta in ((phi0, t1), (phi1, t1), (phi1, t0), (phi0, t0)):
                p.append((cx + radius * math.sin(phi) * math.cos(theta),
                          cy + radius * math.cos(phi),
                          cz + radius * math.sin(phi) * math.sin(theta)))
            mesh.add_quad(*p)
    return mesh


def disc(radius: float, y: float = 0.0, segments: int = 24) -> Mesh:
    mesh = Mesh()
    centre = (0.0, y, 0.0)
    for s in range(segments):
        a0 = 2 * math.pi * s / segments
        a1 = 2 * math.pi * (s + 1) / segments
        mesh.add_triangle(centre,
                          (radius * math.cos(a1), y, radius * math.sin(a1)),
                          (radius * math.cos(a0), y, radius * math.sin(a0)))
    return mesh


# --------------------------------------------------------------------------
# piece profiles (radius, height) - heights are in board squares
# --------------------------------------------------------------------------

PROFILES = {
    "pawn": [
        (0.00, 0.00), (0.40, 0.00), (0.40, 0.06), (0.34, 0.10), (0.22, 0.14),
        (0.17, 0.20), (0.14, 0.34), (0.17, 0.40), (0.24, 0.44), (0.20, 0.48),
        (0.16, 0.50), (0.23, 0.60), (0.26, 0.68), (0.22, 0.78), (0.13, 0.86),
        (0.00, 0.92),
    ],
    "rook": [
        (0.00, 0.00), (0.42, 0.00), (0.42, 0.07), (0.34, 0.12), (0.27, 0.18),
        (0.25, 0.30), (0.26, 0.55), (0.30, 0.62), (0.36, 0.68), (0.38, 0.86),
        (0.38, 0.95), (0.44, 0.95), (0.44, 1.20), (0.00, 1.20),
    ],
    "knight": None,      # built from primitives
    "bishop": [
        (0.00, 0.00), (0.40, 0.00), (0.40, 0.07), (0.32, 0.12), (0.25, 0.18),
        (0.22, 0.32), (0.24, 0.42), (0.30, 0.50), (0.26, 0.56), (0.18, 0.60),
        (0.20, 0.70), (0.24, 0.80), (0.22, 0.92), (0.15, 1.02), (0.08, 1.12),
        (0.00, 1.20),
    ],
    "queen": [
        (0.00, 0.00), (0.44, 0.00), (0.44, 0.07), (0.35, 0.12), (0.28, 0.18),
        (0.24, 0.34), (0.22, 0.55), (0.26, 0.70), (0.32, 0.82), (0.30, 0.90),
        (0.40, 0.96), (0.44, 1.02), (0.40, 1.10), (0.00, 1.10),
    ],
    "king": [
        (0.00, 0.00), (0.45, 0.00), (0.45, 0.07), (0.36, 0.12), (0.29, 0.18),
        (0.25, 0.34), (0.23, 0.58), (0.27, 0.74), (0.33, 0.86), (0.31, 0.94),
        (0.40, 1.00), (0.44, 1.06), (0.40, 1.14), (0.00, 1.14),
    ],
}


def knight_mesh() -> Mesh:
    """A stylised horse head assembled from primitives - the classic knight."""
    mesh = Mesh()
    mesh.extend(lathe([(0.0, 0.0), (0.42, 0.0), (0.42, 0.07), (0.33, 0.12),
                       (0.26, 0.18), (0.23, 0.28), (0.24, 0.34)], segments=20))
    # neck rising forward
    mesh.extend(box(0.30, 0.50, 0.26, centre=(0.02, 0.55, -0.02)))
    # head / muzzle
    mesh.extend(box(0.26, 0.24, 0.52, centre=(0.0, 0.82, 0.12)))
    mesh.extend(box(0.20, 0.16, 0.22, centre=(0.0, 0.74, 0.40)))
    # ears
    mesh.extend(box(0.07, 0.16, 0.07, centre=(-0.08, 1.00, -0.02)))
    mesh.extend(box(0.07, 0.16, 0.07, centre=(0.08, 1.00, -0.02)))
    # mane
    for i in range(4):
        mesh.extend(sphere(0.075, centre=(0.0, 0.92 - i * 0.15, -0.16 + i * 0.05),
                           rings=6, sectors=10))
    # eyes
    mesh.extend(sphere(0.045, centre=(-0.13, 0.87, 0.16), rings=5, sectors=8))
    mesh.extend(sphere(0.045, centre=(0.13, 0.87, 0.16), rings=5, sectors=8))
    return mesh


def piece_mesh(piece_type: int, quality: str = "High") -> Mesh:
    import chess
    segments = {"Low": 12, "Medium": 18, "High": 26, "Ultra": 40}.get(quality, 26)
    name = {chess.PAWN: "pawn", chess.ROOK: "rook", chess.KNIGHT: "knight",
            chess.BISHOP: "bishop", chess.QUEEN: "queen", chess.KING: "king"}[piece_type]
    if name == "knight":
        return knight_mesh()
    mesh = lathe(PROFILES[name], segments=segments)
    if name == "rook":
        # crenellations: four little towers around the rim
        for i in range(4):
            angle = math.pi / 4 + i * math.pi / 2
            r = 0.30
            x, z = r * math.cos(angle), r * math.sin(angle)
            mesh.extend(box(0.16, 0.18, 0.16, centre=(x, 1.12, z)))
    elif name == "queen":
        for i in range(8):
            angle = 2 * math.pi * i / 8
            r = 0.36
            mesh.extend(sphere(0.075, centre=(r * math.cos(angle), 1.08,
                                              r * math.sin(angle)),
                               rings=5, sectors=8))
    elif name == "king":
        # crown pearls and a cross on top
        for i in range(6):
            angle = 2 * math.pi * i / 6
            r = 0.33
            mesh.extend(sphere(0.062, centre=(r * math.cos(angle), 1.05,
                                              r * math.sin(angle)),
                               rings=5, sectors=8))
        mesh.extend(box(0.09, 0.30, 0.09, centre=(0.0, 1.30, 0.0)))
        mesh.extend(box(0.24, 0.09, 0.09, centre=(0.0, 1.24, 0.0)))
    elif name == "bishop":
        mesh.extend(sphere(0.055, centre=(0.0, 1.24, 0.0), rings=5, sectors=8))
        mesh.extend(box(0.05, 0.16, 0.12, centre=(0.0, 1.00, 0.10)))
    elif name == "pawn":
        mesh.extend(sphere(0.09, centre=(0.0, 0.72, 0.0), rings=8, sectors=12))
    return mesh


# --------------------------------------------------------------------------
# board
# --------------------------------------------------------------------------

def board_mesh(bevel: float = 0.06, frame: float = 0.55) -> Mesh:
    """The playing surface plus the surrounding frame."""
    mesh = Mesh()
    half = 4.0
    # frame
    outer = half + frame
    mesh.add_quad((-outer, -0.35, -outer), (outer, -0.35, -outer),
                  (outer, -0.35, outer), (-outer, -0.35, outer))
    for (x0, z0, x1, z1) in ((-outer, -outer, outer, -half), (-outer, half, outer, outer),
                             (-outer, -half, -half, half), (half, -half, outer, half)):
        mesh.add_quad((x0, -0.35, z0), (x0, 0.02, z1), (x1, 0.02, z1), (x1, -0.35, z0))
        mesh.add_quad((x0, 0.02, z0), (x0, 0.02, z1), (x1, 0.02, z1), (x1, 0.02, z0))
    # playing surface
    for file in range(8):
        for rank in range(8):
            x0 = file - 4.0
            z0 = rank - 4.0
            inset = bevel * 0.5
            mesh.add_quad((x0 + inset, 0.0, z0 + inset), (x0 + inset, 0.0, z0 + 1 - inset),
                          (x0 + 1 - inset, 0.0, z0 + 1 - inset),
                          (x0 + 1 - inset, 0.0, z0 + inset))
    return mesh


def arena_mesh() -> Mesh:
    """A broad, stepped stone plinth beneath the board.

    It is intentionally generic fantasy scenery, generated with the rest of
    the TALOS stage rather than copied from any historical chess game. The
    shallow top leaves the board's wooden frame proud of the floor.
    """
    return lathe([
        (0.0, -0.68), (8.30, -0.68), (8.55, -0.61), (8.55, -0.49),
        (8.18, -0.40), (7.35, -0.37), (0.0, -0.37),
    ], segments=64, close_bottom=True, close_top=False)


def square_overlay_mesh() -> Mesh:
    """A single flat square used for highlights (last move, selection, hover)."""
    mesh = Mesh()
    eps = 0.01
    mesh.add_quad((0.06, 0.012, 0.06), (0.06, 0.012, 0.94 - eps),
                  (0.94 - eps, 0.012, 0.94 - eps), (0.94, 0.012, 0.94 - eps))
    return mesh


def shard_mesh(rng: random.Random, count: int = 14, size: float = 0.16) -> Mesh:
    """A cloud of angular fragments used when a piece shatters."""
    mesh = Mesh()
    for _ in range(count):
        cx, cy, cz = (rng.uniform(-0.18, 0.18), rng.uniform(0.05, 0.9),
                      rng.uniform(-0.18, 0.18))
        s = size * rng.uniform(0.45, 1.15)
        a = (cx, cy, cz)
        b = (cx + s * rng.uniform(0.5, 1.3), cy + s * rng.uniform(-0.6, 0.8),
             cz + s * rng.uniform(-0.4, 0.6))
        c = (cx + s * rng.uniform(-0.9, 0.4), cy + s * rng.uniform(-0.9, 0.5),
             cz + s * rng.uniform(0.3, 1.1))
        d = (cx + s * rng.uniform(-0.5, 0.6), cy - s * rng.uniform(0.2, 0.9),
             cz + s * rng.uniform(-0.7, 0.4))
        mesh.add_triangle(a, b, c)
        mesh.add_triangle(a, c, d)
        mesh.add_triangle(a, d, b)
        mesh.add_triangle(b, d, c)
    return mesh
