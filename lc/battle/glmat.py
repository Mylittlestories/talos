"""
Small matrix library that replaces GLU (missing from modern PyOpenGL builds).

Provides the projection matrix, the look-at view matrix and an un-project
routine for mouse picking, all as plain column-major float lists that can be
handed straight to glLoadMatrixf / glMultMatrixf.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

try:
    import numpy as _np
except Exception:                                   # pragma: no cover
    _np = None


def _normalise(v) -> Tuple[float, float, float]:
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a, b) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def perspective(fovy_degrees: float, aspect: float, near: float, far: float):
    """Column-major perspective matrix, ready for glLoadMatrixf."""
    f = 1.0 / math.tan(math.radians(fovy_degrees) / 2.0)
    m = [[f / aspect, 0.0, 0.0, 0.0],
         [0.0, f, 0.0, 0.0],
         [0.0, 0.0, (far + near) / (near - far), (2.0 * far * near) / (near - far)],
         [0.0, 0.0, -1.0, 0.0]]
    if _np is not None:
        return _np.array(m, dtype="float32").T.flatten()
    return [m[row][col] for col in range(4) for row in range(4)]


def look_at(eye: Sequence[float], centre: Sequence[float], up: Sequence[float]):
    """Column-major view matrix, ready for glMultMatrixf."""
    forward = _normalise((eye[0] - centre[0], eye[1] - centre[1], eye[2] - centre[2]))
    side = _normalise(_cross(up, forward))
    true_up = _cross(forward, side)
    m = [[side[0], side[1], side[2], -_dot(side, eye)],
         [true_up[0], true_up[1], true_up[2], -_dot(true_up, eye)],
         [forward[0], forward[1], forward[2], -_dot(forward, eye)],
         [0.0, 0.0, 0.0, 1.0]]
    if _np is not None:
        return _np.array(m, dtype="float32").T.flatten()
    return [m[row][col] for col in range(4) for row in range(4)]


def _invert(m) -> list:
    if _np is not None:
        arr = _np.array(m, dtype="float64").reshape(4, 4).T      # to math layout
        inv = _np.linalg.inv(arr)
        return list(_np.asarray(inv.T, dtype="float32").flatten())
    # 4x4 inversion by Gauss-Jordan (fallback when numpy is missing)
    a = [[float(m[c * 4 + r]) for c in range(4)] for r in range(4)]
    inv = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        a[col], a[pivot] = a[pivot], a[col]
        inv[col], inv[pivot] = inv[pivot], inv[col]
        divisor = a[col][col]
        a[col] = [value / divisor for value in a[col]]
        inv[col] = [value / divisor for value in inv[col]]
        for row in range(4):
            if row == col:
                continue
            factor = a[row][col]
            if factor:
                a[row] = [a[row][k] - factor * a[col][k] for k in range(4)]
                inv[row] = [inv[row][k] - factor * inv[col][k] for k in range(4)]
    return [inv[row][col] for col in range(4) for row in range(4)]


def unproject(win_x: float, win_y: float, win_z: float, modelview, projection,
              viewport) -> Tuple[float, float, float]:
    """Window coordinates -> world coordinates (the inverse of the pipeline)."""
    vx, vy, vw, vh = viewport
    if _np is not None:
        mv = _np.array(modelview, dtype="float64").reshape(4, 4).T
        proj = _np.array(projection, dtype="float64").reshape(4, 4).T
        inverse = _np.linalg.inv(proj @ mv)
        ndc = _np.array([
            (win_x - vx) / vw * 2.0 - 1.0,
            (win_y - vy) / vh * 2.0 - 1.0,
            2.0 * win_z - 1.0,
            1.0], dtype="float64")
        out = inverse @ ndc
        if abs(out[3]) > 1e-12:
            out = out / out[3]
        return (float(out[0]), float(out[1]), float(out[2]))
    # fallback path
    mv = [float(v) for v in modelview]
    proj = [float(v) for v in projection]
    inverse = _invert(_multiply(proj, mv))
    ndc_x = (win_x - vx) / vw * 2.0 - 1.0
    ndc_y = (win_y - vy) / vh * 2.0 - 1.0
    ndc_z = 2.0 * win_z - 1.0
    out = [0.0] * 4
    for row in range(4):
        out[row] = sum(inverse[col * 4 + row] * value
                       for col, value in enumerate((ndc_x, ndc_y, ndc_z, 1.0)))
    if abs(out[3]) > 1e-12:
        out = [value / out[3] for value in out]
    return (out[0], out[1], out[2])


def _multiply(a, b) -> list:
    """Column-major 4x4 multiply (a then b, OpenGL order)."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out
