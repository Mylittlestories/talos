"""
The adaptive learning layer.

Two ideas do the work here:

**Spaced repetition (SM-2).**  Every drill the player meets becomes a card with
an ease factor and an interval.  Get it right and the card goes away for longer;
get it wrong and it comes back tomorrow.  Fast, confident answers stretch the
interval further, hints shrink it, and a card that keeps slipping is flagged as
*leeched* and pushed to the front of the queue.

**A skill rating per theme.**  Tactics, mates, endgames, strategy, openings,
calculation, visualisation and memory each carry an Elo-style rating that moves
against the difficulty of whatever was just attempted, so the app can tell the
difference between "you missed a mate in one" and "you missed a mate in four".
The rating drives the mastery bars and decides what to serve next.

Everything lives in three tables in the user's ``lucas.db``
(``learning_cards``, ``learning_skills``, ``learning_log``), so progress
survives restarts and sits next to the Lucas data it describes.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

DAY = 86400.0

#: The skills the coach tracks, in the order they are shown.
SKILLS: Tuple[Tuple[str, str], ...] = (
    ("tactics", "Tactics - forks, pins, discovered attacks"),
    ("mates", "Mates - finding forced mate"),
    ("endgames", "Endgames - technique with few pieces"),
    ("strategy", "Strategy - the STS-style positional tests"),
    ("openings", "Openings - remembering the theory"),
    ("calculation", "Calculation - guess the move, long lines"),
    ("visualisation", "Visualisation - blindfold, squares, routes"),
    ("memory", "Memory - repetition and recall drills"),
)

SKILL_NAMES = [key for key, _ in SKILLS]
SKILL_LABELS = {key: label.split(" - ")[0] for key, label in SKILLS}

#: Session names -> skill.  Anything unlisted falls back to tactics.
SESSION_SKILL = {
    "Tactics": "tactics", "Everest": "tactics", "Resistance": "tactics",
    "Mates": "mates",
    "Endings": "endgames", "MicElo": "endgames",
    "STS": "strategy", "Positional": "strategy",
    "Openings": "openings",
    "Guess": "calculation",
    "Blindfold": "visualisation", "Squares": "visualisation",
    "Routes": "visualisation", "Square colours": "visualisation",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_cards (
    key         TEXT PRIMARY KEY,
    set_id      INTEGER NOT NULL DEFAULT 0,
    item_id     INTEGER NOT NULL DEFAULT 0,
    skill       TEXT NOT NULL,
    ease        REAL NOT NULL DEFAULT 2.5,
    interval    REAL NOT NULL DEFAULT 0.0,
    due         REAL NOT NULL DEFAULT 0.0,
    reps        INTEGER NOT NULL DEFAULT 0,
    lapses      INTEGER NOT NULL DEFAULT 0,
    streak      INTEGER NOT NULL DEFAULT 0,
    seen        INTEGER NOT NULL DEFAULT 0,
    solved      INTEGER NOT NULL DEFAULT 0,
    seconds     REAL NOT NULL DEFAULT 0.0,
    last_ms     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS learning_skills (
    skill       TEXT PRIMARY KEY,
    rating      REAL NOT NULL DEFAULT 1000.0,
    seen        INTEGER NOT NULL DEFAULT 0,
    solved      INTEGER NOT NULL DEFAULT 0,
    last_ms     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS learning_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    set_id      INTEGER NOT NULL DEFAULT 0,
    item_id     INTEGER NOT NULL DEFAULT 0,
    skill       TEXT NOT NULL,
    solved      INTEGER NOT NULL,
    seconds     REAL NOT NULL DEFAULT 0.0,
    hints       INTEGER NOT NULL DEFAULT 0,
    interval    REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_cards_due ON learning_cards(due);
CREATE INDEX IF NOT EXISTS idx_cards_skill ON learning_cards(skill);
"""


def skill_for_category(category: Optional[str], fallback: str = "tactics") -> str:
    """Map a Lucas puzzle category onto one of our skills."""
    text = (category or "").lower()
    if "mate" in text:
        return "mates"
    if "opening" in text:
        return "openings"
    if text.startswith(("sts", "positional", "strategy")):
        return "strategy"
    if any(text.startswith(code) for code in ("p", "q", "r", "b", "n")):
        # Lucas names its endgame sets after the pieces left on the board:
        # "R_P", "Q_P", "NP", "BP", "P" and friends.
        return "endgames"
    if "end" in text:
        return "endgames"
    if "guess" in text or "calc" in text:
        return "calculation"
    return fallback


def skill_for_session(name: str) -> str:
    """Map a training session's display name onto one of our skills."""
    if not name:
        return "tactics"
    for key, skill in SESSION_SKILL.items():
        if key.lower() in name.lower():
            return skill
    return "tactics"


def difficulty_rating(difficulty: float) -> float:
    """Lucas stores difficulty as 0..5; turn that into an Elo-ish number."""
    return 700.0 + max(0.0, min(5.0, float(difficulty))) * 300.0


@dataclass
class Card:
    """One drill, and how well it is remembered."""
    key: str
    set_id: int = 0
    item_id: int = 0
    skill: str = "tactics"
    ease: float = 2.5
    interval: float = 0.0          # days
    due: float = 0.0               # unix time
    reps: int = 0
    lapses: int = 0
    streak: int = 0
    seen: int = 0
    solved: int = 0
    seconds: float = 0.0
    last_ms: int = 0

    # -- derived ---------------------------------------------------------
    @property
    def is_due(self) -> bool:
        return self.due <= time.time()

    @property
    def leech(self) -> bool:
        """A card that keeps slipping: show it again and again until it sticks."""
        return self.lapses >= 4 and self.seen >= 6

    @property
    def retention(self) -> float:
        return self.solved / max(1, self.seen)

    def days_overdue(self) -> float:
        return max(0.0, (time.time() - self.due) / DAY)


@dataclass
class Skill:
    rating: float = 1000.0
    seen: int = 0
    solved: int = 0
    last_ms: int = 0

    @property
    def mastery(self) -> float:
        """0..100, where 100 is a strong club player's grasp of the theme."""
        return max(0.0, min(100.0, (self.rating - 700.0) / 1500.0 * 100.0))

    @property
    def accuracy(self) -> float:
        return self.solved / max(1, self.seen)


class Learner:
    """Spaced repetition + per-skill ratings, persisted in SQLite."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.cards: Dict[str, Card] = {}
        self.skills: Dict[str, Skill] = {name: Skill() for name in SKILL_NAMES}
        self._ensure_schema()
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        try:
            self.db.executescript(SCHEMA)
            self.db.commit()
        except Exception:
            pass

    def _load(self) -> None:
        try:
            for row in self.db.execute("SELECT * FROM learning_cards"):
                self.cards[row["key"]] = Card(
                    key=row["key"], set_id=row["set_id"], item_id=row["item_id"],
                    skill=row["skill"], ease=row["ease"], interval=row["interval"],
                    due=row["due"], reps=row["reps"], lapses=row["lapses"],
                    streak=row["streak"], seen=row["seen"], solved=row["solved"],
                    seconds=row["seconds"], last_ms=row["last_ms"])
        except Exception:
            pass
        try:
            for row in self.db.execute("SELECT * FROM learning_skills"):
                self.skills[row["skill"]] = Skill(
                    rating=row["rating"], seen=row["seen"], solved=row["solved"],
                    last_ms=row["last_ms"])
        except Exception:
            pass
        if not hasattr(self.db, "row_factory") or self.db.row_factory is None:
            # the loader above needs dict rows; fall back to a plain re-read
            self._load_plain()

    def _load_plain(self) -> None:
        try:
            for row in self.db.execute(
                    "SELECT key,set_id,item_id,skill,ease,interval,due,reps,"
                    "lapses,streak,seen,solved,seconds,last_ms FROM learning_cards"):
                self.cards[row[0]] = Card(*row)
        except Exception:
            pass

    def _save_card(self, card: Card) -> None:
        self.db.execute(
            "INSERT INTO learning_cards(key,set_id,item_id,skill,ease,interval,"
            "due,reps,lapses,streak,seen,solved,seconds,last_ms)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET ease=excluded.ease,"
            " interval=excluded.interval, due=excluded.due, reps=excluded.reps,"
            " lapses=excluded.lapses, streak=excluded.streak, seen=excluded.seen,"
            " solved=excluded.solved, seconds=excluded.seconds,"
            " last_ms=excluded.last_ms",
            (card.key, card.set_id, card.item_id, card.skill, card.ease,
             card.interval, card.due, card.reps, card.lapses, card.streak,
             card.seen, card.solved, card.seconds, card.last_ms))

    def _save_skill(self, name: str, skill: Skill) -> None:
        self.db.execute(
            "INSERT INTO learning_skills(skill,rating,seen,solved,last_ms)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(skill) DO UPDATE SET rating=excluded.rating,"
            " seen=excluded.seen, solved=excluded.solved,"
            " last_ms=excluded.last_ms",
            (name, skill.rating, skill.seen, skill.solved, skill.last_ms))

    # ------------------------------------------------------------------
    # the heart of it
    # ------------------------------------------------------------------
    @staticmethod
    def card_key(set_id: int, item_id: int) -> str:
        return f"{int(set_id)}:{int(item_id)}"

    def get(self, set_id: int, item_id: int, skill: str = "tactics") -> Card:
        key = self.card_key(set_id, item_id)
        card = self.cards.get(key)
        if card is None:
            card = Card(key=key, set_id=int(set_id), item_id=int(item_id),
                        skill=skill)
            self.cards[key] = card
        return card

    def record(self, set_id: int, item_id: int, solved: bool, seconds: float = 0.0,
               hints: int = 0, skill: str = "tactics",
               difficulty: float = 2.0) -> Card:
        """Score one attempt: move the card and the skill rating."""
        now = time.time()
        card = self.get(set_id, item_id, skill)
        card.skill = skill
        card.seen += 1
        card.seconds = seconds
        card.last_ms = int(now * 1000)
        if solved:
            card.solved += 1
            card.streak += 1
        else:
            card.streak = 0

        # ---- SM-2 ------------------------------------------------------
        if solved and hints == 0:
            quality = 5
        elif solved:
            quality = 4 - min(2, hints - 1)
        else:
            quality = 2 if card.streak == 0 and card.seen > 3 else 1

        if quality < 3:
            card.reps = 0
            card.lapses += 1
            card.interval = 0.0
        else:
            if card.reps == 0:
                card.interval = 1.0
            elif card.reps == 1:
                card.interval = 6.0
            else:
                card.interval = max(1.0, card.interval * card.ease)
            if seconds > 0 and seconds < 12.0 and quality == 5:
                card.interval *= 1.18          # answered quickly, remember longer
            if hints:
                card.interval *= max(0.5, 1.0 - 0.18 * hints)
            card.interval = min(card.interval, 365.0)
            card.reps += 1

        card.ease = max(1.3, min(2.8,
                                 card.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))))
        card.due = now + card.interval * DAY

        # ---- the skill rating ------------------------------------------
        state = self.skills.setdefault(skill, Skill())
        target = difficulty_rating(difficulty)
        expected = 1.0 / (1.0 + 10 ** ((target - state.rating) / 400.0))
        actual = 1.0 if solved else 0.0
        if solved and hints:
            actual = 0.65
        k = 28.0 / (1.0 + state.seen / 45.0)
        state.rating = max(400.0, min(2600.0, state.rating + k * (actual - expected)))
        state.seen += 1
        state.solved += 1 if solved else 0
        state.last_ms = int(now * 1000)

        try:
            self._save_card(card)
            self._save_skill(skill, state)
            self.db.execute(
                "INSERT INTO learning_log(ts,set_id,item_id,skill,solved,"
                "seconds,hints,interval) VALUES(?,?,?,?,?,?,?,?)",
                (int(now), int(set_id), int(item_id), skill, 1 if solved else 0,
                 seconds, hints, card.interval))
            self.db.commit()
        except Exception:
            pass
        return card

    # ------------------------------------------------------------------
    # what to study next
    # ------------------------------------------------------------------
    def due_cards(self, limit: int = 40, skill: Optional[str] = None) -> List[Card]:
        """Reviews that are ready now, most overdue first."""
        now = time.time()
        rows = [c for c in self.cards.values()
                if c.due <= now and (skill is None or c.skill == skill)]
        rows.sort(key=lambda c: (not c.leech, -c.days_overdue(), c.retention))
        return rows[:limit]

    def due_count(self) -> int:
        now = time.time()
        return sum(1 for c in self.cards.values() if c.due <= now)

    def weakest_skills(self, count: int = 3) -> List[Tuple[str, float]]:
        rows = [(name, self.skills.get(name, Skill()).rating) for name in SKILL_NAMES]
        rows.sort(key=lambda kv: (self.skills.get(kv[0], Skill()).seen == 0, kv[1]))
        return rows[:count]

    def plan(self, count: int = 20, set_id: Optional[int] = None) -> List[Tuple[int, int, str]]:
        """A mixed queue: overdue reviews, then leeches, then weak themes.

        Returns ``(set_id, item_id, reason)`` triples, ready to be turned into
        training tasks.
        """
        plan: List[Tuple[int, int, str]] = []
        seen_keys = set()
        due = self.due_cards(limit=count)
        for card in due:
            reason = "leech" if card.leech else "review"
            plan.append((card.set_id, card.item_id, reason))
            seen_keys.add(card.key)
        for key, card in self.cards.items():
            if len(plan) >= count:
                break
            if card.leech and key not in seen_keys:
                plan.append((card.set_id, card.item_id, "leech"))
                seen_keys.add(key)
        return plan[:count]

    def new_items(self, skill: Optional[str], limit: int = 10,
                  set_id: Optional[int] = None) -> List[Tuple[int, int]]:
        """Unseen drills for a theme, taken from the Lucas database."""
        where, args = [], []
        if set_id is not None:
            where.append("set_id = ?")
            args.append(int(set_id))
        sql = ("SELECT id, set_id, category FROM puzzles")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY RANDOM() LIMIT 400"
        out: List[Tuple[int, int]] = []
        try:
            for row in self.db.execute(sql, args):
                item_id, item_set, category = row[0], row[1], row[2]
                key = self.card_key(item_set, item_id)
                if key in self.cards:
                    continue
                if skill and skill_for_category(category) != skill:
                    continue
                out.append((int(item_set), int(item_id)))
                if len(out) >= limit:
                    break
        except Exception:
            return []
        return out

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def forecast(self, days: int = 7) -> List[Tuple[str, int]]:
        """How many reviews come due on each of the next few days."""
        import datetime
        buckets: List[Tuple[str, int]] = []
        now = time.time()
        for offset in range(days):
            start = now + offset * DAY
            end = start + DAY
            label = datetime.date.fromtimestamp(start).strftime("%a %d")
            buckets.append((label, sum(1 for c in self.cards.values()
                                       if start <= c.due < end)))
        return buckets

    def retention(self, window: int = 200) -> float:
        try:
            rows = self.db.execute(
                "SELECT solved FROM learning_log ORDER BY id DESC LIMIT ?",
                (window,)).fetchall()
        except Exception:
            return 0.0
        if not rows:
            return 0.0
        return sum(1 for r in rows if r[0]) / len(rows)

    def mastery(self, skill: str) -> float:
        return self.skills.get(skill, Skill()).mastery

    def summary(self) -> Dict:
        recent = self.retention(200)
        return {
            "cards": len(self.cards),
            "due": self.due_count(),
            "reviews": sum(c.seen for c in self.cards.values()),
            "retention": recent,
            "skills": {name: {
                "rating": round(self.skills.get(name, Skill()).rating),
                "mastery": round(self.mastery(name), 1),
                "seen": self.skills.get(name, Skill()).seen,
                "accuracy": round(self.skills.get(name, Skill()).accuracy * 100),
            } for name in SKILL_NAMES},
            "weakest": [name for name, _ in self.weakest_skills(3)],
            "forecast": self.forecast(7),
        }

    def advice(self) -> str:
        """One sentence telling the player what to do next."""
        due = self.due_count()
        if due >= 10:
            return (f"{due} reviews are waiting - clear the queue first, "
                    "that is where the rating is won.")
        weak = self.weakest_skills(1)
        if weak and self.skills.get(weak[0][0], Skill()).seen:
            label = SKILL_LABELS.get(weak[0][0], weak[0][0])
            return (f"Your weakest theme is {label} "
                    f"({self.mastery(weak[0][0]):.0f}% mastered). "
                    "Twenty minutes there is worth an hour anywhere else.")
        if not self.cards:
            return ("Nothing logged yet. Train any mode - every drill you "
                    "answer is remembered and brought back at the right time.")
        return "Everything is reviewed. Add new material to keep climbing."

    def reset(self) -> None:
        try:
            self.db.execute("DELETE FROM learning_cards")
            self.db.execute("DELETE FROM learning_skills")
            self.db.execute("DELETE FROM learning_log")
            self.db.commit()
        except Exception:
            pass
        self.cards.clear()
        self.skills = {name: Skill() for name in SKILL_NAMES}
