store.py -- the data spine of the rectification engine.

A thin, validated wrapper over a single SQLite file. UI-free and pure data:
it holds subjects, their birth data, their life-event timelines, and (populated
in later tasks) rectification runs, candidate times, and the scored-hit ledger.

Design commitments (from the frozen blueprint):
  * One SQLite file = zero-ops, trivially backed up, portable.
  * Times are stored as the person's CIVIL/local clock values plus an explicit
    utc_offset_hours. V1 does NOT resolve named timezones (historical DST is a
    notorious bug source); the offset is given directly. UT conversion happens
    only in the ephemeris layer.
  * known_time is stored for later VALIDATION/comparison only. It must never be
    fed to the rectification search -- the search sweeps the whole window blind.
  * Controlled vocabularies are validated on write, because the frozen rules are
    category-scoped and a typo'd category would silently mis-score.
"""

from __future__ import annotations

import sqlite3
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# --- Controlled vocabularies (validated on insert) ---------------------------
# Categories align with the frozen rules' `applies_to` scopes.
CATEGORIES = {"career", "education", "public", "relationship", "family", "health", "other"}
VALENCES = {"positive", "negative", "mixed", "neutral"}
# date_precision doubles as the reliability proxy in V1 (drives weight + window).
DATE_PRECISIONS = {"exact_day", "exact_month", "season", "year_only", "estimated_period"}


# =============================================================================
# Schema
# =============================================================================
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subjects (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    notes       TEXT,
    created_utc TEXT NOT NULL
);

-- One birth record per subject.
CREATE TABLE IF NOT EXISTS birth_data (
    subject_id       INTEGER PRIMARY KEY REFERENCES subjects(id) ON DELETE CASCADE,
    birth_date       TEXT NOT NULL,   -- ISO date, the civil/local calendar date
    latitude         REAL NOT NULL,   -- decimal degrees, North positive
    longitude        REAL NOT NULL,   -- decimal degrees, East positive
    utc_offset_hours REAL NOT NULL,   -- local = UT + offset  (e.g. +0:40 LMT -> 0.6667)
    tz_note          TEXT,            -- human-readable timezone note (e.g. 'LMT at 10E')
    known_time       TEXT,            -- optional 'HH:MM' local; VALIDATION ONLY, never rectified
    search_start     TEXT NOT NULL,   -- 'HH:MM' local, window start (default 00:00)
    search_end       TEXT NOT NULL    -- 'HH:MM' local, window end   (default 23:59)
);

CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY,
    subject_id     INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    category       TEXT NOT NULL,     -- controlled: see CATEGORIES
    valence        TEXT NOT NULL,     -- controlled: see VALENCES
    event_date     TEXT NOT NULL,     -- ISO date, best-estimate central date
    date_precision TEXT NOT NULL,     -- controlled: see DATE_PRECISIONS (reliability proxy)
    importance     INTEGER NOT NULL,  -- 1..10 (salience)
    notes          TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject_id);

-- Populated in later tasks (schema defined now for a stable spine).
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY,
    subject_id        INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    created_utc       TEXT NOT NULL,
    config_json       TEXT NOT NULL,  -- techniques, orbs, step_minutes, null_iterations, blind flag
    rng_seed          INTEGER NOT NULL,
    swisseph_version  TEXT NOT NULL,
    ephemeris_backend TEXT NOT NULL,
    tz_handling       TEXT NOT NULL,  -- 'explicit_utc_offset' in V1
    ruleset_id        TEXT NOT NULL,
    ruleset_hash      TEXT NOT NULL   -- fingerprint of rules.yaml, for reproducibility
);

CREATE TABLE IF NOT EXISTS candidates (
    id                            INTEGER PRIMARY KEY,
    run_id                        INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    local_time                    TEXT NOT NULL,   -- 'HH:MM' candidate birth time
    internal_fit                  REAL NOT NULL,
    percentile_among_alternatives REAL,
    evidence_coverage             REAL
);
CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id);

CREATE TABLE IF NOT EXISTS hits (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    event_id     INTEGER NOT NULL REFERENCES events(id),
    rule_id      TEXT NOT NULL,
    technique    TEXT NOT NULL,
    point        TEXT NOT NULL,
    aspect       TEXT NOT NULL,
    target       TEXT NOT NULL,
    orb          REAL NOT NULL,
    points       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hits_candidate ON hits(candidate_id);
"""


# =============================================================================
# Dataclasses (thin views over rows)
# =============================================================================
@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    notes: str | None


@dataclass(frozen=True)
class BirthData:
    subject_id: int
    birth_date: str
    latitude: float
    longitude: float
    utc_offset_hours: float
    tz_note: str | None
    known_time: str | None
    search_start: str
    search_end: str


@dataclass(frozen=True)
class Event:
    id: int
    subject_id: int
    title: str
    category: str
    valence: str
    event_date: str
    date_precision: str
    importance: int
    notes: str | None


# =============================================================================
# Connection & init
# =============================================================================
def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
def init_db(path: str) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# =============================================================================
# Writes (validated)
# =============================================================================
def add_subject(conn: sqlite3.Connection, name: str, notes: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO subjects(name, notes, created_utc) VALUES (?, ?, ?)",
        (name, notes, _utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_birth_data(
    conn: sqlite3.Connection,
    subject_id: int,
    birth_date: str,
    latitude: float,
    longitude: float,
    utc_offset_hours: float,
    tz_note: str | None = None,
    known_time: str | None = None,
    search_start: str = "00:00",
    search_end: str = "23:59",
) -> None:
    if not (-90 <= latitude <= 90):
        raise ValueError(f"latitude out of range: {latitude}")
    if not (-180 <= longitude <= 180):
        raise ValueError(f"longitude out of range: {longitude}")
    datetime.strptime(birth_date, "%Y-%m-%d")  # validate ISO date
    conn.execute(
        """INSERT OR REPLACE INTO birth_data
           (subject_id, birth_date, latitude, longitude, utc_offset_hours,
            tz_note, known_time, search_start, search_end)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, birth_date, latitude, longitude, utc_offset_hours,
         tz_note, known_time, search_start, search_end),
    )
    conn.commit()


def add_event(
    conn: sqlite3.Connection,
    subject_id: int,
    title: str,
    category: str,
    valence: str,
    event_date: str,
    date_precision: str,
    importance: int,
    notes: str | None = None,
) -> int:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {sorted(CATEGORIES)}, got {category!r}")
    if valence not in VALENCES:
        raise ValueError(f"valence must be one of {sorted(VALENCES)}, got {valence!r}")
    if date_precision not in DATE_PRECISIONS:
        raise ValueError(f"date_precision must be one of {sorted(DATE_PRECISIONS)}, got {date_precision!r}")
    if not (1 <= int(importance) <= 10):
        raise ValueError(f"importance must be 1..10, got {importance}")
    datetime.strptime(event_date, "%Y-%m-%d")  # validate ISO date
    cur = conn.execute(
        """INSERT INTO events
           (subject_id, title, category, valence, event_date, date_precision, importance, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, title, category, valence, event_date, date_precision, int(importance), notes),
    )
    conn.commit()
    return int(cur.lastrowid)


# =============================================================================
# Reads
# =============================================================================
def get_subject(conn: sqlite3.Connection, subject_id: int) -> Subject | None:
    r = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
    return Subject(r["id"], r["name"], r["notes"]) if r else None


def get_birth_data(conn: sqlite3.Connection, subject_id: int) -> BirthData | None:
    r = conn.execute("SELECT * FROM birth_data WHERE subject_id = ?", (subject_id,)).fetchone()
    if not r:
        return None
    return BirthData(
        r["subject_id"], r["birth_date"], r["latitude"], r["longitude"],
        r["utc_offset_hours"], r["tz_note"], r["known_time"],
        r["search_start"], r["search_end"],
    )


def list_events(conn: sqlite3.Connection, subject_id: int) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM events WHERE subject_id = ? ORDER BY event_date", (subject_id,)
    ).fetchall()
    return [
        Event(r["id"], r["subject_id"], r["title"], r["category"], r["valence"],
              r["event_date"], r["date_precision"], r["importance"], r["notes"])
        for r in rows
    ]


def list_subjects(conn: sqlite3.Connection) -> list[Subject]:
    rows = conn.execute("SELECT * FROM subjects ORDER BY id").fetchall()
    return [Subject(r["id"], r["name"], r["notes"]) for r in rows]


# =============================================================================
# Reproducibility helper
# =============================================================================
def ruleset_fingerprint(rules_path: str) -> str:
    """SHA-256 of the raw rules file, recorded on every run so results are
    always traceable to the exact frozen rule set that produced them."""
    with open(rules_path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
