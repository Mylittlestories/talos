"""
Tiny rigid-body / particle physics for the Battle Chess effects.

Shards are the fragments of a shattered piece: ballistic flight with gravity,
a bounce off the board plane, angular velocity and a lifetime.  Sparks are
short-lived points used for impacts, slashes and shockwaves.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]


@dataclass
class Shard:
    pos: List[float]
    vel: List[float]
    rot: List[float]              # current euler angles
    spin: List[float]             # angular velocity
    life: float
    max_life: float
    scale: float
    color: Tuple[float, float, float]
    bounce: int = 2
    kind: str = "chunk"           # chunk | head | limb | crown

    def step(self, dt: float) -> None:
        self.vel[1] -= 9.8 * dt
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
            self.rot[i] += self.spin[i] * dt
        if self.pos[1] < 0.02:
            self.pos[1] = 0.02
            if self.vel[1] < 0:
                if self.bounce > 0:
                    self.vel[1] = -self.vel[1] * 0.42
                    self.vel[0] *= 0.72
                    self.vel[2] *= 0.72
                    self.spin = [s * 0.6 for s in self.spin]
                    self.bounce -= 1
                else:
                    self.vel = [0.0, 0.0, 0.0]
                    self.spin = [0.0, 0.0, 0.0]
        self.life -= dt

    @property
    def alive(self) -> bool:
        return self.life > 0

    @property
    def fade(self) -> float:
        return max(0.0, min(1.0, self.life / (self.max_life * 0.45)))


@dataclass
class Spark:
    pos: List[float]
    vel: List[float]
    life: float
    max_life: float
    color: Tuple[float, float, float]
    size: float = 2.0
    gravity: float = 4.0
    splat: bool = False          # leaves a stain on the board when it lands
    splat_size: float = 0.10

    def step(self, dt: float) -> None:
        self.vel[1] -= self.gravity * dt
        for i in range(3):
            self.pos[i] += self.vel[i] * dt
        if self.splat and self.pos[1] <= 0.03 and self.vel[1] < 0:
            self.pos[1] = 0.03
            self.life = 0.0        # the world turns it into a stain
        else:
            self.life -= dt

    @property
    def alive(self) -> bool:
        return self.life > 0


@dataclass
class Decal:
    """A stain on the board: irregular, grows once, then dries and fades."""

    x: float
    z: float
    radius: float
    life: float = 7.0
    max_life: float = 7.0
    color: Tuple[float, float, float] = (0.42, 0.02, 0.03)
    edges: List[float] = field(default_factory=list)
    grow: float = 0.55             # seconds spent spreading

    def __post_init__(self) -> None:
        if not self.edges:
            self.edges = [self.rng_edge() for _ in range(14)]

    def rng_edge(self) -> float:
        import random as _r
        return 0.62 + _r.random() * 0.58

    def step(self, dt: float) -> None:
        self.life -= dt

    @property
    def alive(self) -> bool:
        return self.life > 0

    @property
    def spread(self) -> float:
        """0 -> 1 over the first ``grow`` seconds."""
        elapsed = self.max_life - self.life
        return min(1.0, elapsed / max(0.01, self.grow))

    @property
    def fade(self) -> float:
        return max(0.0, min(1.0, self.life / (self.max_life * 0.55)))


@dataclass
class Shockwave:
    pos: List[float]
    radius: float = 0.1
    speed: float = 6.0
    life: float = 0.6
    max_life: float = 0.6
    color: Tuple[float, float, float] = (1.0, 0.85, 0.4)

    def step(self, dt: float) -> None:
        self.radius += self.speed * dt
        self.speed *= 0.90
        self.life -= dt

    @property
    def alive(self) -> bool:
        return self.life > 0


class PhysicsWorld:
    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.shards: List[Shard] = []
        self.sparks: List[Spark] = []
        self.waves: List[Shockwave] = []
        self.decals: List[Decal] = []
        self.gravity = 9.8

    def clear(self) -> None:
        self.shards.clear()
        self.sparks.clear()
        self.waves.clear()
        self.decals.clear()

    # -- spawn -------------------------------------------------------------
    def shatter(self, pos: Sequence[float], color: Tuple[float, float, float],
                count: int = 18, power: float = 1.0, upward: float = 1.0) -> None:
        for _ in range(count):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(0.8, 3.4) * power
            self.shards.append(Shard(
                pos=[pos[0] + self.rng.uniform(-0.1, 0.1),
                     pos[1] + self.rng.uniform(0.05, 0.85),
                     pos[2] + self.rng.uniform(-0.1, 0.1)],
                vel=[math.cos(angle) * speed,
                     self.rng.uniform(1.6, 4.6) * upward * power,
                     math.sin(angle) * speed],
                rot=[self.rng.uniform(0, math.tau) for _ in range(3)],
                spin=[self.rng.uniform(-9, 9) for _ in range(3)],
                life=self.rng.uniform(1.6, 3.0),
                max_life=3.0,
                scale=self.rng.uniform(0.5, 1.25),
                color=color))

    def burst(self, pos: Sequence[float], color: Tuple[float, float, float],
               count: int = 26, power: float = 2.2, spread: float = 1.0) -> None:
        for _ in range(count):
            angle = self.rng.uniform(0, math.tau)
            up = self.rng.uniform(0.4, 1.6)
            speed = self.rng.uniform(0.6, 2.4) * power
            self.sparks.append(Spark(
                pos=list(pos),
                vel=[math.cos(angle) * speed * spread, up * power * spread,
                     math.sin(angle) * speed * spread],
                life=self.rng.uniform(0.25, 0.75),
                max_life=0.75,
                color=color,
                size=self.rng.uniform(1.5, 4.5)))

    def slash(self, pos: Sequence[float], angle: float,
              color: Tuple[float, float, float] = (1.0, 0.95, 0.7),
              count: int = 20) -> None:
        for i in range(count):
            t = i / max(1, count - 1) - 0.5
            self.sparks.append(Spark(
                pos=[pos[0] + math.cos(angle) * t * 1.2,
                     pos[1] + 0.55 + abs(t) * 0.1,
                     pos[2] + math.sin(angle) * t * 1.2],
                vel=[math.cos(angle + math.pi / 2) * 1.4, 0.9,
                     math.sin(angle + math.pi / 2) * 1.4],
                life=0.28, max_life=0.28, color=color, size=3.0, gravity=1.2))

    def wave(self, pos: Sequence[float], color=(1.0, 0.86, 0.45),
             speed: float = 6.5) -> None:
        self.waves.append(Shockwave(pos=list(pos), speed=speed, color=color))

    # -- the messy part ----------------------------------------------------
    def blood(self, pos: Sequence[float], count: int = 30, power: float = 1.0,
              spread: float = 1.0, upward: float = 1.0,
              color: Tuple[float, float, float] = (0.46, 0.02, 0.03)) -> None:
        """A spray of droplets that stain the board where they land."""
        for _ in range(count):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(0.5, 2.6) * power * spread
            self.sparks.append(Spark(
                pos=[pos[0] + self.rng.uniform(-0.08, 0.08),
                     pos[1] + self.rng.uniform(0.1, 0.5),
                     pos[2] + self.rng.uniform(-0.08, 0.08)],
                vel=[math.cos(angle) * speed,
                     self.rng.uniform(1.2, 4.4) * upward * power,
                     math.sin(angle) * speed],
                life=self.rng.uniform(0.5, 1.2),
                max_life=1.2,
                color=color,
                size=self.rng.uniform(1.5, 4.0),
                gravity=9.8,
                splat=True,
                splat_size=self.rng.uniform(0.05, 0.16)))

    def stain(self, x: float, z: float, radius: float = 0.18,
              color: Tuple[float, float, float] = (0.42, 0.02, 0.03),
              life: float = 7.0) -> None:
        if len(self.decals) > 60:
            self.decals.pop(0)
        self.decals.append(Decal(x=x, z=z, radius=radius, life=life,
                                 max_life=life, color=color))

    def limb(self, pos: Sequence[float], kind: str = "chunk",
             color: Tuple[float, float, float] = (0.85, 0.82, 0.74),
             power: float = 1.0, scale: float = 1.0) -> Shard:
        """A body part that flies off, bounces and lies where it falls."""
        angle = self.rng.uniform(0, math.tau)
        speed = self.rng.uniform(0.8, 2.4) * power
        shard = Shard(
            pos=[pos[0], pos[1], pos[2]],
            vel=[math.cos(angle) * speed,
                 self.rng.uniform(3.2, 5.6) * power,
                 math.sin(angle) * speed],
            rot=[self.rng.uniform(0, math.tau) for _ in range(3)],
            spin=[self.rng.uniform(-14, 14) for _ in range(3)],
            life=self.rng.uniform(3.2, 4.6),
            max_life=4.6,
            scale=scale,
            color=color,
            bounce=3,
            kind=kind)
        self.shards.append(shard)
        return shard

    # -- integration -------------------------------------------------------
    def step(self, dt: float) -> None:
        for shard in self.shards:
            shard.step(dt)
        self.shards = [s for s in self.shards if s.alive]
        for spark in self.sparks:
            spark.step(dt)
            if (spark.splat and not spark.alive and spark.pos[1] <= 0.04
                    and len(self.decals) < 60):
                self.stain(spark.pos[0], spark.pos[2], spark.splat_size)
        self.sparks = [s for s in self.sparks if s.alive]
        for w in self.waves:
            w.step(dt)
        self.waves = [w for w in self.waves if w.alive]
        for d in self.decals:
            d.step(dt)
        self.decals = [d for d in self.decals if d.alive]
        if len(self.shards) > 700:
            self.shards = self.shards[-700:]
        if len(self.sparks) > 900:
            self.sparks = self.sparks[-900:]
