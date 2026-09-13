"""
Procedurally generated sound effects (no audio files shipped).

Waveforms are synthesised at start-up into a temporary directory and played
with QSoundEffect: move, capture, castle, check, promote, win, lose, error,
tick (low time), battle clash and shatter.
"""

from __future__ import annotations

import math
import os
import struct
import tempfile
import wave
from typing import Dict, Optional

from PyQt6.QtCore import QUrl

try:
    from PyQt6.QtMultimedia import QSoundEffect
    HAVE_AUDIO = True
except Exception:                       # QtMultimedia / pulseaudio missing
    QSoundEffect = None
    HAVE_AUDIO = False


class SoundBank:
    SAMPLE_RATE = 22050

    RECIPES: Dict[str, Dict] = {
        "move":     dict(kind="click", freq=520, dur=0.055, decay=28, vol=0.35),
        "capture":  dict(kind="noise", freq=260, dur=0.16, decay=14, vol=0.45),
        "castle":   dict(kind="click", freq=420, dur=0.10, decay=16, vol=0.35, sweep=1.4),
        "check":    dict(kind="tone", freq=880, dur=0.20, decay=8, vol=0.35, harmonics=(1, 1.5)),
        "promote":  dict(kind="arp", freq=660, dur=0.30, decay=6, vol=0.35),
        "win":      dict(kind="arp", freq=523, dur=0.55, decay=4, vol=0.40),
        "lose":     dict(kind="arp", freq=330, dur=0.55, decay=4, vol=0.35, down=True),
        "error":    dict(kind="tone", freq=180, dur=0.16, decay=12, vol=0.30, square=True),
        "tick":     dict(kind="click", freq=1200, dur=0.03, decay=60, vol=0.25),
        "start":    dict(kind="arp", freq=440, dur=0.25, decay=6, vol=0.30),
        "clash":    dict(kind="noise", freq=180, dur=0.35, decay=6, vol=0.55),
        "shatter":  dict(kind="noise", freq=110, dur=0.70, decay=4.5, vol=0.55, sweep=0.35),
        "sword":    dict(kind="noise", freq=900, dur=0.18, decay=18, vol=0.35, sweep=0.25),
    }

    def __init__(self, enabled: bool = True, volume: float = 0.8):
        self.volume = volume
        self.available = HAVE_AUDIO and self._device_available()
        self.enabled = enabled and self.available
        self.dir = tempfile.mkdtemp(prefix="lucas_sfx_")
        self.effects: Dict[str, QSoundEffect] = {}
        if self.available:
            self._build()

    @staticmethod
    def _device_available() -> bool:
        """Never touch the audio backend when the machine has no output device:
        Qt would block for seconds per call on some platforms."""
        try:
            from PyQt6.QtMultimedia import QMediaDevices
            device = QMediaDevices.defaultAudioOutput()
            return device is not None and not device.isNull()
        except Exception:
            return False

    # -- synthesis ---------------------------------------------------------
    def _write_wav(self, path: str, samples) -> None:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLE_RATE)
            data = b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767))))
                            for s in samples)
            wf.writeframes(data)

    def _synth(self, recipe: Dict):
        rate = self.SAMPLE_RATE
        kind = recipe.get("kind", "tone")
        dur = recipe.get("dur", 0.1)
        freq = recipe.get("freq", 440.0)
        decay = recipe.get("decay", 10.0)
        vol = recipe.get("vol", 0.3)
        sweep = recipe.get("sweep", 1.0)
        n = int(rate * dur)
        out = [0.0] * n
        phase = 0.0
        rnd_state = 12345
        for i in range(n):
            t = i / rate
            env = math.exp(-decay * t)
            f = freq * (sweep + (1 - sweep) * (1 - t / max(dur, 1e-6)))
            if kind == "click":
                phase += 2 * math.pi * f / rate
                s = math.sin(phase) * 0.7 + 0.3 * math.sin(phase * 2.1)
            elif kind == "noise":
                rnd_state = (1103515245 * rnd_state + 12345) & 0x7FFFFFFF
                r = (rnd_state / 0x7FFFFFFF) * 2 - 1
                phase += 2 * math.pi * f / rate
                s = r * 0.6 + math.sin(phase) * 0.4
            elif kind == "arp":
                steps = [0, 4, 7, 12, 16]
                idx = min(len(steps) - 1, int(t / max(dur, 1e-6) * len(steps)))
                mult = 2 ** (steps[idx] / 12.0)
                if recipe.get("down"):
                    mult = 2 ** (-steps[idx] / 12.0)
                phase += 2 * math.pi * freq * mult / rate
                s = math.sin(phase) * 0.8 + math.sin(phase * 2) * 0.2
            else:
                phase += 2 * math.pi * f / rate
                harmonics = recipe.get("harmonics", (1,))
                s = sum(math.sin(phase * h) / len(harmonics) for h in harmonics)
                if recipe.get("square"):
                    s = 1.0 if s > 0 else -1.0
            out[i] = s * env * vol
        # fade the tail to avoid clicks
        fade = max(1, n // 20)
        for i in range(fade):
            out[n - 1 - i] *= i / fade
        return out

    def _build(self) -> None:
        for name, recipe in self.RECIPES.items():
            path = os.path.join(self.dir, f"{name}.wav")
            try:
                self._write_wav(path, self._synth(recipe))
                effect = QSoundEffect()  # type: ignore[misc]
                effect.setSource(QUrl.fromLocalFile(path))
                effect.setVolume(self.volume)
                self.effects[name] = effect
            except Exception:
                pass

    # -- playback ----------------------------------------------------------
    def play(self, name: str) -> None:
        if not self.enabled or not self.available:
            return
        effect = self.effects.get(name)
        if effect is not None:
            try:
                effect.stop()
                effect.play()
            except Exception:
                pass

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled) and self.available

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        for effect in self.effects.values():
            try:
                effect.setVolume(self.volume)
            except Exception:
                pass
