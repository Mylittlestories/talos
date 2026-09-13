"""
Import the real Lucas Chess data files into a single compact SQLite database.

Sources handled (all of them are plain text, so no reverse engineering of
binary blobs is needed):

  Tactics/<set>/*.fns          FEN|label|solution      tactical puzzles
  Trainings/<set>/*.fns        FEN|labels[(|solution)] endgames, mates, drills
  IntFiles/Mate/mateN.lst      FEN,move|...            mate in 1..4
  IntFiles/STS.ini             [category] FEN|cand=pts strategy test suite
  IntFiles/tactic0.bm          FEN|uci|san|pgn         extra tactic set
  IntFiles/40H-Openings.epd    EPD with id             opening positions
  IntFiles/games.mfn           pipe headers + uci      game database
  IntFiles/Everest/*.str       python literals         everest ladder
  IntFiles/endings*.ini        [kind] FEN + side       endgame drills
  IntFiles/lista60.dkv         pickle                 "60 famous positions"

Run:  python -m lc.data.importer [raw_dir] [db_path]
"""

from __future__ import annotations

import ast
import configparser
import io
import os
import pickle
import re
import sqlite3
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import chess

SCHEMA = """
CREATE TABLE IF NOT EXISTS sets (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,          -- tactics | mates | endgames | openings | sts | everest | boxing | memory
    name TEXT NOT NULL,
    source TEXT,
    description TEXT,
    config TEXT
);
CREATE TABLE IF NOT EXISTS puzzles (
    id INTEGER PRIMARY KEY,
    set_id INTEGER NOT NULL REFERENCES sets(id) ON DELETE CASCADE,
    category TEXT DEFAULT '',
    fen TEXT NOT NULL,
    solution TEXT NOT NULL,       -- space separated UCI moves
    solution_san TEXT DEFAULT '',
    label TEXT DEFAULT '',
    difficulty INTEGER DEFAULT 0,
    pgn TEXT DEFAULT '',
    ord INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_puzzles_set ON puzzles(set_id);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    fen TEXT DEFAULT '',
    moves TEXT NOT NULL,
    white TEXT, black TEXT, event TEXT, site TEXT, date TEXT, round TEXT,
    result TEXT, white_elo INTEGER, black_elo INTEGER, eco TEXT, opening TEXT,
    ply INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_games_eco ON games(eco);
CREATE TABLE IF NOT EXISTS openings (
    id INTEGER PRIMARY KEY,
    fen TEXT NOT NULL,
    eco TEXT DEFAULT '',
    name TEXT DEFAULT '',
    moves TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS progress (
    set_id INTEGER,
    item_id INTEGER,
    seen INTEGER DEFAULT 0,
    solved INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0,
    last_ms INTEGER DEFAULT 0,
    PRIMARY KEY (set_id, item_id)
);
CREATE TABLE IF NOT EXISTS saved_games (
    id INTEGER PRIMARY KEY,
    title TEXT,
    pgn TEXT,
    variant TEXT DEFAULT 'standard',
    created INTEGER,
    result TEXT
);
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

LABEL_SEP = "\xb7"
MAX_PER_FILE = 3000        # keep every set usable but the database compact
MAX_LABEL = 120
MAX_PGN = 220


def clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n - 1] + "\u2026"


def sample_even(items: List[str], cap: int) -> List[str]:
    """Keep at most `cap` lines, spread across the whole file."""
    if cap <= 0 or len(items) <= cap:
        return items
    step = len(items) / float(cap)
    return [items[int(i * step)] for i in range(cap)]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def clean_text(text: str) -> str:
    text = text.replace(LABEL_SEP, " · ")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</?b>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("$1", "").replace("$9", "")
    return text.strip()


def san_to_uci(fen: str, solution: str) -> Tuple[str, str]:
    """Convert a SAN solution line into UCI moves; returns (uci, san)."""
    board = chess.Board(fen)
    # strip move numbers, comments, variations and result tokens
    text = re.sub(r"\([^)]*\)", " ", solution)
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r"\$\d+", " ", text)
    text = re.sub(r"\d+\s*\.\.\.", " ", text)
    text = re.sub(r"\b\d+\s*\.", " ", text)
    text = re.sub(r"[!?]+", " ", text)
    text = re.sub(r"\b(1-0|0-1|1/2-1/2|\*)\b", " ", text)
    tokens = [t for t in text.replace(",", " ").split() if t]
    ucis: List[str] = []
    sans: List[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok or tok in ("-", "--"):
            continue
        try:
            move = board.parse_san(tok)
        except Exception:
            try:
                move = board.parse_uci(tok)
            except Exception:
                break
        ucis.append(move.uci())
        sans.append(board.san(move))
        board.push(move)
    return " ".join(ucis), " ".join(sans)


def valid_fen(fen: str) -> bool:
    try:
        board = chess.Board(fen)
    except Exception:
        return False
    return board.is_valid()


def difficulty_from_label(label: str) -> int:
    m = re.search(r"Difficulty\s*([*+]+)", label)
    if m:
        return min(5, len(m.group(1)))
    stars = label.count("*")
    return min(5, stars)


# --------------------------------------------------------------------------
# parsers
# --------------------------------------------------------------------------

def parse_fns(path: str) -> Iterable[Tuple[str, str, str, str]]:
    """Yield (fen, label, solution, pgn) from a Lucas .fns file."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip("\r\n")
            if not line or "|" not in line:
                continue
            parts = line.split("|")
            fen = parts[0].strip()
            if not fen:
                continue
            label = clean_text(parts[1]) if len(parts) > 1 else ""
            solution = clean_text(parts[2]) if len(parts) > 2 else ""
            pgn = parts[3].strip() if len(parts) > 3 else ""
            yield fen, label, solution, pgn


SET_KINDS = [
    ("tactics", ("Tactics",)),
    ("mates", ("Checkmate", "Mate")),
    ("endgames", ("Endgame", "Endings", "Pawn endings", "Technique")),
    ("positional", ("Singular", "Varied positions")),
]


def guess_kind(name: str, source: str) -> str:
    hay = (name + " " + source).lower()
    if "tactic" in hay:
        return "tactics"
    if "mate" in hay or "checkmate" in hay:
        return "mates"
    if "ending" in hay or "endgame" in hay:
        return "endgames"
    if "opening" in hay:
        return "openings"
    if "singular" in hay:
        return "positional"
    return "tactics"


def import_fns_folder(conn: sqlite3.Connection, root: str, source: str,
                      kind: Optional[str] = None, default_kind: str = "tactics") -> int:
    cur = conn.cursor()
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.lower().endswith(".fns"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            category = os.path.splitext(rel)[0].replace("/", " / ")
            set_name = os.path.basename(dirpath.rstrip("/\\")) or source
            k = kind or guess_kind(set_name, rel)
            cfg = read_config(os.path.join(dirpath, "Config.ini"))
            set_id = ensure_set(cur, k, f"{set_name} · {category}", f"{source}/{rel}", "", cfg)
            count = 0
            seen = set()
            rows = [r for r in parse_fns(path) if valid_fen(r[0])]
            for fen, label, solution, pgn in sample_even(rows, MAX_PER_FILE):
                key = fen + solution
                if key in seen:
                    continue
                seen.add(key)
                uci, san = san_to_uci(fen, solution) if solution else ("", "")
                if solution and not uci:
                    continue
                cur.execute(
                    "INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                    " label, difficulty, pgn, ord) VALUES(?,?,?,?,?,?,?,?,?)",
                    (set_id, category, fen, uci, san, clip(label, MAX_LABEL),
                     difficulty_from_label(label), clip(pgn, MAX_PGN), count))
                count += 1
            if count == 0:
                cur.execute("DELETE FROM sets WHERE id=?", (set_id,))
            total += count
            conn.commit()
    return total


def read_config(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def ensure_set(cur, kind: str, name: str, source: str, desc: str, config: str = "") -> int:
    row = cur.execute("SELECT id FROM sets WHERE kind=? AND name=? AND source=?",
                      (kind, name, source)).fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO sets(kind, name, source, description, config)"
                " VALUES(?,?,?,?,?)", (kind, name, source, desc, config))
    return cur.lastrowid


def import_mate_lists(conn: sqlite3.Connection, mate_dir: str) -> int:
    cur = conn.cursor()
    total = 0
    for fn in sorted(os.listdir(mate_dir)):
        if not fn.endswith(".lst"):
            continue
        m = re.search(r"(\d+)", fn)
        n = int(m.group(1)) if m else 1
        set_id = ensure_set(cur, "mates", f"Mate in {n}", f"IntFiles/Mate/{fn}",
                            f"Direct mate in {n} moves")
        with open(os.path.join(mate_dir, fn), "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        count = 0
        chunks = [c for c in data.split("|") if "," in c]
        for chunk in sample_even(chunks, 8000):
            fen, _, mv = chunk.partition(",")
            fen, mv = fen.strip(), mv.strip()
            if not fen or not mv:
                continue
            if not valid_fen(fen):
                continue
            uci, san = san_to_uci(fen, mv)
            if not uci:
                continue
            cur.execute("INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                        " label, difficulty, ord) VALUES(?,?,?,?,?,?,?,?)",
                        (set_id, f"mate in {n}", fen, uci, san, "", min(5, n), count))
            count += 1
            total += 1
        if count == 0:
            cur.execute("DELETE FROM sets WHERE id=?", (set_id,))
        conn.commit()
    return total


def import_sts(conn: sqlite3.Connection, path: str) -> int:
    if not os.path.exists(path):
        return 0
    cur = conn.cursor()
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    sections = re.split(r"^\[(.+?)\]\s*$", content, flags=re.M)
    # sections: [pre, name1, body1, name2, body2, ...]
    for i in range(1, len(sections), 2):
        name = sections[i].strip()
        body = sections[i + 1]
        set_id = ensure_set(cur, "sts", f"STS · {name}", "IntFiles/STS.ini",
                            "Strategic Test Suite: find the best move, scored by points")
        count = 0
        for line in body.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            fen, _, rest = line.partition("|")
            fen = fen.strip()
            if not valid_fen(fen):
                continue
            cands = {}
            best = None
            best_pts = -1
            for item in rest.split(","):
                item = item.strip()
                if "=" not in item:
                    continue
                mv, _, pts = item.partition("=")
                try:
                    pts = int(pts)
                except Exception:
                    continue
                cands[mv.strip()] = pts
                if pts > best_pts:
                    best_pts, best = pts, mv.strip()
            if not best:
                continue
            uci, san = san_to_uci(fen, best)
            if not uci:
                continue
            label = f"STS {name}: " + ", ".join(f"{k} ({v})" for k, v in
                                                sorted(cands.items(), key=lambda t: -t[1])[:3])
            cur.execute("INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                        " label, difficulty, ord) VALUES(?,?,?,?,?,?,?,?)",
                        (set_id, name, fen, uci, san, label, 3, count))
            count += 1
            total += 1
        if count == 0:
            cur.execute("DELETE FROM sets WHERE id=?", (set_id,))
        conn.commit()
    return total


def import_tactic_bm(conn: sqlite3.Connection, path: str) -> int:
    if not os.path.exists(path):
        return 0
    cur = conn.cursor()
    set_id = ensure_set(cur, "tactics", "Tactics · mixed set (tactic0)",
                        "IntFiles/tactic0.bm", "Mixed tactical positions with solutions")
    total = 0
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = line.split("|")
        fen = parts[0].strip()
        if not valid_fen(fen):
            continue
        uci_raw = parts[1].strip() if len(parts) > 1 else ""
        san = clean_text(parts[2]) if len(parts) > 2 else ""
        pgn = parts[3].strip() if len(parts) > 3 else ""
        uci = ""
        if re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", uci_raw):
            uci = uci_raw
        if not uci:
            uci, san2 = san_to_uci(fen, san)
            if not uci:
                continue
            san = san2
        cur.execute("INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                    " label, difficulty, pgn, ord) VALUES(?,?,?,?,?,?,?,?,?)",
                    (set_id, "mixed", fen, uci, san, clip(san, MAX_LABEL), 3,
                     clip(pgn, MAX_PGN), total))
        total += 1
        if total % 5000 == 0:
            conn.commit()
    conn.commit()
    return total


def import_epd(conn: sqlite3.Connection, path: str, kind: str = "openings",
               name: str = "40H openings") -> int:
    if not os.path.exists(path):
        return 0
    cur = conn.cursor()
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            m = re.search(r'id\s+"([^"]*)"', line)
            eco = m.group(1) if m else ""
            fen = re.split(r"\s+id\s+", line)[0].strip().rstrip(";")
            if not valid_fen(fen):
                continue
            cur.execute("INSERT OR IGNORE INTO openings(fen, eco, name, moves)"
                        " VALUES(?,?,?,?)", (fen, eco, name, ""))
            total += 1
    conn.commit()
    return total


def import_games_mfn(conn: sqlite3.Connection, path: str, limit: int = 20000) -> int:
    """games.mfn:  Header\xb7Value|Header\xb7Value||uci moves"""
    if not os.path.exists(path):
        return 0
    cur = conn.cursor()
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "||" not in line:
                continue
            head, _, moves = line.partition("||")
            info: Dict[str, str] = {}
            for field in head.split("|"):
                if LABEL_SEP in field:
                    k, _, v = field.partition(LABEL_SEP)
                    info[k.strip().lower()] = v.strip()
            mv = moves.strip()
            if not mv:
                continue
            # validate the move list cheaply: count tokens
            tokens = mv.split()
            if len(tokens) < 4:
                continue
            def elo(key):
                try:
                    return int(float(info.get(key, "") or 0))
                except Exception:
                    return 0
            cur.execute(
                "INSERT INTO games(fen, moves, white, black, event, site, date, round,"
                " result, white_elo, black_elo, eco, opening, ply) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("", mv, info.get("white", ""), info.get("black", ""),
                 info.get("event", ""), info.get("site", ""), info.get("date", ""),
                 info.get("round", ""), info.get("result", ""),
                 elo("whiteelo"), elo("blackelo"), info.get("eco", ""), info.get("opening", ""),
                 len(tokens)))
            total += 1
            if total % 5000 == 0:
                conn.commit()
            if total >= limit:
                break
    conn.commit()
    return total


def import_everest(conn: sqlite3.Connection, everest_dir: str) -> int:
    """Kept for reference: the Everest .str files store games in Lucas' XPV
    compression, which is proprietary - Everest mode is built from the
    plain-text games.mfn database instead."""
    """Everest ladder: python-literal .str files with game collections."""
    if not os.path.isdir(everest_dir):
        return 0
    cur = conn.cursor()
    total = 0
    for fn in sorted(os.listdir(everest_dir)):
        if not fn.endswith(".str"):
            continue
        path = os.path.join(everest_dir, fn)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        data = None
        for last in (len(raw), 200000, 50000):
            try:
                data = ast.literal_eval(raw[:last])
                break
            except Exception:
                continue
        if not isinstance(data, list):
            continue
        set_id = ensure_set(cur, "everest", f"Everest · {fn[:-4].replace('_', ' ')}",
                            f"IntFiles/Everest/{fn}",
                            "Climb the ladder: win to advance to harder positions")
        count = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            games = item.get("GAMES") or []
            for g in games:
                if not isinstance(g, dict):
                    continue
                labels = dict((k, v) for k, v in (g.get("LABELS") or []))
                pv = g.get("PV") or g.get("MOVES") or ""
                if not pv:
                    continue
                fen = ""
                for k in ("FEN", "FEN0", "INITIAL"):
                    if g.get(k):
                        fen = g[k]
                        break
                # PV is a compact uci string such as "e2e4 e7e5"
                if " " not in pv and len(pv) % 4 == 0:
                    moves = " ".join(pv[i:i + 4] for i in range(0, len(pv), 4))
                else:
                    moves = pv
                cur.execute("INSERT INTO games(fen, moves, white, black, event, site,"
                            " date, round, result, white_elo, black_elo, eco, opening, ply)"
                            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (fen, moves, labels.get("White", ""), labels.get("Black", ""),
                             labels.get("Event", ""), labels.get("Site", ""),
                             labels.get("Date", ""), labels.get("Round", ""),
                             labels.get("Result", ""),
                             _int(labels.get("WhiteElo")), _int(labels.get("BlackElo")),
                             labels.get("ECO", ""), labels.get("Opening", ""), len(moves.split())))
                count += 1
                total += 1
        if count == 0:
            cur.execute("DELETE FROM sets WHERE id=?", (set_id,))
        conn.commit()
    return total


def _int(v) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def import_endings_ini(conn: sqlite3.Connection, path: str) -> int:
    if not os.path.exists(path):
        return 0
    cur = conn.cursor()
    name = os.path.basename(path)
    set_id = None
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        section = "endings"
        count = 0
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                if set_id:
                    conn.commit()
                set_id = ensure_set(cur, "endings", f"Endings · {name} · {section}",
                                    f"IntFiles/{name}", "Endgame technique drill")
                count = 0
                continue
            if set_id is None:
                set_id = ensure_set(cur, "endings", f"Endings · {name}",
                                    f"IntFiles/{name}", "Endgame technique drill")
            if "|" in line:                      # FEN|label|solution (endingsM)
                head, _, tail = line.partition("|")
                label, _, solution = tail.partition("|")
                fen = head.strip()
                if not valid_fen(fen):
                    continue
                uci, san = san_to_uci(fen, solution)
                cur.execute("INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                            " label, difficulty, ord) VALUES(?,?,?,?,?,?,?,?)",
                            (set_id, section, fen, uci, san, clip(clean_text(label), MAX_LABEL),
                             3, count))
            else:                                 # FEN + side to move
                fen = " ".join(line.split()[:6]) if len(line.split()) >= 6 else line
                if not valid_fen(fen):
                    continue
                cur.execute("INSERT INTO puzzles(set_id, category, fen, solution, solution_san,"
                            " label, difficulty, ord) VALUES(?,?,?,?,?,?,?,?)",
                            (set_id, section, fen, "", "", "", 3, count))
            count += 1
            total += 1
    conn.commit()
    return total


def import_lista60(conn: sqlite3.Connection, path: str) -> int:
    """lista60.dkv is a python2 protocol-0 pickle full of FEN strings."""
    if not os.path.exists(path):
        return 0
    data = None
    for kwargs in (dict(encoding="utf-8"), dict(encoding="latin1"),
                   dict(encoding="bytes", fix_imports=True)):
        try:
            with open(path, "rb") as fh:
                data = pickle.load(fh, **kwargs)
            break
        except Exception:
            data = None
    if data is None:
        # fall back: scrape every quoted string that looks like a FEN
        with open(path, "rb") as fh:
            blob = fh.read().decode("latin1")
        data = re.findall(r"'([1-8rnbqkpRNBQKP/ wKQkqa-h-]{15,})'", blob)
    cur = conn.cursor()
    set_id = ensure_set(cur, "tactics", "The 60 famous positions", "IntFiles/lista60.dkv",
                        "60 classic tactical / winning positions")
    total = 0

    def walk(obj):
        nonlocal total
        if isinstance(obj, str):
            fen = obj.strip()
            if valid_fen(fen):
                cur.execute("INSERT INTO puzzles(set_id, category, fen, solution,"
                            " solution_san, label, difficulty, ord) VALUES(?,?,?,?,?,?,?,?)",
                            (set_id, "60", fen, "", "", "", 3, total))
                total += 1
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                walk(item)
    walk(data)
    conn.commit()
    if total == 0:
        cur.execute("DELETE FROM sets WHERE id=?", (set_id,))
        conn.commit()
    return total


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def build_database(raw_dir: str, db_path: str, verbose: bool = True) -> Dict[str, int]:
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    stats: Dict[str, int] = {}

    def step(name, fn):
        t0 = time.time()
        try:
            n = fn()
        except Exception as exc:
            print(f"  ! {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            n = 0
        stats[name] = n
        if verbose:
            print(f"  {name:28s} {n:8d}  ({time.time() - t0:.1f}s)")

    tactics = os.path.join(raw_dir, "Tactics")
    trainings = os.path.join(raw_dir, "Trainings")
    intfiles = os.path.join(raw_dir, "IntFiles")

    if verbose:
        print("Importing Lucas Chess data ->", db_path)
    if os.path.isdir(tactics):
        step("tactics", lambda: import_fns_folder(conn, tactics, "Tactics", kind="tactics"))
    if os.path.isdir(trainings):
        step("trainings", lambda: import_fns_folder(conn, trainings, "Trainings"))
    step("mate lists", lambda: import_mate_lists(conn, os.path.join(intfiles, "Mate")))
    step("STS", lambda: import_sts(conn, os.path.join(intfiles, "STS.ini")))
    step("tactic0.bm", lambda: import_tactic_bm(conn, os.path.join(intfiles, "tactic0.bm")))
    step("40H openings", lambda: import_epd(conn, os.path.join(intfiles, "40H-Openings.epd")))
    step("games.mfn", lambda: import_games_mfn(conn, os.path.join(intfiles, "games.mfn")))
    for ini in ("endings0.ini", "endings1.ini", "endingsM.ini"):
        step(ini, lambda ini=ini: import_endings_ini(conn, os.path.join(intfiles, ini)))
    step("lista60", lambda: import_lista60(conn, os.path.join(intfiles, "lista60.dkv")))

    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('imported', ?)",
                 (str(int(time.time())),))
    conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('source', ?)", (raw_dir,))
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    return stats


def main() -> int:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    raw = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(here), "lucas_data", "raw")
    db = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "data", "lucas.db")
    stats = build_database(raw, db)
    print("total items:", sum(stats.values()))
    print("database:", db, f"({os.path.getsize(db) / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
