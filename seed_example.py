"""
seed_example.py -- Task 2: prove the data spine with one real, documented chart.

Creates a fresh SQLite database and enters ALBERT EINSTEIN as a validation
subject: an AA-rated known birth time plus a public, dated life-event timeline
that spans every rule category (career/public, relationship/family, and a major
turning point). Because his birth time is independently known, he is an ideal
subject for later BLIND validation -- we can hide the 11:30 and see whether these
events recover it.

All event dates below are from the public historical record. They are
illustrative; for your own work, add your own subject the same way. NOTE: your
OWN chart is exploration-only (you already know the answer); honest validation
uses charts like this one, with independently recorded times.
"""

import os
from engine import store

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "rectify.db")

# (title, category, valence, ISO date, date_precision, importance)
EINSTEIN_EVENTS = [
    ("Marriage to Mileva Maric",              "relationship", "positive", "1903-01-06", "exact_day", 8),
    ("Special relativity published (Annus Mirabilis)", "career", "positive", "1905-09-26", "exact_day", 9),
    ("General relativity field equations presented",   "career", "positive", "1915-11-25", "exact_day", 9),
    ("Divorce from Mileva Maric",             "relationship", "negative", "1919-02-14", "exact_day", 7),
    ("Marriage to Elsa Lowenthal",            "relationship", "positive", "1919-06-02", "exact_day", 6),
    ("Eclipse confirmation -> world fame",    "public",       "positive", "1919-11-06", "exact_day", 9),
    ("Nobel Prize in Physics announced",      "career",       "positive", "1922-11-09", "exact_day", 8),
    ("Emigration to the United States",       "other",        "mixed",    "1933-10-17", "exact_day", 9),
]


def build() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # fresh build for a clean demo

    conn = store.init_db(DB_PATH)

    sid = store.add_subject(
        conn, "Albert Einstein",
        notes="Validation subject. Rodden AA (birth record). Known time kept for "
              "comparison only; never fed to rectification.",
    )
    store.set_birth_data(
        conn, sid,
        birth_date="1879-03-14",
        latitude=48 + 24 / 60,      # 48 deg 24' N
        longitude=10.0,             # 10 deg 00' E
        utc_offset_hours=40 / 60,   # LMT at 10E = +0:40 ahead of UT
        tz_note="LMT at 10E (+0:40); pre-1893 Germany, no standard zone",
        known_time="11:30",         # VALIDATION ONLY
        search_start="00:00",
        search_end="23:59",
    )
    for title, cat, val, date, prec, imp in EINSTEIN_EVENTS:
        store.add_event(conn, sid, title, cat, val, date, prec, imp)

    _report(conn, sid)
    conn.close()


def _report(conn, sid) -> None:
    subj = store.get_subject(conn, sid)
    bd = store.get_birth_data(conn, sid)
    events = store.list_events(conn, sid)

    print("=" * 74)
    print("  DATA SPINE — round-trip read-back")
    print("=" * 74)
    print(f"  Database        : {DB_PATH}")
    print(f"  Subject #{subj.id:<6}: {subj.name}")
    print(f"  Birth (local)   : {bd.birth_date}  {bd.known_time} "
          f"(known — validation only)  |  offset +{bd.utc_offset_hours*60:.0f} min")
    print(f"  Location        : {bd.latitude:.4f} N, {bd.longitude:.4f} E   ({bd.tz_note})")
    print(f"  Search window   : {bd.search_start}–{bd.search_end}  (rectification sweeps this, blind)")
    print("-" * 74)
    print(f"  TIMELINE ({len(events)} events)")
    print(f"    {'date':<12}{'cat':<13}{'val':<9}{'imp':<4}{'precision':<15}title")
    for e in events:
        print(f"    {e.event_date:<12}{e.category:<13}{e.valence:<9}"
              f"{e.importance:<4}{e.date_precision:<15}{e.title}")
    print("-" * 74)

    # category coverage vs the frozen rules' scopes
    cats = {}
    for e in events:
        cats[e.category] = cats.get(e.category, 0) + 1
    print("  Category coverage:", ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
    print("    -> career/public events feed the MC rules; relationship events feed")
    print("       the Venus/Saturn ASC rules; the turning point feeds Uranus/Pluto ASC.")
    print("=" * 74)
    print("  Data spine works: subject + birth data + timeline written and read back.")
    print("=" * 74)


if __name__ == "__main__":
    build()
